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
"""The repository implementations.

The repositories are used to get/set the data from a data source.
They are then used by the edge functions build_model and write_model to serialize/deserialize to
pydantic models.
"""

import copy
import json
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Any

from ops import Application, Model, Relation, Unit
from typing_extensions import override

from data_platform_helpers.interfaces.errors import SecretError
from data_platform_helpers.interfaces.secrets import CachedSecret, SecretCache
from data_platform_helpers.interfaces.types import Scope, SecretGroup
from data_platform_helpers.interfaces.utils import ensure_leader_for_app

logger = getLogger(__name__)


class AbstractRepository(ABC):
    """Abstract repository interface."""

    @abstractmethod
    def get_secret(
        self, secret_group, secret_uri: str | None, short_uuid: str | None = None
    ) -> CachedSecret | None:
        """Gets a secret from the secret cache by uri or label."""
        ...

    @abstractmethod
    def get_secret_field(
        self,
        field: str,
        secret_group: SecretGroup,
        short_uuid: str | None = None,
    ) -> str | None:
        """Gets a value for a field stored in a secret group."""
        ...

    @abstractmethod
    def get_field(self, field: str) -> str | None:
        """Gets the value for one field."""
        ...

    @abstractmethod
    def get_fields(self, *fields: str) -> dict[str, str | None]:
        """Gets the values for all provided fields."""
        ...

    @abstractmethod
    def write_field(self, field: str, value: Any) -> None:
        """Writes the value in the field, without any secret support."""
        ...

    @abstractmethod
    def write_fields(self, mapping: dict[str, Any]) -> None:
        """Writes the values of mapping in the fields without any secret support (keys of mapping)."""
        ...

    def write_secret_field(self, field: str, value: Any, group: SecretGroup) -> CachedSecret | None:
        """Writes a secret field."""
        ...

    @abstractmethod
    def add_secret(
        self,
        field: str,
        value: Any,
        secret_group: SecretGroup,
        short_uuid: str | None = None,
    ) -> CachedSecret | None:
        """Gets a value for a field stored in a secret group."""
        ...

    @abstractmethod
    def delete_secret(self, label: str):
        """Deletes a secret by its label."""
        ...

    @abstractmethod
    def delete_field(self, field: str) -> None:
        """Deletes a field."""
        ...

    @abstractmethod
    def delete_fields(self, *fields: str) -> None:
        """Deletes all the provided fields."""
        ...

    @abstractmethod
    def delete_secret_field(self, field: str, secret_group: SecretGroup) -> None:
        """Delete a field stored in a secret group."""
        ...

    @abstractmethod
    def register_secret(self, secret_group: SecretGroup, short_uuid: str | None = None) -> None:
        """Registers a secret using the repository."""
        ...

    @abstractmethod
    def get_data(self) -> dict[str, Any] | None:
        """Gets the whole data."""
        ...

    @abstractmethod
    def secret_field(self, secret_group: SecretGroup, field: str | None = None) -> str:
        """Builds a secret field."""


