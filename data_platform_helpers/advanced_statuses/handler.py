# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""StatusHandler handles all the status setting, ordering, and formatting operations.

This defines an event handler, which listens to the necessary events:
CollectUnitStatus, CollectAppStatus, UpdateStatus, and the action
"status-detail".
It also provides a way to set the status immediately when necessary.

Example:
class CharmOperator():
    def __init__() -> None:
        self.framework.observe(
            update_status, self._on_heartbeat
        )
        # Status Handler should go *after* the listener for update_status
        # this allows update_status on the charm-side to perform any health
        # checks, before the StatusHandler recomputes statuses
        # components
        self.status = StatusHandler( # priority order
            self.upgrade.status_component,
            self.tls.status_component,
            self.backups.status_component,
            self.shard.status_component
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
from typing import get_args

from ops import Application
from ops.charm import ActionEvent, CharmBase, CollectStatusEvent, UpdateStatusEvent
from ops.framework import Object
from ops.model import ActiveStatus, StatusBase, Unit
from rich.console import Console
from rich.table import Table

from data_platform_helpers.advanced_statuses.components import (
    PRIORITIES,
    ComponentStatuses,
)
from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectDict,
)
from data_platform_helpers.advanced_statuses.protocol import ManagerStatusProtocol
from data_platform_helpers.advanced_statuses.types import Scope

logger = getLogger(__name__)


