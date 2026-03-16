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
"""The event handlers for the data interfaces."""

import json
from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from logging import getLogger
from pathlib import Path
from typing import Generic, TypeVar, overload

from ops import Application, Object, Relation, RelationCreatedEvent, RelationEvent, Unit
from ops.charm import CharmBase, RelationChangedEvent, SecretChangedEvent, SecretRemoveEvent
from ops.model import ModelError, SecretNotFoundError
from pydantic import TypeAdapter
from typing_extensions import override

from data_platform_helpers.interfaces.diff import Diff, diff, resource_added, store_new_data
from data_platform_helpers.interfaces.events import (
    STATUS_FIELD,
    ResourceCreatedEvent,
    ResourceEndpointsChangedEvent,
    ResourceEntityCreatedEvent,
    ResourceProvidesEvents,
    ResourceReadOnlyEndpointsChangedEvent,
    ResourceRequiresEvents,
)
from data_platform_helpers.interfaces.models import (
    DataContractV0,
    DataContractV1,
    RelationStatus,
    RequirerCommonModel,
    RequirerDataContractV0,
    RequirerDataContractV1,
    ResourceProviderModel,
)
from data_platform_helpers.interfaces.repository import AbstractRepository, OpsRelationRepository
from data_platform_helpers.interfaces.repository_interfaces import (
    OpsRelationRepositoryInterface,
    RepositoryInterface,
    build_model,
    write_model,
)
from data_platform_helpers.interfaces.types import OptionalPathLike, RelationStatusDict
from data_platform_helpers.interfaces.utils import gen_hash, get_encoded_dict

try:
    import psycopg2  # type: ignore[reportMissingModuleSource]
except ImportError:
    psycopg2 = None

logger = getLogger(__name__)

TRequirerCommonModel = TypeVar("TRequirerCommonModel", bound=RequirerCommonModel)
TResourceProviderModel = TypeVar("TResourceProviderModel", bound=ResourceProviderModel)


