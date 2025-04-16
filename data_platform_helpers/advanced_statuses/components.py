# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""This file defines the ComponentStatuses class.

This class is used by all components that should report statuses.

Example:
class <>Manager(ManagerStatusProtocol):
    def __init__(self, charm):
        self.status_component = ComponentStatuses(
            charm,
            'my-component',
            'status-peers',
        )

    def compute_statuses(self, scope: Scope):
        ...

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
    "error": 5,
    "blocked": 4,
    "maintenance": 3,
    "waiting": 2,
    "active": 1,
}


class ComponentStatuses(Object):
    """ComponentStatuses CRUD operations with databag."""

    def __init__(
        self,
        parent: Object,
        name: str,
        status_relation_name: str,
    ) -> None:
        """Initialiser of the Component Statuses.

        The status relation name is the name of the peer relation used to
        store the statuses information. The status objects are stored in the
        unit/app databag of the peer relation and then used during the
        collect-status events.

        The component name is the name of the component that this object is
        related to. This is used in serialisation in the databag, to classify
        the statuses by component.

        The parent is used to provide an access to Ops.
        """
        super().__init__(parent=parent, key=f"status-{name}")
        self.name = name
        self.status_relation_name = status_relation_name

    @property
    def relation(self) -> Relation | None:
        """Access the relation object."""
        return self.model.get_relation(self.status_relation_name)

    def databag(self, scope: Scope) -> RelationDataContent | None:
        """Accesses the databag in the right scope."""
        if not self.relation:
            return None
        match scope:
            case "app":
                return self.relation.data[self.model.app]
            case "unit":
                return self.relation.data[self.model.unit]

    def add(self, status: StatusObject, scope: Scope) -> None:
        """Adds a status to the component."""
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot add app status with non-leader unit.")
            return
        if (databag := self.databag(scope)) is None:
            logger.warning("No databag present for statuses, information lost for next events.")
            return
        current_data = StatusObjectList.model_validate_json(databag.get(self.name, "[]"))
        # Insert already sorted
        insort_right(
            current_data.root,
            status,
            key=lambda status: -PRIORITIES.get(status.status.name, 0),
        )
        logger.warning(f"{current_data=}")
        databag.update({self.name: current_data.model_dump_json()})

    def set(self, status: StatusObject, scope: Scope) -> None:
        """Sets component to a specific status.

        This overrides all statuses in the databag.
        """
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot set app status with non-leader unit.")
            return
        if (databag := self.databag(scope)) is None:
            logger.warning("No databag present for statuses, information lost for next events.")
            return
        databag.update({self.name: StatusObjectList([status]).model_dump_json()})

    def delete(self, status: StatusObject, scope: Scope) -> None:
        """Deletes a status from the component.

        If the status is not present, log this information.
        """
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot delete app status with non-leader unit.")
            return
        if (databag := self.databag(scope)) is None:
            logger.warning("No databag present for statuses, information lost for next events.")
            return
        try:
            current_data = StatusObjectList.model_validate_json(databag.get(self.name, "[]"))
            current_data.remove(status)
            databag.update({self.name: current_data.model_dump_json()})
        except ValueError:
            logger.warning(
                f"Tried to delete status {status} in scope {scope} but it was not present"
            )
            return

    def clear(self, scope: Scope) -> None:
        """Clears all statuses from the component."""
        if scope == "app" and not self.model.unit.is_leader():
            logger.warning("Cannot clear app status with non-leader unit.")
            return
        if (databag := self.databag(scope)) is None:
            logger.warning("No databag present for statuses, information lost for next events.")
            return
        databag.update({self.name: "[]"})

    def get(
        self,
        scope: Scope,
        running_status_only: bool = False,
        running_status_type: Literal["all", "blocking", "async"] = "all",
    ) -> StatusObjectList:
        """Gets all statuses for a component.

        Args:
         * scope: The scope we want to get
         * running_status_only: Do we want only running statuses?
         * running_status_type: If we want running statuses, which kind?
        """
        if (databag := self.databag(scope)) is None:
            logger.warning("No databag present for statuses, information lost for next events.")
            return StatusObjectList(root=[])
        current_data = StatusObjectList.model_validate_json(databag.get(self.name, "[]"))
        if not running_status_only:
            return current_data
        match running_status_type:
            case "all":
                return StatusObjectList(root=[status for status in current_data if status.running])
            case _:
                return StatusObjectList(
                    root=[
                        status for status in current_data if status.running == running_status_type
                    ]
                )
