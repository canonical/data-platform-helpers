# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""This file defines the StateStatuses class.

This class is used by the state object so that all components can report statuses.

Example:
class State(iStatusesStateProtocol):
    def __init__(self, charm):
        self.statuses = StateStatuses(
            charm,
            'status-peers',
        )


"""

from bisect import insort_right
from logging import getLogger
from typing import Literal

from ops import Object, Relation
from ops.model import RelationDataContent

from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectList,
)
from data_platform_helpers.advanced_statuses.types import Scope

logger = getLogger(__name__)

PRIORITIES: dict[str, int] = {
    "error": 50,
    "blocked": 40,
    "maintenance": 30,
    "waiting": 20,
    "active": 10,
}


class StatusesState(Object):
    """StatusesState CRUD operations with databag."""

    def __init__(
        self,
        parent: Object,
        status_relation_name: str,
    ) -> None:
        """Initialiser of the Component Statuses.

        The status relation name is the name of the peer relation used to
        store the statuses information. The status objects are stored in the
        unit/app databag of the peer relation and then used during the
        collect-status events.

        The parent is used to provide an access to Ops.
        """
        super().__init__(parent=parent, key="statuses-state")
        self.status_relation_name = status_relation_name

    @property
    def relation(self) -> Relation | None:
        """Access the relation object."""
        return self.model.get_relation(self.status_relation_name)

    def _databag(self, scope: Scope) -> RelationDataContent | None:
        """Accesses the databag in the right scope."""
        if not self.relation:
            return None
        match scope:
            case "app":
                return self.relation.data[self.model.app]
            case "unit":
                return self.relation.data[self.model.unit]

    def add(self, status: StatusObject, scope: Scope, component: str) -> None:
        """Adds a status to the component."""
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot add app status on a non-leader unit.")
            return
        if (databag := self._databag(scope)) is None:
            logger.warning(
                "No databag present for statuses, the status could not be persisted for use in next events."
            )
            return
        current_data = StatusObjectList.model_validate_json(databag.get(component, "[]"))

        if status in current_data.root:
            logger.debug("Not inserting %s already present in databag.", status.model_dump())
            return

        # Insert already sorted, we want to have it by decreasing priority so
        # we have to sort by negative priority as bisect library does not allow
        # to sort by decreasing order.
        insort_right(
            current_data.root,
            status,
            key=lambda status: -PRIORITIES.get(status.status, 0),
        )
        logger.debug(f"{current_data=}")
        databag.update({component: current_data.model_dump_json()})

    def set(self, status: StatusObject, scope: Scope, component: str) -> None:
        """Sets component to a specific status.

        This overrides all statuses in the databag.
        """
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot set app status on a non-leader unit.")
            return
        if (databag := self._databag(scope)) is None:
            logger.warning(
                "No databag present for statuses, the status could not be persisted for use in next events."
            )
            return
        databag.update({component: StatusObjectList(root=[status]).model_dump_json()})

    def delete(self, status: StatusObject, scope: Scope, component: str) -> None:
        """Deletes a status from the component.

        If the status is not present, log this information.
        """
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot delete app status on a non-leader unit.")
            return
        if (databag := self._databag(scope)) is None:
            logger.warning(
                "No databag present for statuses, the status could not be persisted for use in next events."
            )
            return
        try:
            current_data = StatusObjectList.model_validate_json(databag.get(component, "[]"))
            current_data.remove(status)
            databag.update({component: current_data.model_dump_json()})
        except ValueError:
            logger.warning(
                f"Tried to delete status {status} in scope {scope} but it was not present"
            )
            return

    def clear(self, scope: Scope, component: str) -> None:
        """Clears all statuses from the component."""
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot clear app status on a non-leader unit.")
            return
        if (databag := self._databag(scope)) is None:
            logger.warning(
                "No databag present for statuses, the status could not be persisted for use in next events."
            )
            return
        databag.update({component: "[]"})

    def get(
        self,
        scope: Scope,
        component: str,
        running_status_only: bool = False,
        running_status_type: Literal["all", "blocking", "async"] = "all",
    ) -> StatusObjectList:
        """Gets all statuses for a component.

        Args:
         * scope: The scope we want to get
         * component: The component we want to get
         * running_status_only: Do we want only running statuses?
         * running_status_type: If we want running statuses, which kind?
        """
        if (databag := self._databag(scope)) is None:
            logger.warning("No databag present for statuses, information lost for next events.")
            return StatusObjectList(root=[])
        current_data = StatusObjectList.model_validate_json(databag.get(component, "[]"))

        if not running_status_only:
            return current_data

        if running_status_type == "all":
            return StatusObjectList(root=[status for status in current_data if status.running])

        return StatusObjectList(
            root=[status for status in current_data if status.running == running_status_type]
        )
