# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""This module defines the custom events that are handled by the data interfaces."""

import json
import pickle  # nosec: B403
from typing import Any, Generic, TypeVar

from ops import Application, CharmEvents, EventBase, EventSource, Handle, Relation, Unit
from ops.charm import RelationEvent

from data_platform_helpers.interfaces.models import (
    RelationStatus,
    RequirerCommonModel,
    ResourceProviderModel,
)

TRequirerCommonModel = TypeVar("TRequirerCommonModel", bound=RequirerCommonModel)
TResourceProviderModel = TypeVar("TResourceProviderModel", bound=ResourceProviderModel)

STATUS_FIELD = "status"


class ResourceProviderEvent(EventBase, Generic[TRequirerCommonModel]):
    """Resource requested event.

    Contains the request that should be handled.

    fields to serialize: relation, app, unit, request
    """

    def __init__(
        self,
        handle: Handle,
        relation: Relation,
        app: Application | None,
        unit: Unit | None,
        request: TRequirerCommonModel,
    ):
        super().__init__(handle)
        self.relation = relation
        self.app = app
        self.unit = unit
        self.request = request

    def snapshot(self) -> dict[str, Any]:
        """Save the event information."""
        snapshot = {"relation_name": self.relation.name, "relation_id": self.relation.id}
        if self.app:
            snapshot["app_name"] = self.app.name
        if self.unit:
            snapshot["unit_name"] = self.unit.name
        # The models are too complex and would be blocked by marshal so we pickle dump the model.
        # The full dictionary is pickled afterwards anyway.
        snapshot["request"] = pickle.dumps(self.request)
        return snapshot

    def restore(self, snapshot: dict[str, Any]):
        """Restore event information."""
        relation = self.framework.model.get_relation(
            snapshot["relation_name"], snapshot["relation_id"]
        )
        if not relation:
            raise ValueError("Missing relation")
        self.relation = relation
        self.app = None
        app_name = snapshot.get("app_name")
        if app_name:
            self.app = self.framework.model.get_app(app_name)
        self.unit = None
        unit_name = snapshot.get("unit_name")
        if unit_name:
            self.app = self.framework.model.get_app(unit_name)
        self.request = pickle.loads(snapshot["request"])  # nosec: B301


class ResourceRequestedEvent(ResourceProviderEvent[TRequirerCommonModel]):
    """Resource requested event."""

    pass


class ResourceEntityRequestedEvent(ResourceProviderEvent[TRequirerCommonModel]):
    """Resource Entity requested event."""

    pass


class ResourceEntityPermissionsChangedEvent(ResourceProviderEvent[TRequirerCommonModel]):
    """Resource entity permissions changed event."""

    pass


class MtlsCertUpdatedEvent(ResourceProviderEvent[TRequirerCommonModel]):
    """Resource entity permissions changed event."""

    def __init__(
        self,
        handle: Handle,
        relation: Relation,
        app: Application | None,
        unit: Unit | None,
        request: TRequirerCommonModel,
        old_mtls_cert: str | None = None,
    ):
        super().__init__(handle, relation, app, unit, request)

        self.old_mtls_cert = old_mtls_cert

    def snapshot(self):
        """Return a snapshot of the event."""
        return super().snapshot() | {"old_mtls_cert": self.old_mtls_cert}

    def restore(self, snapshot):
        """Restore the event from a snapshot."""
        super().restore(snapshot)
        self.old_mtls_cert = snapshot["old_mtls_cert"]


class BulkResourcesRequestedEvent(EventBase, Generic[TRequirerCommonModel]):
    """Resource requested event.

    Contains the request that should be handled.

    fields to serialize: relation, app, unit, request
    """

    def __init__(
        self,
        handle: Handle,
        relation: Relation,
        app: Application | None,
        unit: Unit | None,
        requests: list[TRequirerCommonModel],
    ):
        super().__init__(handle)
        self.relation = relation
        self.app = app
        self.unit = unit
        self.requests = requests

    def snapshot(self) -> dict[str, Any]:
        """Save the event information."""
        snapshot = {"relation_name": self.relation.name, "relation_id": self.relation.id}
        if self.app:
            snapshot["app_name"] = self.app.name
        if self.unit:
            snapshot["unit_name"] = self.unit.name
        # The models are too complex and would be blocked by marshal so we pickle dump the model.
        # The full dictionary is pickled afterwards anyway.
        snapshot["requests"] = [pickle.dumps(request) for request in self.requests]
        return snapshot

    def restore(self, snapshot: dict[str, Any]):
        """Restore event information."""
        relation = self.framework.model.get_relation(
            snapshot["relation_name"], snapshot["relation_id"]
        )
        if not relation:
            raise ValueError("Missing relation")
        self.relation = relation
        self.app = None
        app_name = snapshot.get("app_name")
        if app_name:
            self.app = self.framework.model.get_app(app_name)
        self.unit = None
        unit_name = snapshot.get("unit_name")
        if unit_name:
            self.app = self.framework.model.get_app(unit_name)
        self.requests = [pickle.loads(request) for request in snapshot["requests"]]  # nosec: B301


