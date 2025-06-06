# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Protocols defined for the advanced status handling.

Those protocols are to be used in components/libs/managers to enforce the
implementation of specific methods and attributes.

We specifically define the ManagerStatusProtocol, which enforces the
implementation of a `get_statuses` method that should compute all feasible
statuses for a component, excluding the blocking running statuses. This
protocol also ensures that the component/lib/manager has defined a
`state` object of type `StatusesStateProtocol` to store and retrieve
statuses from the peer relation databag.

Example of use:

class <>Manager(ManagerStatusProtocol):
    def __init__():
        self.name = 'my-name'
        self.state = ...

    def get_statuses(self, scope: str, recompute: bool = True) -> list[StatusObject]:
        # Implementing compute logic - this should compute every possible
        # status for this component/lib excluding blocking running statuses
        # ....
        if self.is_active():
            return [StatusObject(...)]

    def some_business_logic_function():
        # we know this status is relevant for this component/manager/lib
        # regardless of the event
        if X:
            self.state.statuses.add(<Manager>Statuses.<X>, scope=Scope.UNIT, component=self.name)

        do Y;

        if Z:
            self.status_component.add(<Manager>Statuses.<Z>, scope=Scope.APP, component=self.name)
"""

from typing import Protocol, runtime_checkable

from data_platform_helpers.advanced_statuses.components import StatusesState
from data_platform_helpers.advanced_statuses.models import StatusObject
from data_platform_helpers.advanced_statuses.types import Scope


@runtime_checkable
class StatusesStateProtocol(Protocol):
    """This is a very simple protocol to force a state to define a status state."""

    statuses: StatusesState


@runtime_checkable
class ManagerStatusProtocol(Protocol):
    """This is a very simple protocol used to classes to implement some methods and attributes."""

    # Force subclasses to initialise status component
    state: StatusesStateProtocol
    name: str

    def get_statuses(self, scope: Scope, recompute: bool = False) -> list[StatusObject]:
        """Forces subclasses to implement get_statuses.

        This function gets all feasible statuses for a component (or lib if
        not single kernel) - excluding blocking running statuses.
        It should recompute the statuses if recompute is true.
        """
        ...