class EventHandlers(Object):
    """Requires-side of the relation."""

    component: Application | Unit
    interface: RepositoryInterface

    def __init__(self, charm: CharmBase, relation_name: str, unique_key: str = ""):
        """Manager of base client relations."""
        if not unique_key:
            unique_key = relation_name
        super().__init__(charm, unique_key)

        self.charm = charm
        self.relation_name = relation_name

        self.framework.observe(
            charm.on[self.relation_name].relation_changed,
            self._on_relation_changed_event,
        )

        self.framework.observe(
            self.charm.on[self.relation_name].relation_created,
            self._on_relation_created_event,
        )

        self.framework.observe(
            charm.on.secret_changed,
            self._on_secret_changed_event,
        )
        self.framework.observe(charm.on.secret_remove, self._on_secret_remove_event)

    @property
    def relations(self) -> list[Relation]:
        """Shortcut to get access to the relations."""
        return self.interface.relations

    def get_remote_unit(self, relation: Relation) -> Unit | None:
        """Gets the remote unit in the relation."""
        remote_unit = None
        for unit in relation.units:
            if unit.app != self.charm.app:
                remote_unit = unit
                break
        return remote_unit

    def get_statuses(self, relation_id: int) -> dict[int, RelationStatus]:
        """Return all currently active statuses on this relation. Can only be called on leader units.

        Args:
            relation_id (int): the identifier for a particular relation.

        Returns:
            Dict[int, RelationStatus]: A mapping of status code to RelationStatus instances.
        """
        relation = self.charm.model.get_relation(self.relation_name, relation_id)

        if not relation:
            raise ValueError("Missing relation.")

        component = self.charm.app if isinstance(self.component, Application) else relation.app

        raw = relation.data[component].get(STATUS_FIELD, "[]")

        return {int(item["code"]): RelationStatus(**item) for item in json.loads(raw)}

    # Event handlers

    def _on_relation_created_event(self, event: RelationCreatedEvent) -> None:
        """Event emitted when the relation is created."""
        pass

    @abstractmethod
    def _on_relation_changed_event(self, event: RelationChangedEvent) -> None:
        """Event emitted when the relation data has changed."""
        raise NotImplementedError

    @abstractmethod
    def _on_secret_changed_event(self, event: SecretChangedEvent) -> None:
        """Event emitted when the relation data has changed."""
        raise NotImplementedError

    def _on_secret_remove_event(self, event: SecretRemoveEvent) -> None:
        """Event emitted when a secret is removed.

        A secret removal (entire removal, not just a revision removal) causes
        https://github.com/juju/juju/issues/20794. This check is to avoid the
        errors that would happen if we tried to remove the revision in that case
        (in the revision removal, the label is present).
        """
        if not event.secret.label:
            return
        relation = self._relation_from_secret_label(event.secret.label)

        if not relation:
            logger.info(
                f"Received secret {event.secret.label} but couldn't parse, seems irrelevant"
            )
            return

        try:
            event.secret.get_info()
        except SecretNotFoundError:
            logger.info("Secret removed event ignored for non Secret Owner")
            return

        if relation.name != self.relation_name:
            logger.info("Secret changed on wrong relation.")
            return

        event.remove_revision()

    @abstractmethod
    def _handle_event(self, *args, **kwargs):
        """Handles the event and reacts accordingly."""
        pass

    def compute_diff(
        self,
        relation: Relation,
        request: RequirerCommonModel | ResourceProviderModel,
        repository: AbstractRepository | None = None,
        store: bool = True,
    ) -> Diff:
        """Computes, stores and returns a diff for that request."""
        if not repository:
            repository = OpsRelationRepository(self.model, relation, component=relation.app)

        # Gets the data stored in the databag for diff computation
        old_data = get_encoded_dict(relation, self.component, "data")

        # In case we're V1, we select specifically this request
        if old_data and request.request_id:
            old_data: dict | None = old_data.get(request.request_id, None)

        # dump the data of the current request so we can compare
        new_data = request.model_dump(
            mode="json",
            exclude={"data"},
            exclude_none=True,
            exclude_defaults=True,
        )

        # Computes the diff
        _diff = diff(old_data, new_data)

        if store:
            # Update the databag with the new data for later diff computations
            store_new_data(
                relation,
                self.component,
                new_data,
                short_uuid=request.request_id,
                global_data={
                    STATUS_FIELD: {
                        code: status.model_dump()
                        for code, status in self.get_statuses(relation.id).items()
                    }
                },
            )

        return _diff

    def _relation_from_secret_label(self, secret_label: str) -> Relation | None:
        """Retrieve the relation that belongs to a secret label."""
        contents = secret_label.split(".")

        if not (contents and len(contents) >= 3):
            return None

        try:
            relation_id = int(contents[1])
        except ValueError:
            return None

        relation_name = contents[0]

        try:
            return self.model.get_relation(relation_name, relation_id)
        except ModelError:
            return None

    def _short_uuid_from_secret_label(self, secret_label: str) -> str | None:
        """Retrieve the relation that belongs to a secret label."""
        contents = secret_label.split(".")

        if not (contents and len(contents) >= 5):
            return None

        return contents[2]


