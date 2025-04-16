# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from ops import ActiveStatus, CharmBase, MaintenanceStatus, StoredState, testing
from ops.framework import Object
from ops.model import BlockedStatus

from data_platform_helpers.advanced_statuses.components import ComponentStatuses
from data_platform_helpers.advanced_statuses.handler import StatusHandler
from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
)
from data_platform_helpers.advanced_statuses.protocol import ManagerStatusProtocol
from data_platform_helpers.advanced_statuses.types import Scope


class OtherComponent(Object, ManagerStatusProtocol):
    def __init__(self, charm: MyCharm):
        super().__init__(parent=charm, key="other-component")
        self._charm = charm
        self.component_statuses = ComponentStatuses(
            self,
            "other-component",
            status_relation_name="status-peers",
        )

    def compute_statuses(self, scope: Scope) -> list[StatusObject]:
        if scope == "app":
            if self._charm._stored.call_number < 3:
                return []
            return [
                StatusObject(
                    status=BlockedStatus("other component failed"),
                    action="Restart the service",
                )
            ]
        return []


class MyCharm(CharmBase, ManagerStatusProtocol):
    # Store state for returning more than one status
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(call_number=0)
        self.component_statuses = ComponentStatuses(
            self,
            name="my-charm",
            status_relation_name="status-peers",
        )
        self.other_component = OtherComponent(self)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.status_handler = StatusHandler(self, self, self.other_component)

    def _on_update_status(self, event):
        self._stored.call_number += 1
        return

    def compute_statuses(self, scope: Scope) -> list[StatusObject]:
        if scope == "app":
            if self._stored.call_number == 1:
                return [StatusObject(status=BlockedStatus("blah"))]
            if self._stored.call_number == 2:
                return [
                    StatusObject(status=BlockedStatus("blah")),
                    StatusObject(status=MaintenanceStatus("running maintenance")),
                ]
            return [
                StatusObject(status=MaintenanceStatus("running maintenance")),
            ]
        return self.component_statuses.get("unit").root or [
            StatusObject(status=ActiveStatus("running"))
        ]


METADATA = {
    "name": "test-charm",
    "description": "A description",
    "summary": "A summary",
    "peers": {"status-peers": {"interface": "status-peers"}},
}

ACTIONS = {
    "status-detail": {
        "description": "Gets statuses of the charm",
        "params": {
            "recompute": {
                "type": "boolean",
                "default": False,
                "description": "a boolean indicating whether a unit should recompute all statuses.",
            }
        },
    }
}


@pytest.fixture
def test_charm_context() -> (
    Generator[tuple[testing.Context[MyCharm], testing.State, testing.PeerRelation], Any, Any]
):
    ctx = testing.Context(MyCharm, meta=METADATA, actions=ACTIONS)
    relation = testing.PeerRelation(id=1, endpoint="status-peers", interface="status-peers")
    stored_state = testing.StoredState(name="_stored", content={"call_number": 0})
    state = testing.State(leader=True, relations=[relation], stored_states=[stored_state])
    yield ctx, state, relation


@pytest.fixture
def context(test_charm_context):
    ctx, _, _ = test_charm_context
    yield ctx


@pytest.fixture
def state(test_charm_context):
    _, _state, _ = test_charm_context
    yield _state


@pytest.fixture
def peer_relation(test_charm_context):
    _, _, relation = test_charm_context
    yield relation


def test_status_handler(context, state):
    out = context.run(context.on.update_status(), state)

    app_status = out.app_status
    unit_status = out.unit_status

    assert app_status == BlockedStatus("blah")
    assert unit_status == ActiveStatus("running")


def test_multiple_statuses(context, state: testing.State):
    out = context.run(context.on.update_status(), state)

    out_bis = context.run(context.on.update_status(), out)

    # Good, we computed the correct status
    assert out_bis.app_status == BlockedStatus(
        "blah. Run `status-detail`: 0 action required; 1 additional statuses."
    )

    context.run(context.on.action("status-detail"), out_bis)
    json_output = context.action_results["json-output"]
    assert len(json_output["app"]) == 2
    assert len(json_output["unit"]) == 1

    assert json_output["app"][0]["Status"] == "Blocked"
    assert json_output["app"][1]["Status"] == "Maintenance"
    assert json_output["unit"][0]["Status"] == "Active"


def test_multiple_components(context: testing.Context, state: testing.State):
    out = context.run(context.on.update_status(), state)
    out_bis = context.run(context.on.update_status(), out)
    out_ter = context.run(context.on.update_status(), out_bis)

    # We have successfully prioritized statuses, logged actions required and counted statuses.
    assert out_ter.app_status == BlockedStatus(
        "other component failed. Run `status-detail`: 1 action required; 1 additional statuses."
    )

    context.run(context.on.action("status-detail"), out_ter)
    json_output = context.action_results["json-output"]
    assert len(json_output["app"]) == 2
    assert len(json_output["unit"]) == 1

    assert json_output["app"][0]["Status"] == "Blocked"
    assert json_output["app"][0]["Component Name"] == "other-component"
    assert json_output["app"][1]["Status"] == "Maintenance"
    assert json_output["app"][1]["Component Name"] == "my-charm"
