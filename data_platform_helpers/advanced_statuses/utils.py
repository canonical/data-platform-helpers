# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""Utility functions for the advanced statuses."""

from ops.model import StatusBase

from data_platform_helpers.advanced_statuses.models import StatusObject


def as_status(status: StatusObject):
    """Transform an extended status object into an Ops Status Object."""
    return StatusBase.from_name(status.status, status.message)
