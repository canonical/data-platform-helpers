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
r"""Library to manage the relation for the data-platform products.

This V1 has been specified in
https://docs.google.com/document/d/1lnuonWnoQb36RWYwfHOBwU0VClLbawpTISXIC_yNKYo,
and should be backward compatible with v0 clients.

This library contains the Requires and Provides classes for handling the relation
between an application and multiple managed application supported by the data-team:
MySQL, Postgresql, MongoDB, Redis, Kafka, and Karapace.

#### Models

This library exposes basic default models that can be used in most cases.
If you need more complex models, you can subclass them.

```python
from data_platform_helpers.interfaces import RequirerCommonModel, ExtraSecretStr

class ExtendedCommonModel(RequirerCommonModel):
    operator_password: ExtraSecretStr
```

Secret groups are handled using annotated types.
If you wish to add extra secret groups, please follow the following model.
The string metadata represents the secret group name, and `OptionalSecretStr` is a TypeAlias for
`SecretStr | None`. Finally, `SecretStr` represents a field validating the URI pattern `secret:.*`

```python
MyGroupSecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "mygroup"]
```

Fields not specified as OptionalSecretStr and extended with a group name in the metadata will NOT
get serialised.


#### Requirer Charm

This library is a uniform interface to a selection of common database
metadata, with added custom events that add convenience to database management,
and methods to consume the application related data.


```python
from data_platform_helpers.interfaces import (
    RequirerCommonModel,
    RequirerDataContractV1,
    ResourceCreatedEvent,
    ResourceEntityCreatedEvent,
    ResourceProviderModel,
    ResourceRequirerEventHandler,
)

class ClientCharm(CharmBase):
    # Database charm that accepts connections from application charms.
    def __init__(self, *args) -> None:
        super().__init__(*args)

        requests = [
            RequirerCommonModel(
                resource="clientdb",
            ),
            RequirerCommonModel(
                resource="clientbis",
            ),
            RequirerCommonModel(
                entity_type="USER",
            )
        ]
        self.database = ResourceRequirerEventHandler(
            self,"database", requests, response_model=ResourceProviderModel
        )
        self.framework.observe(self.database.on.resource_created, self._on_resource_created)
        self.framework.observe(self.database.on.resource_entity_created, self._on_entity_created)

    def _on_resource_created(self, event: ResourceCreatedEvent) -> None:
        # Event triggered when a new database is created.
        relation_id = event.relation.id
        response = event.response # This is the response model

        username = event.response.username
        password = event.response.password
        ...

    def _on_entity_created(self, event: ResourceCreatedEvent) -> None:
        # Event triggered when a new entity is created.
        ...

Compared to V0, this library makes heavy use of pydantic models, and allows for
multiple requests, specified as a list.
On the Requirer side, each response will trigger one custom event for that response.
This way, it allows for more strategic events to be emitted according to the request.

As show above, the library provides some custom events to handle specific situations,
which are listed below:
-  resource_created: event emitted when the requested database is created.
-  resource_entity_created: event emitted when the requested entity is created.
-  endpoints_changed: event emitted when the read/write endpoints of the database have changed.
-  read_only_endpoints_changed: event emitted when the read-only endpoints of the database
  have changed. Event is not triggered if read/write endpoints changed too.

If it is needed to connect multiple database clusters to the same relation endpoint
the application charm can implement the same code as if it would connect to only
one database cluster (like the above code example).

To differentiate multiple clusters connected to the same relation endpoint
the application charm can use the name of the remote application:

```python

def _on_resource_created(self, event: ResourceCreatedEvent) -> None:
    # Get the remote app name of the cluster that triggered this event
    cluster = event.relation.app.name
```

It is also possible to provide an alias for each different database cluster/relation.

So, it is possible to differentiate the clusters in two ways.
The first is to use the remote application name, i.e., `event.relation.app.name`, as above.

The second way is to use different event handlers to handle each cluster events.
The implementation would be something like the following code:

```python

from data_platform_helpers.interfaces import (
    RequirerCommonModel,
    RequirerDataContractV1,
    ResourceCreatedEvent,
    ResourceEntityCreatedEvent,
    ResourceProviderModel,
    ResourceRequirerEventHandler,
)

class ApplicationCharm(CharmBase):
    # Application charm that connects to database charms.

    def __init__(self, *args):
        super().__init__(*args)

        requests = [
            RequirerCommonModel(
                resource="clientdb",
            ),
            RequirerCommonModel(
                resource="clientbis",
            ),
        ]
        # Define the cluster aliases and one handler for each cluster database created event.
        self.database = ResourceRequirerEventHandler(
            self,
            relation_name="database"
            relations_aliases = ["cluster1", "cluster2"],
            requests=
        )
        self.framework.observe(
            self.database.on.cluster1_resource_created, self._on_cluster1_resource_created
        )
        self.framework.observe(
            self.database.on.cluster2_resource_created, self._on_cluster2_resource_created
        )

    def _on_cluster1_resource_created(self, event: ResourceCreatedEvent) -> None:
        # Handle the created database on the cluster named cluster1

        # Create configuration file for app
        config_file = self._render_app_config_file(
            event.response.username,
            event.response.password,
            event.response.endpoints,
        )
        ...

    def _on_cluster2_resource_created(self, event: ResourceCreatedEvent) -> None:
        # Handle the created database on the cluster named cluster2

        # Create configuration file for app
        config_file = self._render_app_config_file(
            event.response.username,
            event.response.password,
            event.response.endpoints,
        )
        ...
```

### Provider Charm

Following an example of using the ResourceRequestedEvent, in the context of the
database charm code:

```python
from data_platform_helpers.interfaces import (
    ResourceProviderEventHandler,
    ResourceProviderModel,
    ResourceRequestedEvent,
    RequirerCommonModel,
)

class SampleCharm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        # Charm events defined in the database provides charm library.
        self.provided_database = ResourceProviderEventHandler(self, "database", RequirerCommonModel)
        self.framework.observe(self.provided_database.on.resource_requested,
            self._on_resource_requested)
        # Database generic helper
        self.database = DatabaseHelper()

    def _on_resource_requested(self, event: ResourceRequestedEvent) -> None:
        # Handle the event triggered by a new database requested in the relation
        # Retrieve the database name using the charm library.
        db_name = event.request.resource
        # generate a new user credential
        username = self.database.generate_user(event.request.request_id)
        password = self.database.generate_password(event.request.request_id)
        # set the credentials for the relation
        response = ResourceProviderModel(
            salt=event.request.salt,
            request_id=event.request.request_id,
            resource=db_name,
            username=username,
            password=password,
            ...
        )
        self.provided_database.set_response(event.relation.id, response)
```

As shown above, the library provides a custom event (resource_requested) to handle
the situation when an application charm requests a new database to be created.
It's preferred to subscribe to this event instead of relation changed event to avoid
creating a new database when other information other than a database name is
exchanged in the relation databag.

"""

