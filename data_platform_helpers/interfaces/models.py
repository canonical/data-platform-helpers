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
"""Data modelling."""

import copy
import json
from logging import getLogger
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    Tag,
    TypeAdapter,
    ValidationInfo,
    model_serializer,
    model_validator,
)
from pydantic.functional_validators import AfterValidator
from typing_extensions import Self

from data_platform_helpers.interfaces.errors import SecretError, SecretsUnavailableError
from data_platform_helpers.interfaces.repository import AbstractRepository
from data_platform_helpers.interfaces.types import (
    EntitySecretStr,
    ExtraSecretStr,
    MtlsSecretStr,
    OptionalSecretBool,
    OptionalSecrets,
    SecretGroup,
    SecretString,
    TlsSecretBool,
    TlsSecretStr,
    UserSecretStr,
)
from data_platform_helpers.interfaces.utils import RESOURCE_ALIASES, gen_hash, gen_salt

logger = getLogger(__name__)

SECRET_PREFIX = "secret-"


class PeerModel(BaseModel):
    """Common Model for all peer relations."""

    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        populate_by_name=True,
        serialize_by_alias=True,
        alias_generator=lambda x: x.replace("_", "-"),
        extra="allow",
    )

    @model_validator(mode="after")
    def extract_secrets(self, info: ValidationInfo):
        """Extract all secret_fields into their local field."""
        if not info.context or not isinstance(info.context.get("repository"), AbstractRepository):
            logger.debug("No secret parsing as we're lacking context here.")
            return self
        repository: AbstractRepository = info.context.get("repository")
        for field, field_info in self.__pydantic_fields__.items():
            if field_info.annotation in OptionalSecrets and len(field_info.metadata) == 1:
                secret_group = SecretGroup(field_info.metadata[0])
                if not secret_group:
                    raise SecretsUnavailableError(field)

                aliased_field = field_info.serialization_alias or field
                secret = repository.get_secret(secret_group, secret_uri=None)

                if not secret:
                    logger.info(f"No secret for group {secret_group}")
                    continue

                value = secret.get_content().get(aliased_field)
                if value and field_info.annotation == OptionalSecretBool:
                    value = json.loads(value)
                setattr(self, field, value)

        return self

    @model_serializer(mode="wrap")
    def serialize_model(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo):
        """Serializes the model writing the secrets in their respective secrets."""
        if not info.context or not isinstance(info.context.get("repository"), AbstractRepository):
            logger.debug("No secret parsing serialization as we're lacking context here.")
            return handler(self)
        repository: AbstractRepository = info.context.get("repository")

        for field, field_info in self.__pydantic_fields__.items():
            if field_info.annotation in OptionalSecrets and len(field_info.metadata) == 1:
                secret_group = SecretGroup(field_info.metadata[0])
                if not secret_group:
                    raise SecretsUnavailableError(field)

                aliased_field = field_info.serialization_alias or field
                secret = repository.get_secret(secret_group, secret_uri=None)

                value = getattr(self, field)

                if (value is not None) and not isinstance(value, str):
                    value = json.dumps(value)

                if secret is None:
                    if value:
                        secret = repository.add_secret(
                            aliased_field,
                            value,
                            secret_group,
                        )
                        if not secret or not secret.meta:
                            raise SecretError("No secret to send back")
                    continue

                content = secret.get_content()
                full_content = copy.deepcopy(content)

                if value is None:
                    full_content.pop(aliased_field, None)
                else:
                    full_content.update({aliased_field: value})
                secret.set_content(full_content)
        return handler(self)

    def __getitem__(self, key):
        """Dict like access to the model."""
        try:
            return getattr(self, key.replace("-", "_"))
        except Exception:
            raise KeyError(f"{key} is not present in the model")

    def __setitem__(self, key, value):
        """Dict like setter for the model."""
        return setattr(self, key.replace("-", "_"), value)

    def __delitem__(self, key):
        """Dict like deleter for the model."""
        try:
            return delattr(self, key.replace("-", "_"))
        except Exception:
            raise KeyError(f"{key} is not present in the model.")


