# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""Utility functions for the advanced statuses."""

from ops.model import StatusBase

from data_platform_helpers.advanced_statuses.models import StatusObject

TEMPLATE = "{message}. Run `status-detail`: {actions_to_run} action required; {important_statuses} additional statuses."


def as_status(status: StatusObject) -> StatusBase:
    """Transform an extended status object into an Ops Status Object."""
    return StatusBase.from_name(status.status, status.message)


def compute_status_message(
    status: StatusObject, actions_to_run: int, important_statuses: int
) -> str:
    """Computes a complex status message based on the status to display and extra information."""
    if status.short_message:
        message = status.short_message
    elif len(status.message) <= 40:
        message = status.message
    else:
        message = f"{status.message:.40}.."
    return TEMPLATE.format(
        message=message, actions_to_run=actions_to_run, important_statuses=important_statuses
    )