from .diff import (
    Diff,
    diff,
    resource_added,
    store_new_data,
)
from .errors import (
    DataInterfacesError,
    IllegalOperationError,
    SecretAlreadyExistsError,
    SecretError,
    SecretsUnavailableError,
)
from .events import (
    AuthenticationUpdatedEvent,
    BulkResourcesRequestedEvent,
    MtlsCertUpdatedEvent,
    ResourceCreatedEvent,
    ResourceEndpointsChangedEvent,
    ResourceEntityCreatedEvent,
    ResourceEntityPermissionsChangedEvent,
    ResourceEntityRequestedEvent,
    ResourceProviderEvent,
    ResourceProvidesEvents,
    ResourceReadOnlyEndpointsChangedEvent,
    ResourceRequestedEvent,
    ResourceRequirerEvent,
    ResourceRequiresEvents,
    StatusEventBase,
    StatusRaisedEvent,
    StatusResolvedEvent,
)
from .handlers import (
    EventHandlers,
    ResourceProviderEventHandler,
    ResourceRequirerEventHandler,
)
from .models import (
    SECRET_PREFIX,
    BaseCommonModel,
    CommonModel,
    DataContract,
    DataContractV0,
    DataContractV1,
    EntityPermissionModel,
    KafkaRequestModel,
    KafkaResponseModel,
    PeerModel,
    ProviderCommonModel,
    RelationStatus,
    RequirerCommonModel,
    RequirerDataContract,
    RequirerDataContractType,
    RequirerDataContractV0,
    RequirerDataContractV1,
    ResourceProviderModel,
)
from .repository import (
    AbstractRepository,
    OpsOtherPeerUnitRepository,
    OpsPeerRepository,
    OpsPeerUnitRepository,
    OpsRelationRepository,
    OpsRepository,
)
from .repository_interfaces import (
    OpsOtherPeerUnitRepositoryInterface,
    OpsPeerRepositoryInterface,
    OpsPeerUnitRepositoryInterface,
    OpsRelationRepositoryInterface,
    RepositoryInterface,
    build_model,
    write_model,
)
from .secrets import (
    CachedSecret,
    SecretCache,
)
from .types import (
    EntitySecretStr,
    ExtraSecretStr,
    MtlsSecretStr,
    OptionalPathLike,
    OptionalSecretBool,
    OptionalSecrets,
    OptionalSecretStr,
    RelationStatusDict,
    Scope,
    SecretGroup,
    SecretString,
    TlsSecretBool,
    TlsSecretStr,
    UserSecretStr,
)
from .utils import (
    ensure_leader_for_app,
    gen_hash,
    gen_salt,
    get_encoded_dict,
)