class BaseCommonModel(BaseModel):
    """Embeds the logic of parsing and serializing."""

    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        populate_by_name=True,
        serialize_by_alias=True,
        alias_generator=lambda x: x.replace("_", "-"),
        extra="allow",
    )

    def update(self: Self, model: Self):
        """Updates a common Model with another one."""
        # Iterate on all the fields that where explicitly set.
        for item in model.model_fields_set:
            # ignore the outstanding fields.
            if item not in ["salt", "request_id"]:
                value = getattr(model, item)
                setattr(self, item, value)
        return self

    @model_validator(mode="after")
    def extract_secrets(self, info: ValidationInfo):
        """Extract all secret_fields into their local field."""
        if not info.context or not isinstance(info.context.get("repository"), AbstractRepository):
            logger.debug("No secret parsing as we're lacking context here.")
            return self
        repository: AbstractRepository = info.context.get("repository")
        short_uuid = self.short_uuid
        for field, field_info in self.__pydantic_fields__.items():
            if field_info.annotation in OptionalSecrets and len(field_info.metadata) == 1:
                secret_group = field_info.metadata[0]
                if not secret_group:
                    raise SecretsUnavailableError(field)

                aliased_field = field_info.serialization_alias or field
                secret_field = repository.secret_field(secret_group, aliased_field).replace(
                    "-", "_"
                )
                secret_uri: str | None = getattr(self, secret_field, None)

                if not secret_uri:
                    continue

                secret = repository.get_secret(
                    secret_group, secret_uri=secret_uri, short_uuid=short_uuid
                )

                if not secret:
                    logger.info(f"No secret for group {secret_group} and short uuid {short_uuid}")
                    continue

                value = secret.get_content().get(aliased_field)

                if value and field_info.annotation == OptionalSecretBool:
                    value = json.loads(value)

                setattr(self, field, value)

        return self

    @model_serializer(mode="wrap")
    def serialize_model(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo):  # noqa: C901
        """Serializes the model writing the secrets in their respective secrets."""
        if not info.context or not isinstance(info.context.get("repository"), AbstractRepository):
            logger.debug("No secret parsing serialization as we're lacking context here.")
            return handler(self)
        repository: AbstractRepository = info.context.get("repository")

        short_uuid = self.short_uuid
        # Backward compatibility for v0 regarding secrets.
        if info.context.get("version") == "v0":
            short_uuid = None

        for field, field_info in self.__pydantic_fields__.items():
            if field_info.annotation in OptionalSecrets and len(field_info.metadata) == 1:
                secret_group = field_info.metadata[0]
                if not secret_group:
                    raise SecretsUnavailableError(field)
                aliased_field = field_info.serialization_alias or field
                secret_field = repository.secret_field(secret_group, aliased_field).replace(
                    "-", "_"
                )
                secret_uri: str | None = getattr(self, secret_field, None)
                secret = repository.get_secret(
                    secret_group, secret_uri=secret_uri, short_uuid=short_uuid
                )

                value = getattr(self, field)

                if (value is not None) and not isinstance(value, str):
                    value = json.dumps(value)

                if secret is None:
                    if value:
                        secret = repository.add_secret(
                            aliased_field, value, secret_group, short_uuid
                        )
                        if not secret or not secret.meta:
                            raise SecretError("No secret to send back")
                        setattr(self, secret_field, secret.meta.id)
                    continue

                if secret and secret.meta and secret.meta.id:
                    # In case we lost the secret uri in the structure, let's add it back.
                    setattr(self, secret_field, secret.meta.id)

                content = secret.get_content()
                full_content = copy.deepcopy(content)

                if value is None:
                    full_content.pop(aliased_field, None)
                else:
                    full_content.update({aliased_field: value})
                secret.set_content(full_content)

                if not full_content:
                    # Setting a field to '' deletes it
                    setattr(self, secret_field, None)
                    repository.delete_secret(secret.label)

        return handler(self)

    @classmethod
    def _get_secret_field(cls, field: str) -> SecretGroup | None:
        """Checks if the field is a secret uri or not."""
        if not field.startswith(SECRET_PREFIX):
            return None

        value = field.split("-")[1]
        if info := cls.__pydantic_fields__.get(field.replace("-", "_")):
            if info.annotation == SecretString:
                return SecretGroup(value)
        return None

    @property
    def short_uuid(self) -> str | None:
        """The request id."""
        return None

    def __getitem__(self, key):
        """Dict like access to the model."""
        try:
            return getattr(self, key.replace("-", "_"))
        except Exception:
            raise KeyError(f"{key} is not present in the model")

    def __setitem__(self, key, value):
        """Dict like setter for the model."""
        return setattr(self, key.replace("-", "_"), value)

    def __delitem__(self, key):
        """Dict like deleter for the model."""
        try:
            return delattr(self, key.replace("-", "_"))
        except Exception:
            raise KeyError(f"{key} is not present in the model.")