class ResourceProviderEventHandler(EventHandlers, Generic[TRequirerCommonModel]):
    """Event Handler for resource provider."""

    on = ResourceProvidesEvents[TRequirerCommonModel]()  # type: ignore[reportAssignmentType]

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str,
        request_model: type[TRequirerCommonModel],
        unique_key: str = "",
        mtls_enabled: bool = False,
        bulk_event: bool = False,
        status_schema_path: OptionalPathLike = None,
        resource_aliases: list[str] | None = None,
    ):
        """Builds a resource provider event handler.

        Args:
            charm: The charm.
            relation_name: The relation name this event handler is listening to.
            request_model: The request model that is expected to be received.
            unique_key: An optional unique key for that object.
            mtls_enabled: If True, means the server supports MTLS integration.
            bulk_event: Only one event will be emitted with all requests in the case of a v1 requirer.
            status_schema_path: Path to the JSON file defining status/error codes and their definitions.
            resource_aliases: An optional list of strings that defines extra aliases for the resource field.
        """
        super().__init__(charm, relation_name, unique_key)
        self.component = self.charm.app
        self.request_model = request_model
        self.interface = OpsRelationRepositoryInterface(charm.model, relation_name, request_model)
        self.mtls_enabled = mtls_enabled
        self.bulk_event = bulk_event
        self._extra_aliases = resource_aliases

        self._status_schema = (
            {} if not status_schema_path else self._load_status_schema(Path(status_schema_path))
        )

    def _load_status_schema(self, schema_path: Path) -> dict[int, RelationStatus]:
        """Load JSON schema defining status codes and their details.

        Args:
            schema_path: JSON schema file path.

        Raises:
            FileNotFoundError: If the provided path is invalid/inaccessible.

        Returns:
            dict[int, RelationStatusDict]: Mapping of status code to RelationStatus data objects.
        """
        if not schema_path.exists():
            raise FileNotFoundError(f"Can't locate status schema file: {schema_path}")

        content = json.load(open(schema_path))

        return {s["code"]: RelationStatus(**s) for s in content.get("statuses", [])}

    @staticmethod
    def _validate_diff(event: RelationEvent, _diff: Diff) -> None:
        """Validates that entity information is not changed after relation is established.

        - When entity-type changes, backwards compatibility is broken.
        - When extra-user-roles changes, role membership checks become incredibly complex.
        - When extra-group-roles changes, role membership checks become incredibly complex.
        """
        if not isinstance(event, RelationChangedEvent):
            return

        for key in [
            "resource",
            "entity-type",
            "extra-user-roles",
            "extra-group-roles",
        ]:
            if key in _diff.changed:
                raise ValueError(f"Cannot change {key} after relation has already been created")

    def _dispatch_events(self, event: RelationEvent, _diff: Diff, request: RequirerCommonModel):
        if self.mtls_enabled and "secret-mtls" in _diff.added:
            getattr(self.on, "mtls_cert_updated").emit(
                event.relation, app=event.app, unit=event.unit, request=request, old_mtls_cert=None
            )
            return
        # Emit a resource requested event if the setup key (resource name)
        # was added to the relation databag, but the entity-type key was not.
        if resource_added(_diff, self._extra_aliases) and "entity-type" not in _diff.added:
            getattr(self.on, "resource_requested").emit(
                event.relation,
                app=event.app,
                unit=event.unit,
                request=request,
            )
            # To avoid unnecessary application restarts do not trigger other events.
            return

        # Emit an entity requested event if the setup key (resource name)
        # was added to the relation databag, in addition to the entity-type key.
        if resource_added(_diff, self._extra_aliases) and "entity-type" in _diff.added:
            getattr(self.on, "resource_entity_requested").emit(
                event.relation,
                app=event.app,
                unit=event.unit,
                request=request,
            )
            # To avoid unnecessary application restarts do not trigger other events.
            return

        # Emit a permissions changed event if the setup key (resource name)
        # was added to the relation databag, and the entity-permissions key changed.
        if (
            not resource_added(_diff, self._extra_aliases)
            and "entity-type" not in _diff.added
            and ("entity-permissions" in _diff.added or "entity-permissions" in _diff.changed)
        ):
            getattr(self.on, "resource_entity_permissions_changed").emit(
                event.relation, app=event.app, unit=event.unit, request=request
            )
            # To avoid unnecessary application restarts do not trigger other events.
            return

    @override
    def _handle_event(
        self,
        event: RelationChangedEvent,
        repository: AbstractRepository,
        request: RequirerCommonModel,
    ):
        _diff = self.compute_diff(event.relation, request, repository)

        self._validate_diff(event, _diff)
        self._dispatch_events(event, _diff, request)

    def _handle_bulk_event(
        self,
        event: RelationChangedEvent,
        repository: AbstractRepository,
        request_model: RequirerDataContractV1[TRequirerCommonModel],
    ):
        """Validate all the diffs, then dispatch the bulk event AND THEN stores the diff.

        This allows for the developer to process the diff and store it themselves
        """
        for request in request_model.requests:
            # Compute the diff without storing it so we can validate the diffs.
            _diff = self.compute_diff(event.relation, request, repository, store=False)
            self._validate_diff(event, _diff)

        getattr(self.on, "bulk_resources_requested").emit(
            event.relation, app=event.app, unit=event.unit, requests=request_model.requests
        )

        # Store all the diffs if they were not already stored.
        for request in request_model.requests:
            new_data = request.model_dump(
                mode="json",
                exclude={"data"},
                context={"repository": repository},
                exclude_none=True,
                exclude_defaults=True,
            )
            store_new_data(event.relation, self.component, new_data, request.request_id)

    @override
    def _on_secret_changed_event(self, event: SecretChangedEvent) -> None:
        if not self.mtls_enabled:
            logger.info("MTLS is disabled, exiting early.")
            return
        if not event.secret.label:
            return

        relation = self._relation_from_secret_label(event.secret.label)
        short_uuid = self._short_uuid_from_secret_label(event.secret.label)

        if not relation:
            logger.info(
                f"Received secret {event.secret.label} but couldn't parse, seems irrelevant"
            )
            return

        if relation.name != self.relation_name:
            logger.info("Secret changed on wrong relation.")
            return

        try:
            event.secret.get_info()
            logger.info("Secret changed event ignored for Secret Owner")
            return
        except SecretNotFoundError:
            pass

        remote_unit = self.get_remote_unit(relation)

        repository = OpsRelationRepository(self.model, relation, component=relation.app)
        version = repository.get_field("version") or "v0"

        old_mtls_cert = event.secret.get_content().get("mtls-cert")
        logger.info("mtls-cert-updated")

        # V0, just fire the event.
        if version == "v0":
            request = build_model(repository, RequirerDataContractV0)
        # V1, find the corresponding request.
        else:
            request_model = build_model(repository, RequirerDataContractV1[self.request_model])
            if not short_uuid:
                return
            for _request in request_model.requests:
                if _request.request_id == short_uuid:
                    request = _request
                    break
            else:
                logger.info(f"Unknown request id {short_uuid}")
                return

        getattr(self.on, "mtls_cert_updated").emit(
            relation,
            app=relation.app,
            unit=remote_unit,
            request=request,
            old_mtls_cert=old_mtls_cert,
        )

    @override
    def _on_relation_changed_event(self, event: RelationChangedEvent):
        if not self.charm.unit.is_leader():
            return

        repository = OpsRelationRepository(self.model, event.relation, component=event.relation.app)

        # Don't do anything until we get some data
        if not repository.get_data():
            return

        version = repository.get_field("version") or "v0"
        if version == "v0":
            request_model = build_model(repository, RequirerDataContractV0)
            old_name = request_model.original_field
            request_model.request_id = None  # For safety, let's ensure that we don't have a model.
            self._handle_event(event, repository, request_model)
            logger.info(
                f"Patching databag for v0 compatibility: replacing 'resource' by '{old_name}'"
            )
            self.interface.repository(
                event.relation.id,
            ).write_field(old_name, request_model.resource)
        else:
            request_model = build_model(repository, RequirerDataContractV1[self.request_model])
            if self.bulk_event:
                self._handle_bulk_event(event, repository, request_model)
                return
            for request in request_model.requests:
                self._handle_event(event, repository, request)

    def set_response(self, relation_id: int, response: ResourceProviderModel):
        r"""Sets a response in the databag.

        This function will react accordingly to the version number.
        If the version number is v0, then we write the data directly in the databag.
        If the version number is v1, then we write the data in the list of responses.

        /!\ This function updates a response if it was already present in the databag!

        Args:
            relation_id: The specific relation id for that event.
            response: The response to write in the databag.
        """
        if not self.charm.unit.is_leader():
            return

        relation = self.charm.model.get_relation(self.relation_name, relation_id)

        if not relation:
            raise ValueError("Missing relation.")

        repository = OpsRelationRepository(self.model, relation, component=relation.app)
        version = repository.get_field("version") or "v0"

        if version == "v0":
            # Ensure the request_id is None
            response.request_id = None
            self.interface.write_model(
                relation_id, response, context={"version": "v0"}
            )  # {"database": "database-name", "secret-user": "uri", ...}
            return

        model = self.interface.build_model(relation_id, DataContractV1[response.__class__])

        # for/else syntax allows to execute the else if break was not called.
        # This allows us to update or append easily.
        for index, _response in enumerate(model.requests):
            if _response.request_id == response.request_id:
                model.requests[index].update(response)
                break
        else:
            model.requests.append(response)

        self.interface.write_model(relation_id, model)
        return

    def set_responses(self, relation_id: int, responses: list[ResourceProviderModel]) -> None:
        r"""Sets a list of responses in the databag.

        This function will react accordingly to the version number.
        If the version number is v0, then we write the data directly in the databag.
        If the version number is v1, then we write the data in the list of responses.

        /!\ This function updates a response if it was already present in the databag!

        Args:
            relation_id: The specific relation id for that event.
            responses: The response to write in the databag.
        """
        if not self.charm.unit.is_leader():
            return

        relation = self.charm.model.get_relation(self.relation_name, relation_id)

        assert len(responses) >= 1, "List of responses is empty"

        if not relation:
            raise ValueError("Missing relation.")

        repository = OpsRelationRepository(self.model, relation, component=relation.app)
        version = repository.get_field("version") or "v0"

        if version == "v0":
            assert len(responses) == 1, "V0 only expects one response"
            # Ensure the request_id is None
            response = responses[0]
            response.request_id = None
            self.interface.write_model(
                relation_id, response, context={"version": "v0"}
            )  # {"database": "database-name", "secret-user": "uri", ...}
            return

        model = self.interface.build_model(relation_id, DataContractV1[responses[0].__class__])

        response_map: dict[str, ResourceProviderModel] = {
            response.request_id: response for response in responses if response.request_id
        }

        # Update all the already existing keys
        for index, _response in enumerate(model.requests):
            assert _response.request_id, "Missing request id in the response"
            response = response_map.get(_response.request_id)
            if response:
                model.requests[index].update(response)
                del response_map[_response.request_id]

        # Add the missing keys
        model.requests += list(response_map.values())

        self.interface.write_model(relation_id, model)
        return

    def requests(self, relation: Relation) -> Sequence[RequirerCommonModel]:
        """Returns the list of requests that we got."""
        repository = OpsRelationRepository(self.model, relation, component=relation.app)

        # Don't do anything until we get some data
        if not repository.get_data():
            return []

        version = repository.get_field("version") or "v0"
        if version == "v0":
            request_model = build_model(repository, RequirerDataContractV0)
            request_model.request_id = None  # For safety, let's ensure that we don't have a model.
            return [request_model]
        request_model = build_model(repository, RequirerDataContractV1[self.request_model])
        return request_model.requests

    def responses(
        self, relation: Relation, model: type[ResourceProviderModel]
    ) -> list[ResourceProviderModel]:
        """Returns the list of responses that we currently have."""
        repository = self.interface.repository(relation.id, component=relation.app)

        version = repository.get_field("version") or "v0"
        if version == "v0":
            # Ensure the request_id is None
            return [self.interface.build_model(relation.id, DataContractV0)]

        return self.interface.build_model(relation.id, DataContractV1[model]).requests

    @overload
    def raise_status(self, relation_id: int, status: int) -> None: ...

    @overload
    def raise_status(self, relation_id: int, status: RelationStatusDict) -> None: ...

    @overload
    def raise_status(self, relation_id: int, status: RelationStatus) -> None: ...

    def raise_status(
        self, relation_id: int, status: RelationStatus | RelationStatusDict | int
    ) -> None:
        """Raise a status on the relation. Can only be called on leader units.

        Args:
            relation_id (int): the identifier for a particular relation.
            status (RelationStatus | RelationStatusDict | int): A representation of the status being raised,
                which could be either a RelationStatus, an appropriate dict, or the numeric status code.

        Raises:
            ValueError: If the status provided is not correctly formatted.
        """
        relation = self.charm.model.get_relation(self.relation_name, relation_id)

        if not relation:
            raise ValueError("Missing relation.")

        if isinstance(status, int):
            # we expect the status schema to be defined in this case.
            if status not in self._status_schema:
                raise KeyError(f"Status code [{status}] not defined.")
            _status = self._status_schema[status]
        elif isinstance(status, dict):
            _status = RelationStatus(**status)
        elif isinstance(status, RelationStatus):
            _status = status
        else:
            raise ValueError(
                "The status should be either a RelationStatus, an appropriate dict, or the numeric status code."
            )

        statuses = self.get_statuses(relation_id)
        statuses.update({_status.code: _status})
        serialized = json.dumps([statuses[k].model_dump() for k in sorted(statuses)])

        repository = OpsRelationRepository(self.model, relation, component=self.charm.app)
        repository.write_field(STATUS_FIELD, serialized)

    def resolve_status(self, relation_id: int, status_code: int) -> None:
        """Set a previously raised status as resolved.

        Args:
            relation_id (int): the identifier for a particular relation.
            status_code (int): the numeric code of the resolved status.
        """
        relation = self.charm.model.get_relation(self.relation_name, relation_id)

        if not relation:
            raise ValueError("Missing relation.")

        statuses = self.get_statuses(relation_id)
        if status_code not in statuses:
            logger.error(f"Status [{status_code}] has never been raised before.")
            return

        statuses.pop(status_code)
        serialized = json.dumps([statuses[k].model_dump() for k in sorted(statuses)])

        repository = OpsRelationRepository(self.model, relation, component=self.charm.app)
        repository.write_field(STATUS_FIELD, serialized)

    def clear_statuses(self, relation_id: int) -> None:
        """Clear all previously raised statuses.

        Args:
            relation_id (int): the identifier for a particular relation.
        """
        relation = self.charm.model.get_relation(self.relation_name, relation_id)

        if not relation:
            raise ValueError("Missing relation.")

        repository = OpsRelationRepository(self.model, relation, component=self.charm.app)
        repository.delete_field(STATUS_FIELD)