__all__ = [
    "Diff",
    "diff",
    "resource_added",
    "store_new_data",
    "DataInterfacesError",
    "IllegalOperationError",
    "SecretAlreadyExistsError",
    "SecretError",
    "SecretsUnavailableError",
    "AuthenticationUpdatedEvent",
    "BulkResourcesRequestedEvent",
    "MtlsCertUpdatedEvent",
    "ResourceCreatedEvent",
    "ResourceEndpointsChangedEvent",
    "ResourceEntityCreatedEvent",
    "ResourceEntityPermissionsChangedEvent",
    "ResourceEntityRequestedEvent",
    "ResourceProviderEvent",
    "ResourceProvidesEvents",
    "ResourceReadOnlyEndpointsChangedEvent",
    "ResourceRequestedEvent",
    "ResourceRequirerEvent",
    "ResourceRequiresEvents",
    "StatusEventBase",
    "StatusRaisedEvent",
    "StatusResolvedEvent",
    "EventHandlers",
    "ResourceProviderEventHandler",
    "ResourceRequirerEventHandler",
    "BaseCommonModel",
    "CommonModel",
    "DataContract",
    "DataContractV0",
    "DataContractV1",
    "EntityPermissionModel",
    "KafkaRequestModel",
    "KafkaResponseModel",
    "PeerModel",
    "ProviderCommonModel",
    "RelationStatus",
    "RequirerCommonModel",
    "RequirerDataContract",
    "RequirerDataContractType",
    "RequirerDataContractV0",
    "RequirerDataContractV1",
    "ResourceProviderModel",
    "AbstractRepository",
    "OpsOtherPeerUnitRepository",
    "OpsPeerRepository",
    "OpsPeerUnitRepository",
    "OpsRelationRepository",
    "OpsRepository",
    "OpsOtherPeerUnitRepositoryInterface",
    "OpsPeerRepositoryInterface",
    "OpsPeerUnitRepositoryInterface",
    "OpsRelationRepositoryInterface",
    "RepositoryInterface",
    "build_model",
    "write_model",
    "EntitySecretStr",
    "ExtraSecretStr",
    "MtlsSecretStr",
    "OptionalPathLike",
    "OptionalSecretBool",
    "OptionalSecrets",
    "OptionalSecretStr",
    "RelationStatusDict",
    "Scope",
    "SecretGroup",
    "SecretString",
    "TlsSecretBool",
    "TlsSecretStr",
    "UserSecretStr",
    "ensure_leader_for_app",
    "gen_hash",
    "gen_salt",
    "get_encoded_dict",
    "CachedSecret",
    "SecretCache",
    "SECRET_PREFIX",
]
