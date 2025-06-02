# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from collections.abc import Generator
from typing import Any

import pytest
from ops import CharmBase, MaintenanceStatus, WaitingStatus, testing
from ops.model import BlockedStatus

from data_platform_helpers.advanced_statuses.components import StatusesState
from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectList,
)
from data_platform_helpers.advanced_statuses.protocol import (
    ManagerStatusProtocol,
    StatusesStateProtocol,
)
from data_platform_helpers.advanced_statuses.types import Scope


class State(StatusesStateProtocol):
    def __init__(self, charm: CharmBase):
        self.statuses = StatusesState(charm, "status-peers")


class MyCharm(CharmBase, ManagerStatusProtocol):
    def __init__(self, *args):
        super().__init__(*args)
        self.name = "my-charm"
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.state = State(self)

    def _on_update_status(self, event):
        return

    def get_statuses(self, scope: Scope, recompute: bool = False) -> list[StatusObject]:
        if scope == "app":
            return [StatusObject(status="blocked", message="blah")]
        return self.state.statuses.get("unit", self.name).root or [
            StatusObject(status="active", message="running")
        ]


METADATA = {
    "name": "test-charm",
    "description": "A description",
    "summary": "A summary",
    "peers": {"status-peers": {"interface": "status-peers"}},
}


@pytest.fixture(scope="module")
def test_charm_context() -> (
    Generator[tuple[testing.Context[MyCharm], testing.State, testing.PeerRelation], Any, Any]
):
    ctx = testing.Context(MyCharm, meta=METADATA)
    relation = testing.PeerRelation(id=1, endpoint="status-peers", interface="status-peers")
    state = testing.State(leader=True, relations=[relation])
    yield ctx, state, relation


@pytest.fixture
def context(
    test_charm_context: testing.Context[MyCharm],
) -> Generator[testing.Context[MyCharm], Any, Any]:
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


def test_component_statuses_add_unit(
    context: testing.Context[MyCharm], state: testing.State, peer_relation: testing.PeerRelation
):
    with context(context.on.update_status(), state) as manager:
        manager.charm.state.statuses.add(
            StatusObject(status="waiting", message="Waiting for new event"),
            scope="unit",
            component="my-charm",
        )
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])
    assert len(unit_status_list.root) == 1


def test_component_statuses_add_app(
    context: testing.Context[MyCharm], state: testing.State, peer_relation: testing.PeerRelation
):
    with context(context.on.update_status(), state) as manager:
        manager.charm.state.statuses.add(
            StatusObject(status="waiting", message="Waiting for new event"),
            scope="app",
            component="my-charm",
        )
        out = manager.run()

    local_app_data = out.get_relation(peer_relation.id).local_app_data

    app_status_list = StatusObjectList.model_validate_json(local_app_data["my-charm"])
    assert len(app_status_list.root) == 1


def test_component_statuses_set_unit(
    context: testing.Context[MyCharm], state: testing.State, peer_relation: testing.PeerRelation
):
    with context(context.on.update_status(), state) as manager:
        manager.charm.state.statuses.add(
            StatusObject(status="waiting", message="Waiting for new event"),
            scope="unit",
            component="my-charm",
        )
        manager.charm.state.statuses.add(
            StatusObject(status="blocked", message="blocked"),
            scope="unit",
            component="my-charm",
        )
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])

    # Check that we have two statuses
    assert len(unit_status_list.root) == 2

    # Check that it was inserted in order
    assert unit_status_list[0] == StatusObject(status="blocked", message="blocked")


def test_component_statuses_clear_unit(
    context: testing.Context[MyCharm], state: testing.State, peer_relation: testing.PeerRelation
):
    with context(context.on.update_status(), state) as manager:
        manager.charm.state.statuses.add(
            StatusObject(status="waiting", message="Waiting for new event"),
            scope="unit",
            component="my-charm",
        )
        manager.charm.state.statuses.add(
            StatusObject(status="blocked", message="blocked"),
            scope="unit",
            component="my-charm",
        )
        out = manager.run()

    with context(context.on.update_status(), out) as manager:
        manager.charm.state.statuses.clear(scope="unit", component="my-charm")
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])
    assert len(unit_status_list.root) == 0


def test_component_statuses_get_unit(context: testing.Context[MyCharm], state: testing.State):
    with context(context.on.update_status(), state) as manager:
        manager.charm.state.statuses.add(
            StatusObject(status="waiting", message="Waiting for new event", running="async"),
            scope="unit",
            component="my-charm",
        )
        manager.charm.state.statuses.add(
            StatusObject(status="blocked", message="blocked"), scope="unit", component="my-charm"
        )
        manager.charm.state.statuses.add(
            StatusObject(status="maintenance", message="installing", running="blocking"),
            scope="unit",
            component="my-charm",
        )
        out = manager.run()

    with context(context.on.update_status(), out) as manager:
        running_statuses = manager.charm.state.statuses.get(
            scope="unit",
            running_status_only=True,
            component="my-charm",
        )
        assert len(running_statuses.root) == 2
        blocking_statuses = manager.charm.state.statuses.get(
            scope="unit",
            running_status_only=True,
            running_status_type="blocking",
            component="my-charm",
        )
        assert len(blocking_statuses.root) == 1

        async_statuses = manager.charm.state.statuses.get(
            scope="unit",
            running_status_only=True,
            running_status_type="async",
            component="my-charm",
        )
        assert len(async_statuses.root) == 1

        all_statuses = manager.charm.state.statuses.get(scope="unit", component="my-charm")
        assert len(all_statuses.root) == 3


def test_component_statuses_delete_unit(
    context: testing.Context[MyCharm], state: testing.State, peer_relation: testing.PeerRelation
):
    with context(context.on.update_status(), state) as manager:
        manager.charm.state.statuses.add(
            StatusObject(status="waiting", message="Waiting for new event", running="async"),
            scope="unit",
            component="my-charm",
        )
        manager.charm.state.statuses.add(
            StatusObject(status="blocked", message="blocked"), scope="unit", component="my-charm"
        )
        out = manager.run()

    with context(context.on.update_status(), out) as manager:
        manager.charm.state.statuses.delete(
            StatusObject(status="blocked", message="blocked"), scope="unit", component="my-charm"
        )
        out_bis = manager.run()

    local_unit_data = out_bis.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])
    assert len(unit_status_list.root) == 1
    assert unit_status_list[0] == StatusObject(
        status="waiting", message="Waiting for new event", running="async"
    )