class StatusHandler(Object):
    """The status handler collects statuses and sets the correct status.

    This is according to DA161 and DA147.
    """

    def __init__(
        self, charm: CharmBase, *components_in_priorty_order: ManagerStatusProtocol
    ) -> None:
        super().__init__(parent=charm, key="status-handler")
        self.charm = charm
        self.components: tuple[ManagerStatusProtocol, ...] = components_in_priorty_order
        self.framework.observe(self.charm.on.collect_unit_status, self._on_collect_unit_status)
        self.framework.observe(self.charm.on.collect_app_status, self._on_collect_app_status)
        self.framework.observe(self.charm.on.status_detail_action, self._on_status_detail_action)
        self.framework.observe(self.charm.on.update_status, self._on_update_status)

    @cached_property
    def components_statuses(self) -> list[ComponentStatuses]:
        """All components statuses."""
        return [component.component_statuses for component in self.components]

    @cached_property
    def _component_names(self) -> list[str]:
        return [component.name for component in self.components_statuses]

    @lru_cache
    def _component_priority(self, component_name: str):
        """Retrieves the component priority from the component name."""
        if component_name not in self._component_names:
            raise ValueError(f"Invalid component name: {component_name}")
        return self._component_names.index(component_name)

    def object(self, scope: Scope) -> Application | Unit:
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
        async_status_component: ComponentStatuses | None = None,
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
        statuses = self._get_critical_statuses(scope)
        match status.running, statuses, is_action:
            case None, _, _:
                raise ValueError(f"Status {status} is not a running status.")
            case "async", [], _:
                self.object(scope).status = status.status
                if async_status_component is None:
                    raise ValueError("No status component provided to store the async status.")
                async_status_component.add(status, scope)
            case "async", _, _:
                # We're not displaying the status because there's a more important status.
                logger.info("not displaying status %s", status.model_dump())
            case "blocking", [], _:
                self.object(scope).status = status.status
            case "blocking", _, False:
                # We're not displaying the status because there's a more important status.
                logger.info("not displaying status %s", status.model_dump())
            case "blocking", _, True:
                # We have critical statuses but this is an action so we
                # override this status and log.
                logger.info("Overriding critical status %s", statuses)
                self.object(scope).status = status.status

    @lru_cache
    def _get_sorted_statuses(self, scope: Scope) -> list[tuple[str, StatusObject]]:
        statuses_by_components = StatusObjectDict.model_validate(
            {component.name: component.get(scope) for component in self.components_statuses}
        )
        current_statuses = [
            (component, item)
            for component, statuses in statuses_by_components.items()
            for item in statuses
        ]

        # Log all statuses.
        logger.info(json.dumps({"scope": scope, "statuses": statuses_by_components.model_dump()}))

        return sorted(
            itertools.chain(current_statuses),
            key=lambda status: (
                -PRIORITIES.get(status[1].status.name, 0),
                self._component_priority(status[0]),
            ),
        )

    def _get_critical_statuses(self, scope: Scope) -> list[tuple[str, StatusObject]]:
        """Gets all critical statuses for all components."""
        all_statuses = self._get_sorted_statuses(scope)
        return [status for status in all_statuses if status[1].approved_critical_component]

    def _on_scope_statuses(self, scope: Scope, event: CollectStatusEvent):
        """The core logic of the status handling for a given scope."""
        all_statuses = self._get_sorted_statuses(scope)
        critical_statuses = self._get_critical_statuses(scope)

        if critical_statuses:
            # When we have critical statuses, we display it right away.
            event.add_status(critical_statuses[0][1].status)
            return

        first_status = all_statuses[0][1].status

        number_of_important_statuses = len(
            [status for status in all_statuses if not isinstance(status[1].status, ActiveStatus)]
        )
        actions_to_run = len(list(filter(lambda x: x[1].action is not None, all_statuses)))
        if number_of_important_statuses > 1:
            # We have many statuses so we display the full line.
            event.add_status(
                StatusBase.from_name(
                    first_status.name,
                    f"{first_status.message}. Run `status-detail`: {actions_to_run} action required; {number_of_important_statuses - 1} additional statuses.",
                )
            )
        else:
            # Only one status which is important, let's log it.
            event.add_status(first_status)

    def _on_collect_unit_status(self, event: CollectStatusEvent) -> None:
        """Handles collect_unit_status event.

        Retrieves the previously set statuses of the components for the unit
        status and then: prioritises, logs, and shows status info.

        Note: prioritisation of statuses is performed according to DA147,
        offering addition customisation over the ops default_status operation.
        """
        # log all statuses + set status + clear any blocking running statuses.
        self._on_scope_statuses(scope="unit", event=event)

    def _on_collect_app_status(self, event: CollectStatusEvent) -> None:
        """Handles collect_app_status event.

        Retrieves the previously set statuses of the components for the app
        status and: priorities, logs, and shows status info.

        Note: prioritisation of statuses is performed according to DA147,
        offering addition customisation over the ops default_status operation.
        """
        self._on_scope_statuses(scope="app", event=event)

    def _recompute_statuses(self):
        """Recompute all statuses for all components."""
        for manager in self.components:
            for scope in get_args(Scope):
                manager.component_statuses.clear(scope)
                statuses = manager.compute_statuses(scope)
                logger.debug(f"Recomputed statuses for {scope=}: {statuses}")
                for status in statuses:
                    manager.component_statuses.add(status=status, scope=scope)

    def _on_status_detail_action(self, event: ActionEvent) -> None:
        """Handles status-detail action.

        This action has an optional boolean argument `recompute`.
        If recompute = True, it will recompute all statuses, cache the results
        in the databag, and output it.
        """
        logger.debug("Getting all statuses")
        if event.params.get("recompute", False):
            self._recompute_statuses()

        current_app_statuses = self._get_sorted_statuses(scope="app")
        current_unit_statuses = self._get_sorted_statuses(scope="unit")
        logger.debug(f"{current_app_statuses=}")
        logger.debug(f"{current_unit_statuses=}")

        event.set_results(
            {
                "app": self.format_statuses("app", current_app_statuses),
                "unit": self.format_statuses("unit", current_unit_statuses),
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
        table.add_column("Message", no_wrap=True)
        table.add_column("Action", no_wrap=True)
        table.add_column("Reason", no_wrap=True)

        for component_name, status in statuses:
            table.add_row(
                *[
                    status.status.name.capitalize(),
                    component_name,
                    status.status.message,
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
                    "Status": status.status.name.capitalize(),
                    "Component Name": component_name,
                    "Message": status.status.message,
                    "Action": status.check or "N/A",
                    "Reason": status.check or "N/A",
                }
            )
        return res
