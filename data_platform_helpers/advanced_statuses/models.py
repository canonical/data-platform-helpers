# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""This file defines the models for StatusObject with extensive validation.

The StatusObject are enhanced statuses, that embed some extra information.

A StatusObject is composed of an ops Status, and can contain the following extra information:
 * check: a string representing the check that was run and led to this status
 * action: The action the user should take first.
 * running: this field can be either empty, or one of "async" or "blocking". In
 the two last cases, it means that this status is a running status. It is
 "blocking" if it should block other events from running and should be
 discarded at the end of the event, or "async" if it should be persisted among
 events until the long running task finishes. For example, a blocking running
 status could be "Waiting to drain shard" while an async running status could
 be "Running backup <backup-id". Statuses that are not running are regular statuses
 * approved_critical_component: This specifies statuses that are critical and
 require immediate action. They should be approved by managers as they break
 the UX and can extend to more than 120 characters, which is a status size
 limit.
"""

from __future__ import annotations

from collections.abc import ItemsView, Iterator
from typing import (
    Annotated,
    Any,
    Literal,
    TypeAlias,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
)

StatusLiteral: TypeAlias = Literal["blocked", "maintenance", "waiting", "active"]


class StatusObject(BaseModel):
    """This dataclass defines the extended statuses objects.

    This extended status object contains some extra information used to decide
    when to display / log /discard it.

    The developer can specify what check led to this status, what action is
    required from the user, and for running statuses, what kind of running
    status it is: async statuses have their statuses saved so that they can be
    displayed across hooks, while blocking running statuses are cleared at the
    end of the hook they are set in.
    """

    model_config = ConfigDict(frozen=True)  # Don't allow to update the status object.

    status: StatusLiteral = Field(
        title="The Status type",
        description="The  status type that will be set if this object is picked.",
    )
    message: str = Field(
        title="The Status message",
        description="The status message that will be set if this object is picked.",
    )
    short_message: Annotated[str, StringConstraints(max_length=40)] | None = Field(
        title="A short message",
        description="The status message displayed if multiple statuses should be displayed. Max len: 40 chars",
        default=None,
    )

    check: str | None = Field(
        default=None, description="What check was performed to determine the status."
    )
    action: str | None = Field(default=None, description="What action is required from the user.")
    running: Literal["blocking", "async", None] = Field(
        default=None, description="Indicator of running status type, if applicable"
    )

    approved_critical_component: bool = Field(
        default=False,
        description="Critical components statuses breaks the UX by using all 120 characters. They must be approved by Data Platform managers.",
    )

    def __eq__(self, other: Any):  # noqa: D105
        if not isinstance(other, StatusObject):
            return False
        return (
            self.status == other.status
            and self.message == other.message
            and self.check == other.check
            and self.action == other.action
            and self.running == other.running
            and self.approved_critical_component == other.approved_critical_component
        )


class StatusObjectList(RootModel):
    """A Status Object list, used by different components."""

    root: list[StatusObject]

    def __iter__(self) -> Iterator[StatusObject]:  # type: ignore[override] # noqa: D105
        return iter(self.root)

    def __getitem__(self, item: int) -> StatusObject:  # noqa: D105
        return self.root[item]

    def __contains__(self, item: Any) -> bool:  # noqa: D105
        return item in self.root

    def remove(self, item: StatusObject) -> None:  # noqa: D102
        return self.root.remove(item)


class StatusObjectDict(RootModel):
    """A Status Object dictionary mapping a component name to its statuses."""

    root: dict[str, StatusObjectList]

    def __iter__(self) -> Iterator[str]:  # type: ignore[override] # noqa: D105
        return iter(self.root)

    def __getitem__(self, item) -> StatusObjectList:  # noqa: D105
        return self.root[item]

    def items(self) -> ItemsView[str, StatusObjectList]:  # noqa: D102
        return self.root.items()
