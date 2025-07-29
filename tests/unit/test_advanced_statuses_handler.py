# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from ops import ActiveStatus, CharmBase, StoredState, testing
from ops.framework import Object
from ops.model import BlockedStatus

from data_platform_helpers.advanced_statuses.components import StatusesState
from data_platform_helpers.advanced_statuses.handler import StatusHandler
from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectDict,
)
from data_platform_helpers.advanced_statuses.protocol import (
    ManagerStatusProtocol,
    StatusesStateProtocol,
)
from data_platform_helpers.advanced_statuses.types import Scope


class State(StatusesStateProtocol):
    def __init__(self, charm: CharmBase):
        self.statuses = StatusesState(charm, "status-peers")


class OtherComponent(Object, ManagerStatusProtocol):
    def __init__(self, charm: MyCharm, state: State):
        super().__init__(parent=charm, key="other-component")
        self._charm = charm
        self.state = state
        self.name = "other-component"

    def get_statuses(self, scope: Scope, recompute: bool = False) -> list[StatusObject]:
        if scope == "app":
            if self._charm._stored.call_number < 3:
                return []
            return [
                StatusObject(
                    status="blocked",
                    message="other component failed",
                    action="Restart the service",
                )
            ]
        return []


class MyCharm(CharmBase, ManagerStatusProtocol):
    # Store state for returning more than one status
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.name = "my-charm"
        self.state = State(self)
        self._stored.set_default(call_number=0)
        self.other_component = OtherComponent(self, self.state)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.status_handler = StatusHandler(self, self, self.other_component)

    def _on_update_status(self, event):
        self._stored.call_number += 1
        return

    def get_statuses(self, scope: Scope, recompute: bool = False) -> list[StatusObject]:
        if scope == "app":
            if self._stored.call_number == 1:
                return [StatusObject(status="blocked", message="blah")]
            if self._stored.call_number == 2:
                return [
                    StatusObject(status="blocked", message="blah"),
                    StatusObject(status="maintenance", message="running maintenance"),
                ]
            return [
                StatusObject(status="maintenance", message="running maintenance"),
            ]
        return self.state.statuses.get("unit", self.name).root or [
            StatusObject(status="active", message="running")
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
def context(test_charm_context) -> Generator[testing.Context[MyCharm], Any, Any]:
    ctx, _, _ = test_charm_context
    yield ctx


@pytest.fixture
def state(test_charm_context) -> Generator[testing.State, Any, Any]:
    _, _state, _ = test_charm_context
    yield _state


@pytest.fixture
def peer_relation(test_charm_context) -> Generator[testing.PeerRelation, Any, Any]:
    _, _, relation = test_charm_context
    yield relation


def test_status_handler(context: testing.Context[MyCharm], state: testing.State):
    out = context.run(context.on.update_status(), state)

    app_status = out.app_status
    unit_status = out.unit_status

    assert app_status == BlockedStatus("blah")
    assert unit_status == ActiveStatus("running")


def test_multiple_statuses(context: testing.Context[MyCharm], state: testing.State):
    out = context.run(context.on.update_status(), state)

    out_bis = context.run(context.on.update_status(), out)

    # Good, we computed the correct status
    assert out_bis.app_status == BlockedStatus(
        "blah. Run `status-detail`: 0 action required; 1 additional statuses."
    )

    context.run(context.on.action("status-detail"), out_bis)
    json_output = context.action_results["json-output"]
    app_statuses = StatusObjectDict.model_validate_json(json_output['app'])
    unit_statuses = StatusObjectDict.model_validate_json(json_output['unit'])
    assert len(app_statuses.root["my-charm"].root) == 2
    assert len(unit_statuses.root["my-charm"].root) == 1

    assert app_statuses.root["my-charm"].root[0].status == "blocked"
    assert app_statuses.root["my-charm"].root[0].message == "blah"
    assert app_statuses.root["my-charm"].root[1].status == "maintenance"
    assert app_statuses.root["my-charm"].root[1].message == "running maintenance"
    assert unit_statuses.root["my-charm"].root[0].status == "active"
    assert unit_statuses.root["my-charm"].root[0].message == "running"


def test_multiple_components(context: testing.Context[MyCharm], state: testing.State):
    out = context.run(context.on.update_status(), state)
    out_bis = context.run(context.on.update_status(), out)
    out_ter = context.run(context.on.update_status(), out_bis)

    # We have successfully prioritized statuses, logged actions required and counted statuses.
    assert out_ter.app_status == BlockedStatus(
        "other component failed. Run `status-detail`: 1 action required; 1 additional statuses."
    )

    context.run(context.on.action("status-detail"), out_ter)
    json_output = context.action_results["json-output"]
    app_statuses_by_components = StatusObjectDict.model_validate_json(json_output['app'])
    unit_statuses_by_components = StatusObjectDict.model_validate_json(json_output['unit'])
    
    assert len(app_statuses_by_components.root['my-charm'].root) == 1
    assert len(app_statuses_by_components.root['other-component'].root) == 1
    assert len(unit_statuses_by_components.root['my-charm'].root) == 1
    assert len(unit_statuses_by_components.root['other-component'].root) == 0

    assert app_statuses_by_components.root['my-charm'].root[0].status == "maintenance"
    assert app_statuses_by_components.root['my-charm'].root[0].message == "running maintenance"
    assert app_statuses_by_components.root['other-component'].root[0].status == "blocked"
    assert app_statuses_by_components.root['other-component'].root[0].message == "other component failed"
    assert unit_statuses_by_components.root['my-charm'].root[0].status == "active"
    assert unit_statuses_by_components.root['my-charm'].root[0].message == "running"
    assert unit_statuses_by_components.root['other-component'].root == []
