# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.model import BlockedStatus, MaintenanceStatus
from pydantic import ValidationError

from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectDict,
    StatusObjectList,
)
from data_platform_helpers.advanced_statuses.utils import compute_status_message


def test_create_status_object():
    status = StatusObject.model_validate(
        {
            "status": "blocked",
            "message": "Invalid config",
            "check": "Config was not set properly",
            "action": "Rollback configuration change.",
        }
    )

    assert not status.approved_critical_component
    assert status.model_dump() == {
        "status": "blocked",
        "message": "Invalid config",
        "check": "Config was not set properly",
        "action": "Rollback configuration change.",
        "running": None,
        "approved_critical_component": False,
        "short_message": None,
    }


def test_create_invalid_status_object():
    with pytest.raises(ValidationError):
        StatusObject.model_validate(
            {
                "status": "invalid",
                "message": "deadbeef",
                "check": "Config was not set properly",
                "action": "Rollback configuration change.",
            }
        )


def test_create_status_object_list():
    status_list = StatusObjectList.model_validate(
        [{"status": "blocked", "message": "blah"}, {"status": "maintenance", "message": "bluh"}]
    )

    status_list.remove(StatusObject(status="blocked", message="blah"))

    assert len(status_list.root) == 1


def test_create_status_object_dict():
    status_list = StatusObjectDict.model_validate(
        {
            "component-1": [{"status": "blocked", "message": "blah"}],
            "component-2": [{"status": "maintenance", "message": "bluh"}],
        }
    )

    assert status_list["component-1"][0].status == "blocked"
    assert status_list["component-1"][0].message == "blah"
    assert status_list["component-2"][0].status == "maintenance"
    assert status_list["component-2"][0].message == "bluh"


def test_lookup():
    a = StatusObject(status="blocked", message="blah")
    status_list = StatusObjectList([a, StatusObject(status="maintenance", message="bluh")])

    assert a in status_list


def test_create_with_short_message():
    status = StatusObject.model_validate(
        {"status": "blocked", "message": "blah", "short_message": "short"}
    )

    real_status_message = compute_status_message(status, 1, 1)

    assert "short" in real_status_message