class CommonModel(BaseCommonModel):
    """Common Model for both requirer and provider.

    request_id stores the request identifier for easier access.
    salt is used to create a valid request id.
    resource is the requested resource.
    """

    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        populate_by_name=True,
        serialize_by_alias=True,
        alias_generator=lambda x: x.replace("_", "-"),
        extra="allow",
    )

    resource: str = Field(validation_alias=AliasChoices(*RESOURCE_ALIASES), default="")
    request_id: str | None = Field(default=None)
    salt: str = Field(
        description="This salt is used to create unique hashes even when other fields map 1-1",
        default_factory=gen_salt,
    )

    @property
    def short_uuid(self) -> str | None:
        """The request id."""
        return self.request_id or gen_hash(self.resource, self.salt)


class EntityPermissionModel(BaseModel):
    """Entity Permissions Model."""

    resource_name: str
    resource_type: str
    privileges: list


class RequirerCommonModel(CommonModel):
    """Requirer side of the request model.

    extra_user_roles is used to request more roles for that user.
    external_node_connectivity is used to indicate that the URI is for external client.
    """

    extra_user_roles: str | None = Field(default=None)
    extra_group_roles: str | None = Field(default=None)
    external_node_connectivity: bool = Field(default=False)
    entity_type: Literal["USER", "GROUP"] | None = Field(default=None)
    entity_permissions: list[EntityPermissionModel] | None = Field(default=None)
    secret_mtls: SecretString | None = Field(default=None)
    mtls_cert: MtlsSecretStr = Field(default=None)

    @model_validator(mode="after")
    def validate_fields(self):
        """Validates that no inconsistent request is being sent."""
        if self.entity_type and self.entity_type not in ["USER", "GROUP"]:
            raise ValueError("Invalid entity-type. Possible values are USER and GROUP")

        if self.entity_type == "USER" and self.extra_group_roles:
            raise ValueError("Inconsistent entity information. Use extra_user_roles instead")

        if self.entity_type == "GROUP" and self.extra_user_roles:
            raise ValueError("Inconsistent entity information. Use extra_group_roles instead")

        return self


class ProviderCommonModel(CommonModel):
    """Serialized fields added to the databag.

    endpoints stores the endpoints exposed to that client.
    secret_user is a secret URI mapping to the user credentials
    secret_tls is a secret URI mapping to the TLS certificate
    secret_extra is a secret URI for all additional secrets requested.
    """

    endpoints: str | None = Field(default=None)
    read_only_endpoints: str | None = Field(default=None)
    secret_user: SecretString | None = Field(default=None)
    secret_tls: SecretString | None = Field(default=None)
    secret_extra: SecretString | None = Field(default=None)
    secret_entity: SecretString | None = Field(default=None)