class OpsRepository(AbstractRepository):
    """Implementation for ops repositories, with some methods left out."""

    SECRET_FIELD_NAME: str

    uri_to_databag: bool = True

    def __init__(
        self,
        model: Model,
        relation: Relation | None,
        component: Unit | Application,
    ):
        self._local_app = model.app
        self._local_unit = model.unit
        self.relation = relation
        self.component = component
        self.model = model
        self.secrets = SecretCache(model, component)

    @abstractmethod
    def _generate_secret_label(
        self, relation: Relation, secret_group: SecretGroup, short_uuid: str | None = None
    ) -> str:
        """Generate unique group mapping for secrets within a relation context."""
        ...

    @override
    def get_data(self) -> dict[str, Any] | None:
        ret: dict[str, Any] = {}
        if not self.relation:
            logger.info("No relation to get value from")
            return None
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return None

        for key, value in self.relation.data[self.component].items():
            try:
                ret[key] = json.loads(value)
            except json.JSONDecodeError:
                ret[key] = value

        return ret

    @override
    @ensure_leader_for_app
    def get_field(
        self,
        field: str,
    ) -> str | None:
        if not self.relation:
            logger.info("No relation to get value from")
            return None
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return None
        relation_data = self.relation.data[self.component]
        return relation_data.get(field)

    @override
    @ensure_leader_for_app
    def get_fields(self, *fields: str) -> dict[str, str]:
        res = {}
        for field in fields:
            if (value := self.get_field(field)) is not None:
                res[field] = value
        return res

    @override
    @ensure_leader_for_app
    def write_field(self, field: str, value: Any) -> None:
        if not self.relation:
            logger.info("No relation to get value from")
            return
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return
        if not value:
            return
        self.relation.data[self.component].update({field: value})

    @override
    @ensure_leader_for_app
    def write_fields(self, mapping: dict[str, Any]) -> None:
        if not self.relation:
            logger.info("No relation to get value from")
            return
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return
        (self.write_field(field, value) for field, value in mapping.items())

    @override
    @ensure_leader_for_app
    def write_secret_field(
        self, field: str, value: Any, secret_group: SecretGroup
    ) -> CachedSecret | None:
        if not self.relation:
            logger.info("No relation to get value from")
            return None
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return None

        label = self._generate_secret_label(self.relation, secret_group)
        secret_uri = self.get_field(self.secret_field(secret_group, field))

        secret = self.secrets.get(label=label, uri=secret_uri)
        if not secret:
            return self.add_secret(field, value, secret_group)
        content = secret.get_content()
        full_content = copy.deepcopy(content)
        full_content.update({field: value})
        secret.set_content(full_content)
        return secret

    @override
    @ensure_leader_for_app
    def delete_field(self, field: str) -> None:
        if not self.relation:
            logger.info("No relation to get value from")
            return
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return
        relation_data = self.relation.data[self.component]
        try:
            relation_data.pop(field)
        except KeyError:
            logger.debug(
                f"Non existent field {field} was attempted to be removed from the databag (relation ID: {self.relation.id})"
            )

    @override
    @ensure_leader_for_app
    def delete_fields(self, *fields: str) -> None:
        (self.delete_field(field) for field in fields)

    @override
    @ensure_leader_for_app
    def delete_secret_field(self, field: str, secret_group: SecretGroup) -> None:
        if not self.relation:
            logger.info("No relation to get value from")
            return
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return

        relation_data = self.relation.data[self.component]
        secret_field = self.secret_field(secret_group, field)

        label = self._generate_secret_label(self.relation, secret_group)
        secret_uri = relation_data.get(secret_field)

        secret = self.secrets.get(label=label, uri=secret_uri)

        if not secret:
            logger.error(f"Can't delete secret for relation {self.relation.id}")
            return

        content = secret.get_content()
        new_content = copy.deepcopy(content)
        try:
            new_content.pop(field)
        except KeyError:
            logger.debug(
                f"Non-existing secret '{field}' was attempted to be removed"
                f"from relation {self.relation.id} and group {secret_group}"
            )

        # Write the new secret content if necessary
        if new_content:
            secret.set_content(new_content)
            return

        # Remove the secret from the relation if it's fully gone.
        try:
            relation_data.pop(field)
        except KeyError:
            pass
        self.secrets.remove(label)
        return

    @ensure_leader_for_app
    def register_secret(self, uri: str, secret_group: SecretGroup, short_uuid: str | None = None):
        """Registers the secret group for this relation.

        [MAGIC HERE]
        If we fetch a secret using get_secret(id=<ID>, label=<arbitraty_label>),
        then <arbitraty_label> will be "stuck" on the Secret object, whenever it may
        appear (i.e. as an event attribute, or fetched manually) on future occasions.

        This will allow us to uniquely identify the secret on Provider side (typically on
        'secret-changed' events), and map it to the corresponding relation.
        """
        if not self.relation:
            raise ValueError("Cannot register without relation.")

        label = self._generate_secret_label(self.relation, secret_group, short_uuid=short_uuid)
        CachedSecret(self.model, self.component, label, uri).meta

    @override
    def get_secret(
        self, secret_group, secret_uri: str | None, short_uuid: str | None = None
    ) -> CachedSecret | None:
        """Gets a secret from the secret cache by uri or label."""
        if not self.relation:
            logger.info("No relation to get value from")
            return None
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return None

        label = self._generate_secret_label(self.relation, secret_group, short_uuid=short_uuid)

        return self.secrets.get(label=label, uri=secret_uri)

    @override
    def get_secret_field(
        self,
        field: str,
        secret_group: SecretGroup,
        uri: str | None = None,
        short_uuid: str | None = None,
    ) -> str | None:
        """Gets a value for a field stored in a secret group."""
        if not self.relation:
            logger.info("No relation to get value from")
            return None
        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return None

        secret_field = self.secret_field(secret_group, field)

        relation_data = self.relation.data[self.component]
        secret_uri = uri or relation_data.get(secret_field)
        label = self._generate_secret_label(self.relation, secret_group, short_uuid=short_uuid)

        if self.uri_to_databag and not secret_uri:
            logger.info(f"No secret for group {secret_group} in relation {self.relation}")
            return None

        secret = self.secrets.get(label=label, uri=secret_uri)

        if not secret:
            logger.info(f"No secret for group {secret_group} in relation {self.relation}")
            return None

        content = secret.get_content().get(field)

        if not content:
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    @override
    @ensure_leader_for_app
    def add_secret(
        self,
        field: str,
        value: Any,
        secret_group: SecretGroup,
        short_uuid: str | None = None,
    ) -> CachedSecret | None:
        if not self.relation:
            logger.info("No relation to get value from")
            return None

        if self.component not in self.relation.data:
            logger.info(f"Component {self.component} not in relation {self.relation}")
            return None

        label = self._generate_secret_label(self.relation, secret_group, short_uuid)

        secret = self.secrets.add(label, {field: value}, self.relation)

        if not secret.meta or not secret.meta.id:
            logger.error("Secret is missing Secret ID")
            raise SecretError("Secret added but is missing Secret ID")

        return secret

    @override
    @ensure_leader_for_app
    def delete_secret(self, label: str) -> None:
        self.secrets.remove(label)