class ResourceProvidesEvents(CharmEvents, Generic[TRequirerCommonModel]):
    """Database events.

    This class defines the events that the database can emit.
    """

    bulk_resources_requested = EventSource(BulkResourcesRequestedEvent)
    resource_requested = EventSource(ResourceRequestedEvent)
    resource_entity_requested = EventSource(ResourceEntityRequestedEvent)
    resource_entity_permissions_changed = EventSource(ResourceEntityPermissionsChangedEvent)
    mtls_cert_updated = EventSource(MtlsCertUpdatedEvent)


class ResourceRequirerEvent(EventBase, Generic[TResourceProviderModel]):
    """Resource created/changed event.

    Contains the request that should be handled.

    fields to serialize: relation, app, unit, response
    """

    def __init__(
        self,
        handle: Handle,
        relation: Relation,
        app: Application | None,
        unit: Unit | None,
        response: TResourceProviderModel,
    ):
        super().__init__(handle)
        self.relation = relation
        self.app = app
        self.unit = unit
        self.response = response

    def snapshot(self) -> dict:
        """Save the event information."""
        snapshot = {"relation_name": self.relation.name, "relation_id": self.relation.id}
        if self.app:
            snapshot["app_name"] = self.app.name
        if self.unit:
            snapshot["unit_name"] = self.unit.name
        # The models are too complex and would be blocked by marshal so we pickle dump the model.
        # The full dictionary is pickled afterwards anyway.
        snapshot["response"] = pickle.dumps(self.response)
        return snapshot

    def restore(self, snapshot: dict):
        """Restore event information."""
        relation = self.framework.model.get_relation(
            snapshot["relation_name"], snapshot["relation_id"]
        )
        if not relation:
            raise ValueError("Missing relation")
        self.relation = relation
        self.app = None
        app_name = snapshot.get("app_name")
        if app_name:
            self.app = self.framework.model.get_app(app_name)
        self.unit = None
        unit_name = snapshot.get("unit_name")
        if unit_name:
            self.app = self.framework.model.get_app(unit_name)

        self.response = pickle.loads(snapshot["response"])  # nosec: B301


class ResourceCreatedEvent(ResourceRequirerEvent[TResourceProviderModel]):
    """Resource has been created."""

    pass


class ResourceEntityCreatedEvent(ResourceRequirerEvent[TResourceProviderModel]):
    """Resource entity has been created."""

    pass


class ResourceEndpointsChangedEvent(ResourceRequirerEvent[TResourceProviderModel]):
    """Read/Write endpoints are changed."""

    pass


class ResourceReadOnlyEndpointsChangedEvent(ResourceRequirerEvent[TResourceProviderModel]):
    """Read-only endpoints are changed."""

    pass


class AuthenticationUpdatedEvent(ResourceRequirerEvent[TResourceProviderModel]):
    """Authentication was updated for a user."""

    pass


# Error Propagation Events


class StatusEventBase(RelationEvent):
    """Base class for relation status change events."""

    def __init__(
        self,
        handle: Handle,
        relation: Relation,
        status: RelationStatus,
        app: Application | None = None,
        unit: Unit | None = None,
    ):
        super().__init__(handle, relation, app=app, unit=unit)
        self.status = status

    def snapshot(self) -> dict:
        """Return a snapshot of the event."""
        return super().snapshot() | {"status": json.dumps(self.status.model_dump())}

    def restore(self, snapshot: dict):
        """Restore the event from a snapshot."""
        super().restore(snapshot)
        self.status = RelationStatus(**json.loads(snapshot["status"]))

    @property
    def active_statuses(self) -> list[RelationStatus]:
        """Returns a list of all currently active statuses on this relation."""
        if not self.relation.app:
            return []

        raw = json.loads(self.relation.data[self.relation.app].get(STATUS_FIELD, "[]"))

        return [RelationStatus(**item) for item in raw]


class StatusRaisedEvent(StatusEventBase):
    """Event emitted on the requirer when a new status is being raised by the provider."""


class StatusResolvedEvent(StatusEventBase):
    """Event emitted on the requirer when a status is marked as resolved by the provider."""


class ResourceRequiresEvents(CharmEvents, Generic[TResourceProviderModel]):
    """Database events.

    This class defines the events that the database can emit.
    """

    resource_created = EventSource(ResourceCreatedEvent)
    resource_entity_created = EventSource(ResourceEntityCreatedEvent)
    endpoints_changed = EventSource(ResourceEndpointsChangedEvent)
    read_only_endpoints_changed = EventSource(ResourceReadOnlyEndpointsChangedEvent)
    authentication_updated = EventSource(AuthenticationUpdatedEvent)
    status_raised = EventSource(StatusRaisedEvent)
    status_resolved = EventSource(StatusResolvedEvent)
