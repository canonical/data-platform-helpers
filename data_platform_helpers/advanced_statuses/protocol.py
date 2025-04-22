# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Protocols defined for the advanced status handling.

Those protocols are to be used in components/libs/managers to enforce the
implementation of specific methods and attributes.

We specifically define the ManagerStatusProtocol, which enforces the
implementation of a `compute_statuses` method that should compute all feasible
statuses for a component, excluding the blocking running statuses. This
protocol also ensures that the component/lib/manager has defined a
`component_statuses` object of type `ComponentStatuses` to store and retrieve
statuses from the peer relation databag.

Example of use:

class <>Manager(ManagerStatusProtocol):
    def __init__():
        self.status_component = ComponentStatuses(statuses_relation_name)

    def compute_statuses(self, scope: str) -> StatusObjectList:
        # Implementing compute logic - this should compute every possible
        # status for this component/lib excluding blocking running statuses
        # ....
        if self.is_active():
            return StatusObjectList([StatusObject(...)])

    def some_business_logic_function():
        # we know this status is relevant for this component/manager/lib
        # regardless of the event
        if X:
            self.status_component.add(<Manager>Statuses.<X>)

        do Y;

        if Z:
            self.status_component.add(<Manager>Statuses.<Z>)
"""

from typing import Protocol, runtime_checkable

from data_platform_helpers.advanced_statuses.components import ComponentStatuses
from data_platform_helpers.advanced_statuses.models import (
    StatusObjectList,
)
from data_platform_helpers.advanced_statuses.types import Scope


@runtime_checkable
class ManagerStatusProtocol(Protocol):
    """This is a very simple protocol used to classes to implement some methods and attributes."""

    # Force subclasses to initialise status component
    component_statuses: ComponentStatuses

    def compute_statuses(self, scope: Scope) -> StatusObjectList:
        """Forces subclasses to implement compute_statuses.

        This function computes all feasible statuses for a component (or lib if
        not single kernel) - excluding blocking running statuses.
        """
        ...
