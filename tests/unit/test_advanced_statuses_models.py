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


def test_create_status_object():
    status = StatusObject.model_validate(
        {
            "status": BlockedStatus("Invalid config"),
            "check": "Config was not set properly",
            "action": "Rollback configuration change.",
        }
    )

    assert not status.approved_critical_component
    assert status.model_dump() == {
        "status": {"name": "blocked", "message": "Invalid config"},
        "check": "Config was not set properly",
        "action": "Rollback configuration change.",
        "running": None,
        "approved_critical_component": False,
    }


def test_create_invalid_status_object():
    with pytest.raises(ValidationError):
        StatusObject.model_validate(
            {
                "status": {"status": "invalid", "message": "deadbeef"},
                "check": "Config was not set properly",
                "action": "Rollback configuration change.",
            }
        )


def test_create_status_object_list():
    status_list = StatusObjectList.model_validate(
        [{"status": BlockedStatus("blah")}, {"status": MaintenanceStatus("bluh")}]
    )

    status_list.remove(StatusObject(status=BlockedStatus("blah")))

    assert len(status_list.root) == 1


def test_create_status_object_dict():
    status_list = StatusObjectDict.model_validate(
        {
            "component-1": [{"status": BlockedStatus("blah")}],
            "component-2": [{"status": MaintenanceStatus("bluh")}],
        }
    )

    assert status_list["component-1"][0].status == BlockedStatus("blah")
    assert status_list["component-2"][0].status == MaintenanceStatus("bluh")


def test_lookup():
    a = StatusObject(status=BlockedStatus("blah"))
    status_list = StatusObjectList([a, StatusObject(status=MaintenanceStatus("bluh"))])

    assert a in status_list
