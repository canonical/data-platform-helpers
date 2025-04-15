# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

from collections.abc import Generator
from typing import Any

import pytest
from ops import ActiveStatus, CharmBase, MaintenanceStatus, WaitingStatus, testing
from ops.model import BlockedStatus

from data_platform_helpers.advanced_statuses.components import ComponentStatuses
from data_platform_helpers.advanced_statuses.models import (
    StatusObject,
    StatusObjectList,
)
from data_platform_helpers.advanced_statuses.protocol import ManagerStatusProtocol
from data_platform_helpers.advanced_statuses.types import Scope


class MyCharm(CharmBase, ManagerStatusProtocol):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.component_statuses = ComponentStatuses(
            self,
            name="my-charm",
            status_relation_name="status-peers",
            compute_statuses_callback=lambda scope: self.compute_statuses(scope),
        )

    def _on_update_status(self, event):
        return

    def compute_statuses(self, scope: Scope) -> list[StatusObject]:
        if scope == "app":
            return [StatusObject(status=BlockedStatus("blah"))]
        return self.component_statuses.get("unit").root or [
            StatusObject(status=ActiveStatus("running"))
        ]


METADATA = {
    "name": "test-charm",
    "description": "A description",
    "summary": "A summary",
    "peers": {"status-peers": {"interface": "status-peers"}},
}


@pytest.fixture(scope="module")
def test_charm_context() -> (
    Generator[
        tuple[testing.Context[MyCharm], testing.State, testing.PeerRelation], Any, Any
    ]
):
    ctx = testing.Context(MyCharm, meta=METADATA)
    relation = testing.PeerRelation(
        id=1, endpoint="status-peers", interface="status-peers"
    )
    state = testing.State(leader=True, relations=[relation])
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


def test_component_statuses_add_unit(context, state, peer_relation):
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(
            StatusObject(status=WaitingStatus("Waiting for new event")), scope="unit"
        )
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])
    assert len(unit_status_list.root) == 1


def test_component_statuses_add_app(context, state, peer_relation):
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(
            StatusObject(status=WaitingStatus("Waiting for new event")), scope="app"
        )
        out = manager.run()

    local_app_data = out.get_relation(peer_relation.id).local_app_data

    app_status_list = StatusObjectList.model_validate_json(local_app_data["my-charm"])
    assert len(app_status_list.root) == 1


def test_component_statuses_set_unit(context, state, peer_relation):
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(
            StatusObject(status=WaitingStatus("Waiting for new event")), scope="unit"
        )
        manager.charm.component_statuses.add(
            StatusObject(status=BlockedStatus("blocked")), scope="unit"
        )
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])

    # Check that we have two statuses
    assert len(unit_status_list.root) == 2

    # Check that it was inserted in order
    assert unit_status_list[0] == StatusObject(status=BlockedStatus("blocked"))


def test_component_statuses_clear_unit(context, state, peer_relation):
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(
            StatusObject(status=WaitingStatus("Waiting for new event")), scope="unit"
        )
        manager.charm.component_statuses.add(
            StatusObject(status=BlockedStatus("blocked")), scope="unit"
        )
        out = manager.run()

    with context(context.on.update_status(), out) as manager:
        manager.charm.component_statuses.clear(scope="unit")
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])
    assert len(unit_status_list.root) == 0


def test_component_statuses_get_unit(context, state):
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(
            StatusObject(
                status=WaitingStatus("Waiting for new event"), running="async"
            ),
            scope="unit",
        )
        manager.charm.component_statuses.add(
            StatusObject(status=BlockedStatus("blocked")), scope="unit"
        )
        manager.charm.component_statuses.add(
            StatusObject(status=MaintenanceStatus("installing"), running="blocking"),
            scope="unit",
        )
        out = manager.run()

    with context(context.on.update_status(), out) as manager:
        running_statuses = manager.charm.component_statuses.get(
            scope="unit", running_status_only=True
        )
        assert len(running_statuses.root) == 2
        blocking_statuses = manager.charm.component_statuses.get(
            scope="unit", running_status_only=True, running_status_type="blocking"
        )
        assert len(blocking_statuses.root) == 1

        async_statuses = manager.charm.component_statuses.get(
            scope="unit", running_status_only=True, running_status_type="async"
        )
        assert len(async_statuses.root) == 1

        all_statuses = manager.charm.component_statuses.get(scope="unit")
        assert len(all_statuses.root) == 3


def test_component_statuses_delete_unit(context, state, peer_relation):
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(
            StatusObject(
                status=WaitingStatus("Waiting for new event"), running="async"
            ),
            scope="unit",
        )
        manager.charm.component_statuses.add(
            StatusObject(status=BlockedStatus("blocked")), scope="unit"
        )
        out = manager.run()

    with context(context.on.update_status(), out) as manager:
        manager.charm.component_statuses.delete(
            status=StatusObject(status=BlockedStatus("blocked")), scope="unit"
        )
        out_bis = manager.run()

    local_unit_data = out_bis.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])
    assert len(unit_status_list.root) == 1
    assert unit_status_list[0] == StatusObject(
        status=WaitingStatus("Waiting for new event"), running="async"
    )


def test_component_statuses_recompute_statuses(context, state, peer_relation):
    blocked_status_object = StatusObject(status=BlockedStatus("blocked"))
    with context(context.on.update_status(), state) as manager:
        manager.charm.component_statuses.add(blocked_status_object, scope="unit")
        manager.charm.component_statuses.recompute_statuses()
        out = manager.run()

    local_unit_data = out.get_relation(peer_relation.id).local_unit_data

    unit_status_list = StatusObjectList.model_validate_json(local_unit_data["my-charm"])

    assert len(unit_status_list.root) == 1

    # Check the former status has been erased
    assert unit_status_list[0] != blocked_status_object

    # Check the computed status is in place
    assert unit_status_list[0] == StatusObject(status=ActiveStatus("running"))

    local_app_data = out.get_relation(peer_relation.id).local_app_data

    app_status_list = StatusObjectList.model_validate_json(local_app_data["my-charm"])

    assert len(app_status_list.root) == 1
    assert app_status_list[0] == StatusObject(status=BlockedStatus("blah"))
