# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
# ruff: noqa
"""The advanced status handling module.

This is the implementation of rich statuses as defined by the following specs:
 * [DA-147: UX of Statuses](https://docs.google.com/document/d/1SV11ct-flQkc5BOYOeXgmPeglL8bVs-mDVkGjG20K48/)
 * [DA-161: Implementation of Advanced Statuses](https://docs.google.com/document/d/1Yg7w7N-S1STbluk3SttZCQx1waZW_e_yOuKWeyahy20/)

With this module, charms can support multiple statuses at the same time, in a
common and refined approach. It uses a peer-relation to store all the statuses
set by the components of the charm, and then takes advantage of ops
CollecStatusEvent for App and Unit to retrieve all those statuses, prioritize
them and display the correct status.

There are two steps of prioritization:
 * One from ops that we use: Error > Blocked > Maintenance > Waiting > Active  > Unknown
 * One which is defined by the developer that prioritizes the components.

In this library, we use a lexicographic sorting on the tuple (Status priority, component priority).

Given C1 > C2 > C3 > … > Cn, n components, in our case n = 5
Given the following list of statuses for the 5 components,
C1 - None
C2 - Maintenance(C2-status), Waiting(C2-status)
C3 - Blocked(C3-status)
C4 - Blocked(C4-status)
C5 - Maintenance(C5-status)

The prioritization would lead to this status priority list :
Blocked(C3-status),  Blocked(C4-status), Maintenance(C2-status), Maintenance(C5-status), Waiting(C2-status)

Which would be displayed as: BlockedStatus("<C3-status>. Run `status-detail`: <X> action required; 4 additional statuses")

A rich status can define an action to run to resolve the issue, the check that led to this status, but also some more fields.

Statuses are classified into:
 * Regular statuses: Regular statuses set on every event.
 * Blocking running statuses: A type of status that prevents other events from executing.
 * Async running statuses: A type of status that runs across hooks.
 * Approved Critical Statuses: A type of status that BREAKS the UX. They
 require immediate action. This status is shown over all other statuses.

The approved critical statuses MUST be approved by a manager as they break UX.
"""

from .handler import StatusHandler
from .protocol import ManagerStatusProtocol
from .components import StatusesState
from .models import StatusObject, StatusObjectDict, StatusObjectList

__all__ = (
    "StatusHandler",
    "ManagerStatusProtocol",
    "StatusesState",
    "StatusObject",
    "StatusObjectDict",
    "StatusObjectList",
)