class OpsRelationRepository(OpsRepository):
    """Implementation of the Abstract Repository for non peer relations."""

    SECRET_FIELD_NAME: str = "secret"

    @override
    def _generate_secret_label(
        self, relation: Relation, secret_group: SecretGroup, short_uuid: str | None = None
    ) -> str:
        """Generate unique group_mappings for secrets within a relation context."""
        if short_uuid:
            return f"{relation.name}.{relation.id}.{short_uuid}.{secret_group}.secret"
        return f"{relation.name}.{relation.id}.{secret_group}.secret"

    def secret_field(self, secret_group: SecretGroup, field: str | None = None) -> str:
        """Generates the field name to store in the peer relation."""
        return f"{self.SECRET_FIELD_NAME}-{secret_group}"

    @ensure_leader_for_app
    @override
    def get_data(self) -> dict[str, Any] | None:
        return super().get_data()


class OpsPeerRepository(OpsRepository):
    """Implementation of the Ops Repository for peer relations."""

    SECRET_FIELD_NAME = "internal_secret"

    uri_to_databag: bool = False

    @property
    def scope(self) -> Scope:
        """Returns a scope."""
        if isinstance(self.component, Application):
            return Scope.APP
        if isinstance(self.component, Unit):
            return Scope.UNIT
        raise ValueError("Invalid component, neither a Unit nor an Application")

    @override
    def _generate_secret_label(
        self, relation: Relation, secret_group: SecretGroup, short_uuid: str | None = None
    ) -> str:
        """Generate unique group_mappings for secrets within a relation context."""
        members = [relation.name, self._local_app.name, self.scope.value]

        if secret_group != SecretGroup("extra"):
            members.append(secret_group)
        return f"{'.'.join(members)}"

    def secret_field(self, secret_group: SecretGroup, field: str | None = None) -> str:
        """Generates the field name to store in the peer relation."""
        if not field:
            raise ValueError("Must have a field.")
        return f"{field}@{secret_group}"


class OpsPeerUnitRepository(OpsPeerRepository):
    """Implementation for a unit."""

    @override
    def __init__(self, model: Model, relation: Relation | None, component: Unit):
        super().__init__(model, relation, component)


class OpsOtherPeerUnitRepository(OpsPeerRepository):
    """Implementation for a remote unit."""

    @override
    def __init__(self, model: Model, relation: Relation | None, component: Unit):
        if component == model.unit:
            raise ValueError(f"Can't instantiate {self.__class__.__name__} with local unit.")
        super().__init__(model, relation, component)

    @override
    def write_field(self, field: str, value: Any) -> None:
        raise NotImplementedError("It's not possible to update data of another unit.")

    @override
    def write_fields(self, mapping: dict[str, Any]) -> None:
        raise NotImplementedError("It's not possible to update data of another unit.")

    @override
    def add_secret(
        self, field: str, value: Any, secret_group: SecretGroup, short_uuid: str | None = None
    ) -> CachedSecret | None:
        raise NotImplementedError("It's not possible to update data of another unit.")

    @override
    def delete_field(self, field: str) -> None:
        raise NotImplementedError("It's not possible to update data of another unit.")

    @override
    def delete_fields(self, *fields: str) -> None:
        raise NotImplementedError("It's not possible to update data of another unit.")

    @override
    def delete_secret_field(self, field: str, secret_group: SecretGroup) -> None:
        raise NotImplementedError("It's not possible to update data of another unit.")