class ResourceProviderModel(ProviderCommonModel):
    """Extended model including the deserialized fields."""

    username: UserSecretStr = Field(default=None)
    password: UserSecretStr = Field(default=None)
    uris: UserSecretStr = Field(default=None)
    read_only_uris: UserSecretStr = Field(default=None)
    tls: TlsSecretBool = Field(default=None)
    tls_ca: TlsSecretStr = Field(default=None)
    entity_name: EntitySecretStr = Field(default=None)
    entity_password: EntitySecretStr = Field(default=None)
    version: str | None = Field(default=None)


class RequirerDataContractV0(RequirerCommonModel):
    """Backward compatibility."""

    version: Literal["v0"] = Field(default="v0")

    original_field: str = Field(exclude=True, default="")

    @model_validator(mode="before")
    @classmethod
    def ensure_original_field(cls, data: Any):
        """Ensures that we keep the original field."""
        if isinstance(data, dict):
            for alias in RESOURCE_ALIASES:
                if data.get(alias) is not None:
                    data["original_field"] = alias
                    break
        else:
            for alias in RESOURCE_ALIASES:
                if getattr(data, alias) is not None:
                    data.original_field = alias
        return data


TResourceProviderModel = TypeVar("TResourceProviderModel", bound=ResourceProviderModel)
TRequirerCommonModel = TypeVar("TRequirerCommonModel", bound=RequirerCommonModel)


class RequirerDataContractV1(BaseModel, Generic[TRequirerCommonModel]):
    """The new Data Contract."""

    version: Literal["v1"] = Field(default="v1")
    requests: list[TRequirerCommonModel] = Field(default_factory=list)


def discriminate_on_version(payload: Any) -> str:
    """Use the version to discriminate."""
    if isinstance(payload, dict):
        return payload.get("version", "v0")
    return getattr(payload, "version", "v0")


RequirerDataContractType = Annotated[
    Annotated[RequirerDataContractV0, Tag("v0")] | Annotated[RequirerDataContractV1, Tag("v1")],
    Discriminator(discriminate_on_version),
]


RequirerDataContract: TypeAdapter[RequirerDataContractType] = TypeAdapter(RequirerDataContractType)


class DataContractV0(ResourceProviderModel):
    """The Data contract of the response, for V0."""


class DataContractV1(BaseModel, Generic[TResourceProviderModel]):
    """The Data contract of the response, for V1."""

    version: Literal["v1"] = Field(default="v1")
    requests: list[TResourceProviderModel] = Field(default_factory=list)


DataContract = TypeAdapter(DataContractV1[ResourceProviderModel])


TCommonModel = TypeVar("TCommonModel", bound=CommonModel)


def is_topic_value_acceptable(value: str | None) -> str | None:
    """Check whether the given Kafka topic value is acceptable."""
    if value and "*" in value[:3]:
        raise ValueError(f"Error on topic '{value}',, unacceptable value.")
    return value


class KafkaRequestModel(RequirerCommonModel):
    """Specialised model for Kafka."""

    consumer_group_prefix: Annotated[str | None, AfterValidator(is_topic_value_acceptable)] = Field(
        default=None
    )


class KafkaResponseModel(ResourceProviderModel):
    """Kafka response model."""

    consumer_group_prefix: ExtraSecretStr = Field(default=None)
    zookeeper_uris: ExtraSecretStr = Field(default=None)


class RelationStatus(BaseModel):
    """Base model for status propagation on charm relations."""

    code: int
    message: str
    resolution: str

    @property
    def is_informational(self) -> bool:
        """Is this an informational status?"""
        return self.code // 1000 == 1

    @property
    def is_transitory(self) -> bool:
        """Is this a transitory status?"""
        return self.code // 1000 == 4

    @property
    def is_fatal(self) -> bool:
        """Is this a fatal status, requiring removing the relation?"""
        return self.code // 1000 == 5