class ResourceRequirerEventHandler(EventHandlers, Generic[TResourceProviderModel]):
    """Event Handler for resource requirer."""

    on = ResourceRequiresEvents[TResourceProviderModel]()  # type: ignore[reportAssignmentType]

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str,
        requests: list[RequirerCommonModel],
        response_model: type[TResourceProviderModel],
        unique_key: str = "",
        relation_aliases: list[str] | None = None,
    ):
        super().__init__(charm, relation_name, unique_key)
        self.component = self.charm.unit
        self.relation_aliases = relation_aliases
        self._requests = requests
        self.response_model = DataContractV1[response_model]
        self.interface: OpsRelationRepositoryInterface[DataContractV1[TResourceProviderModel]] = (
            OpsRelationRepositoryInterface(charm.model, relation_name, self.response_model)
        )

        if requests:
            self._request_model = requests[0].__class__
        else:
            self._request_model = RequirerCommonModel

        # First, check that the number of aliases matches the one defined in charm metadata.
        if self.relation_aliases:
            relation_connection_limit = self.charm.meta.requires[relation_name].limit
            if len(self.relation_aliases) != relation_connection_limit:
                raise ValueError(
                    f"Invalid number of aliases, expected {relation_connection_limit}, received {len(self.relation_aliases)}"
                )

        # Created custom event names for each alias.
        if self.relation_aliases:
            for relation_alias in self.relation_aliases:
                self.on.define_event(
                    f"{relation_alias}_resource_created",
                    ResourceCreatedEvent,
                )
                self.on.define_event(
                    f"{relation_alias}_resource_entity_created",
                    ResourceEntityCreatedEvent,
                )
                self.on.define_event(
                    f"{relation_alias}_endpoints_changed",
                    ResourceEndpointsChangedEvent,
                )
                self.on.define_event(
                    f"{relation_alias}_read_only_endpoints_changed",
                    ResourceReadOnlyEndpointsChangedEvent,
                )

    ##############################################################################
    # Extra useful functions
    ##############################################################################
    def is_resource_created(
        self,
        rel_id: int,
        request_id: str,
        model: DataContractV1[TResourceProviderModel] | None = None,
    ) -> bool:
        """Checks if a resource has been created or not.

        Args:
            rel_id: The relation id to check.
            request_id: The specific request id to check.
            model: An optional model to use (for performances).
        """
        if not model:
            relation = self.model.get_relation(self.relation_name, rel_id)
            if not relation:
                return False
            model = self.interface.build_model(relation_id=rel_id, component=relation.app)
        for request in model.requests:
            if request.request_id == request_id:
                return request.secret_user is not None or request.secret_entity is not None
        return False

    def are_all_resources_created(self, rel_id: int) -> bool:
        """Checks that all resources have been created for a relation.

        Args:
            rel_id: The relation id to check.
        """
        relation = self.model.get_relation(self.relation_name, rel_id)
        if not relation:
            return False
        model = self.interface.build_model(relation_id=rel_id, component=relation.app)
        return all(
            self.is_resource_created(rel_id, request.request_id, model)
            for request in model.requests
            if request.request_id
        )

    @staticmethod
    def _is_pg_plugin_enabled(plugin: str, connection_string: str) -> bool:
        # Actual checking method.
        # No need to check for psycopg here, it's been checked before.
        if not psycopg2:
            return False

        try:
            with psycopg2.connect(connection_string) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT TRUE FROM pg_extension WHERE extname=%s::text;", (plugin,)
                    )
                    return cursor.fetchone() is not None
        except psycopg2.Error as e:
            logger.exception(
                f"failed to check whether {plugin} plugin is enabled in the database: %s",
                str(e),
            )
            return False

    def is_postgresql_plugin_enabled(self, plugin: str, relation_index: int = 0) -> bool:
        """Returns whether a plugin is enabled in the database.

        Args:
            plugin: name of the plugin to check.
            relation_index: Optional index to check the database (default: 0 - first relation).
        """
        if not psycopg2:
            return False

        # Can't check a non existing relation.
        if len(self.relations) <= relation_index:
            return False

        relation = self.relations[relation_index]
        model = self.interface.build_model(relation_id=relation.id, component=relation.app)
        for request in model.requests:
            if request.endpoints and request.username and request.password:
                host = request.endpoints.split(":")[0]
                username = request.username
                password = request.password

                connection_string = f"host='{host}' dbname='{request.resource}' user='{username}' password='{password}'"
                return self._is_pg_plugin_enabled(plugin, connection_string)
        logger.info("No valid request to use to check for plugin.")
        return False

    ##############################################################################
    # Helpers for aliases
    ##############################################################################

    def _assign_relation_alias(self, relation_id: int) -> None:
        """Assigns an alias to a relation.

        This function writes in the unit data bag.

        Args:
            relation_id: the identifier for a particular relation.
        """
        # If no aliases were provided, return immediately.
        if not self.relation_aliases:
            return

        # Return if an alias was already assigned to this relation
        # (like when there are more than one unit joining the relation).
        relation = self.charm.model.get_relation(self.relation_name, relation_id)
        if relation and relation.data[self.charm.unit].get("alias"):
            return

        # Retrieve the available aliases (the ones that weren't assigned to any relation).
        available_aliases = self.relation_aliases[:]
        for relation in self.charm.model.relations[self.relation_name]:
            alias = relation.data[self.charm.unit].get("alias")
            if alias:
                logger.debug("Alias %s was already assigned to relation %d", alias, relation.id)
                available_aliases.remove(alias)

        # Set the alias in the unit relation databag of the specific relation.
        relation = self.charm.model.get_relation(self.relation_name, relation_id)
        if relation:
            relation.data[self.charm.unit].update({"alias": available_aliases[0]})

        # We need to set relation alias also on the application level so,
        # it will be accessible in show-unit juju command, executed for a consumer application unit
        if relation and self.charm.unit.is_leader():
            relation.data[self.charm.app].update({"alias": available_aliases[0]})

    def _emit_aliased_event(
        self, event: RelationChangedEvent, event_name: str, response: ResourceProviderModel
    ):
        """Emit all aliased events."""
        alias = self._get_relation_alias(event.relation.id)
        if alias:
            getattr(self.on, f"{alias}_{event_name}").emit(
                event.relation, app=event.app, unit=event.unit, response=response
            )

    def _get_relation_alias(self, relation_id: int) -> str | None:
        """Gets the relation alias for a relation id."""
        for relation in self.charm.model.relations[self.relation_name]:
            if relation.id == relation_id:
                return relation.data[self.charm.unit].get("alias")
        return None

    ##############################################################################
    # Event Handlers
    ##############################################################################

    def _on_secret_changed_event(self, event: SecretChangedEvent):
        """Event notifying about a new value of a secret."""
        if not event.secret.label:
            return
        relation = self._relation_from_secret_label(event.secret.label)
        short_uuid = self._short_uuid_from_secret_label(event.secret.label)

        if not relation:
            logger.info(
                f"Received secret {event.secret.label} but couldn't parse, seems irrelevant"
            )
            return

        if relation.name != self.relation_name:
            logger.info("Secret changed on wrong relation.")
            return

        try:
            event.secret.get_info()
            logger.info("Secret changed event ignored for Secret Owner")
            return
        except SecretNotFoundError:
            pass

        remote_unit = self.get_remote_unit(relation)

        response_model = self.interface.build_model(relation.id, component=relation.app)
        if not short_uuid:
            return
        for _response in response_model.requests:
            if _response.request_id == short_uuid:
                response = _response
                break
        else:
            logger.info(f"Unknown request id {short_uuid}")
            return

        getattr(self.on, "authentication_updated").emit(
            relation,
            app=relation.app,
            unit=remote_unit,
            response=response,
        )

    def _on_relation_created_event(self, event: RelationCreatedEvent) -> None:
        """Event emitted when the database relation is created."""
        super()._on_relation_created_event(event)

        repository = OpsRelationRepository(self.model, event.relation, self.charm.app)

        # If relations aliases were provided, assign one to the relation.
        self._assign_relation_alias(event.relation.id)

        if not self.charm.unit.is_leader():
            return

        # Generate all requests id so they are saved already.
        for request in self._requests:
            request.request_id = gen_hash(request.resource, request.salt)

        full_request = RequirerDataContractV1[self._request_model](
            version="v1", requests=self._requests
        )
        write_model(repository, full_request)

    def _on_relation_changed_event(self, event: RelationChangedEvent) -> None:
        """Event emitted when the database relation has changed."""
        is_subordinate = False
        remote_unit_data = None
        for key in event.relation.data.keys():
            if isinstance(key, Unit) and not key.name.startswith(self.charm.app.name):
                remote_unit_data = event.relation.data[key]
            elif isinstance(key, Application) and key.name != self.charm.app.name:
                is_subordinate = event.relation.data[key].get("subordinated") == "true"

        if is_subordinate:
            if not remote_unit_data or remote_unit_data.get("state") != "ready":
                return

        repository = self.interface.repository(event.relation.id, event.app)
        response_model = self.interface.build_model(event.relation.id, component=event.app)

        if not response_model.requests:
            logger.info("Still waiting for data.")
            return

        data = repository.get_field("data")
        if not data:
            logger.info("Missing data to compute diffs")
            return

        request_map = TypeAdapter(dict[str, self._request_model]).validate_json(data)

        for response in response_model.requests:
            response_id = response.request_id or gen_hash(response.resource, response.salt)
            request = request_map.get(response_id, None)
            if not request:
                raise ValueError(f"No request matching the response with response_id {response_id}")
            self._handle_event(event, repository, request, response)

        self._handle_statuses(event, repository, data)

    def _handle_statuses(
        self, event: RelationChangedEvent, repository: OpsRelationRepository, data: str | None
    ):
        """Handles statuses for this event."""
        # Retrieve old statuses from "data"
        old_data = json.loads(data or "{}")
        old_statuses = old_data.get(STATUS_FIELD, {})
        previous_codes = {int(k) for k in old_statuses.keys()}

        # Compute current statuses
        current_statuses = json.loads(repository.get_field(STATUS_FIELD) or "[]")
        current_codes = {status.get("code") for status in current_statuses}

        # Detect changes
        raised = current_codes - previous_codes
        resolved = previous_codes - current_codes

        for status_code in raised:
            logger.debug(f"Status [{status_code}] raised")
            _status = next(s for s in current_statuses if s["code"] == status_code)
            _status_instance = RelationStatus(**_status)
            getattr(self.on, "status_raised").emit(
                event.relation,
                status=_status_instance,
                app=event.app,
                unit=event.unit,
            )

        for status_code in resolved:
            logger.debug(f"Status [{status_code}] resolved")
            # Because JSON keys are always string, we should convert the int code to str.
            _status = old_statuses[str(status_code)]
            _status_instance = RelationStatus(**_status)
            getattr(self.on, "status_resolved").emit(
                event.relation,
                status=_status_instance,
                app=event.app,
                unit=event.unit,
            )

        if not any([raised, resolved]):
            return

        # Store new state of the statuses in the "data" field
        new_data = get_encoded_dict(event.relation, self.component, "data") or {}
        store_new_data(
            relation=event.relation,
            component=self.component,
            new_data=new_data,
            short_uuid=None,
            global_data={
                STATUS_FIELD: {
                    code: status.model_dump()
                    for code, status in self.get_statuses(event.relation.id).items()
                }
            },
        )

    ##############################################################################
    # Methods to handle specificities of relation events
    ##############################################################################

    @override
    def _handle_event(
        self,
        event: RelationChangedEvent,
        repository: OpsRelationRepository,
        request: RequirerCommonModel,
        response: ResourceProviderModel,
    ):
        _diff = self.compute_diff(event.relation, response, repository, store=True)

        for newval in _diff.added:
            if secret_group := response._get_secret_field(newval):
                uri = getattr(response, newval.replace("-", "_"))
                repository.register_secret(uri, secret_group, response.request_id)

        if "secret-user" in _diff.added and not request.entity_type:
            logger.info(f"resource {response.resource} created at {datetime.now()}")
            getattr(self.on, "resource_created").emit(
                event.relation, app=event.app, unit=event.unit, response=response
            )
            self._emit_aliased_event(event, "resource_created", response)
            return

        if "secret-entity" in _diff.added and request.entity_type:
            logger.info(f"entity {response.entity_name} created at {datetime.now()}")
            getattr(self.on, "resource_entity_created").emit(
                event.relation, app=event.app, unit=event.unit, response=response
            )
            self._emit_aliased_event(event, "resource_entity_created", response)
            return

        if "endpoints" in _diff.added or "endpoints" in _diff.changed:
            logger.info(f"endpoints changed at {datetime.now()}")
            getattr(self.on, "endpoints_changed").emit(
                event.relation, app=event.app, unit=event.unit, response=response
            )
            self._emit_aliased_event(event, "endpoints_changed", response)
            return

        if "read-only-endpoints" in _diff.added or "read-only-endpoints" in _diff.changed:
            logger.info(f"read-only-endpoints changed at {datetime.now()}")
            getattr(self.on, "read_only_endpoints_changed").emit(
                event.relation, app=event.app, unit=event.unit, response=response
            )
            self._emit_aliased_event(event, "read_only_endpoints_changed", response)
            return

        if "secret-tls" in _diff.added or "secret-tls" in _diff.changed:
            logger.info(f"auth updated for {response.resource} at {datetime.now()}")
            getattr(self.on, "authentication_updated").emit(
                event.relation, app=event.app, unit=event.unit, response=response
            )
            self._emit_aliased_event(event, "authentication_updated", response)
            return
