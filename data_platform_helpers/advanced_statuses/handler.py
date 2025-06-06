# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""StatusHandler handles all the status setting, ordering, and formatting operations.

This defines an event handler, which listens to the necessary events:
CollectUnitStatus, CollectAppStatus, UpdateStatus, and the action
"status-detail".
It also provides a way to set the status immediately when necessary.

Example:
class CharmOperator(ManagerStatusProtocol):
    def __init__(self, *args, **kwargs) -> None:
        self.framework.observe(
            update_status, self._on_heartbeat
        )
        # Status Handler should go *after* the listener for update_status
        # this allows update_status on the charm-side to perform any health
        # checks, before the StatusHandler recomputes statuses
        # components
        self.status = StatusHandler( # priority order
            self,
            self.upgrade,
            self.tls,
            self.backups,
            self.shard,
        )
        ...

    def _on_heartbeat() -> None:
        '''Perform any self healing/checks.

        StatusHandler will take care of computing+setting statuses for the
        update status event.
        '''
"""

import itertools
import json
from functools import cached_property, lru_cache
from io import StringIO
from logging import getLogger

from ops import Application
from ops.charm import ActionEvent, CharmBase, CollectStatusEvent, UpdateStatusEvent
from ops.framework import Object
from ops.model import StatusBase, Unit
from rich.console import Console
from rich.table import Table

from data_platform_helpers.advanced_statuses.components import PRIORITIES, StatusesState
from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectDict,
)
from data_platform_helpers.advanced_statuses.protocol import ManagerStatusProtocol
from data_platform_helpers.advanced_statuses.types import Scope
from data_platform_helpers.advanced_statuses.utils import as_status, compute_status_message

logger = getLogger(__name__)


class StatusHandler(Object):
    """The status handler collects statuses and sets the correct status.

    This is according to DA161 and DA147.
    """

    def __init__(
        self, charm: CharmBase, *components_in_priority_order: ManagerStatusProtocol
    ) -> None:
        super().__init__(parent=charm, key="status-handler")
        self.charm = charm
        self.components: tuple[ManagerStatusProtocol, ...] = components_in_priority_order
        self.framework.observe(self.charm.on.collect_unit_status, self._on_collect_unit_status)
        self.framework.observe(self.charm.on.collect_app_status, self._on_collect_app_status)
        self.framework.observe(self.charm.on.status_detail_action, self._on_status_detail_action)
        self.framework.observe(self.charm.on.update_status, self._on_update_status)

    @cached_property
    def _component_names(self) -> list[str]:
        """Names of all the components defined."""
        return [component.name for component in self.components]

    @lru_cache
    def _component_priority(self, component_name: str):
        """Retrieves the component priority from the component name."""
        if component_name not in self._component_names:
            raise ValueError(f"Invalid component name: {component_name}")
        return self._component_names.index(component_name)

    def _object(self, scope: Scope) -> Application | Unit:
        """Return the correct component to use for displaying status."""
        match scope:
            case "app":
                return self.charm.app
            case "unit":
                return self.charm.unit

    def set_running_status(
        self,
        status: StatusObject,
        scope: Scope,
        is_action: bool = False,
        # required to save async status
        statuses_state: StatusesState | None = None,
        component_name: str | None = None,
    ):
        """Immediately sets a running status.

        When called from an action, set the `is_action` flag to True so that
        the status will be displayed no matter what, even if there are some
        approved_critical_component statuses displayed.

        Blocking running statuses are cleared at the end of the hook they are set in.

        Example: TLS being enabled, shard draining, etc.

        Async statuses have their statuses saved so that they can be displayed across hooks.

        Example: backup happening in the background.

        Raises: if StatusObject isn't a running status.
        """
        critical_statuses = self._get_critical_statuses(scope)
        ops_status = as_status(status)
        match status.running, critical_statuses, is_action:
            case None, _, _:
                raise ValueError(f"Status {status} is not a running status.")
            case ("async", [], _) | ("async", _, True):
                self._object(scope).status = ops_status
                if statuses_state is None or component_name is None:
                    raise ValueError("No status component provided to store the async status.")
                statuses_state.add(status, scope, component_name)
            case "async", _, _:
                # We're not displaying the status because there's a more important status.
                logger.info(
                    "Not displaying status %s, %s critical statuses in queue",
                    status.model_dump(exclude={"short_message"}),
                    len(critical_statuses),
                )
            case "blocking", [], _:
                self._object(scope).status = ops_status
            case "blocking", _, False:
                # We're not displaying the status because there's a more important status.
                logger.info(
                    "Not displaying status %s, %s critical statuses in queue",
                    status.model_dump(exclude={"short_message"}),
                    len(critical_statuses),
                )
            case "blocking", _, True:
                # We have critical statuses but this is an action so we
                # override this status and log.
                logger.info("Overriding critical status %s", critical_statuses)
                self._object(scope).status = ops_status

    @lru_cache
    def _get_sorted_statuses(self, scope: Scope) -> list[tuple[str, StatusObject]]:
        """Retrieves the list of all statuses and sorts them according to DA-147 and DA-161.

        Statuses are ordered by status priority, and for a similar status type,
        by component priority.
        """
        statuses_by_components = StatusObjectDict.model_validate(
            {component.name: component.get_statuses(scope) for component in self.components}
        )
        current_statuses = [
            (component, item)
            for component, statuses in statuses_by_components.items()
            for item in statuses
        ]

        # Log all statuses.
        logger.info(
            json.dumps(
                {
                    "scope": scope,
                    "statuses": statuses_by_components.model_dump(
                        exclude={"__all__": {"short_message"}}
                    ),
                }
            )
        )

        return sorted(
            itertools.chain(current_statuses),
            key=lambda status: (
                -PRIORITIES.get(status[1].status, 0),
                self._component_priority(status[0]),
            ),
        )

    def _get_critical_statuses(self, scope: Scope) -> list[tuple[str, StatusObject]]:
        """Retrieves all critical statuses."""
        """Gets all critical statuses for all components."""
        all_statuses = self._get_sorted_statuses(scope)
        return [status for status in all_statuses if status[1].approved_critical_component]

    def _process_on_scope_statuses(self, scope: Scope, event: CollectStatusEvent):
        """The core logic of the status handling for a given scope."""
        all_statuses = self._get_sorted_statuses(scope)
        critical_statuses = self._get_critical_statuses(scope)

        if critical_statuses:
            # When we have critical statuses, we display it right away.
            ops_status = as_status(critical_statuses[0][1])
            event.add_status(ops_status)
            return

        if not all_statuses:
            # We don't have any status so we return and ops will display an unknown status.
            return

        # The list of all statuses is a list of tuples.
        # Each tuple contains first the component and then the status, so we
        # get the first element, and then the second item of the tuple.
        first_status = all_statuses[0][1]

        important_statuses = len(
            [status for status in all_statuses if status[1].status != "active"]
        )
        actions_to_run = len(list(filter(lambda x: x[1].action is not None, all_statuses)))
        if important_statuses > 1:
            # We have many statuses so we display the full line.
            event.add_status(
                StatusBase.from_name(
                    first_status.status,
                    compute_status_message(first_status, actions_to_run, important_statuses - 1),
                )
            )
        else:
            # Only one status which is important, let's log it.
            event.add_status(as_status(first_status))

    def _on_collect_unit_status(self, event: CollectStatusEvent) -> None:
        """Handles collect_unit_status event.

        Retrieves the previously set statuses of the components for the unit
        status and then: prioritises, logs, and shows status info.

        Note: prioritisation of statuses is performed according to DA147,
        offering addition customisation over the ops default_status operation.
        """
        # log all statuses + set status + clear any blocking running statuses.
        self._process_on_scope_statuses(scope="unit", event=event)

    def _on_collect_app_status(self, event: CollectStatusEvent) -> None:
        """Handles collect_app_status event.

        Retrieves the previously set statuses of the components for the app
        status and: priorities, logs, and shows status info.

        Note: prioritisation of statuses is performed according to DA147,
        offering addition customisation over the ops default_status operation.
        """
        self._process_on_scope_statuses(scope="app", event=event)

    def _recompute_statuses_for_scope(self, scope: Scope, manager: ManagerStatusProtocol):
        """Recomputes for a specific scope."""
        manager.state.statuses.clear(scope, component=manager.name)
        statuses = manager.get_statuses(scope, recompute=True)
        logger.debug(f"Recomputed statuses for {scope=}: {statuses}")
        for status in statuses:
            manager.state.statuses.add(status=status, scope=scope, component=manager.name)

    def _recompute_statuses(self):
        """Recompute all statuses for all components."""
        for manager in self.components:
            # For unit
            self._recompute_statuses_for_scope("unit", manager)
            # We don't recompute statuses for the app if we're not leader.
            if not self.charm.unit.is_leader():
                continue
            self._recompute_statuses_for_scope("app", manager)

    def _on_status_detail_action(self, event: ActionEvent) -> None:
        """Handles status-detail action.

        This action has an optional boolean argument `recompute`.
        If recompute = True, it will recompute all statuses, cache the results
        in the databag, and output it.
        """
        logger.debug("Getting all statuses")
        if recompute := event.params.get("recompute", False):
            self._recompute_statuses()

        event.log(f"{'Recomputed' if recompute else 'Stored'} statuses:")

        current_app_statuses = self._get_sorted_statuses(scope="app")
        current_unit_statuses = self._get_sorted_statuses(scope="unit")
        logger.debug(f"{current_app_statuses=}")
        logger.debug(f"{current_unit_statuses=}")

        event.log(self.format_statuses("app", current_app_statuses))
        event.log(self.format_statuses("unit", current_unit_statuses))

        event.set_results(
            {
                "json-output": {
                    "app": self.json_output(current_app_statuses),
                    "unit": self.json_output(current_unit_statuses),
                },
            }
        )

    def _on_update_status(self, event: UpdateStatusEvent) -> None:
        """Recomputes + stores all statuses for the components.

        Note: The charm-code will still listen to update_status to perform self healing.
        """
        self._recompute_statuses()

    @staticmethod
    def format_statuses(scope: Scope, statuses: list[tuple[str, StatusObject]]) -> str:
        """Formats the statuses to display a fancy array."""
        table = Table(title=f"{scope.capitalize()} Statuses")

        table.add_column("Status", no_wrap=True)
        table.add_column("Component Name", no_wrap=True)
        table.add_column("Message", overflow="fold")
        table.add_column("Action", overflow="fold")
        table.add_column("Reason", overflow="fold")

        for component_name, status in statuses:
            table.add_row(
                *[
                    status.status.capitalize(),
                    component_name,
                    status.message,
                    status.action or "N/A",
                    status.check or "N/A",
                ]
            )

        out_f = StringIO()
        console = Console(file=out_f, width=79)
        console.print(table)

        return out_f.getvalue()

    @staticmethod
    def json_output(
        statuses: list[tuple[str, StatusObject]],
    ) -> list[dict[str, str]]:
        """Formats in json."""
        res: list[dict[str, str]] = []
        for component_name, status in statuses:
            res.append(
                {
                    "Status": status.status.capitalize(),
                    "Component Name": component_name,
                    "Message": status.message,
                    "Action": status.action or "N/A",
                    "Reason": status.check or "N/A",
                }
            )
        return res
