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
"""The repository interfaces.

Those interfaces build the link between a relation, its component, a repository and its model.
It helps bring a more object oriented interface that is used by event handlers (for example).
"""

from __future__ import annotations

import json
from typing import Generic, TypeVar, overload

from ops import Application, Model, Relation, Unit
from pydantic import BaseModel, TypeAdapter

from data_platform_helpers.interfaces.models import PeerModel
from data_platform_helpers.interfaces.repository import (
    AbstractRepository,
    OpsOtherPeerUnitRepository,
    OpsPeerRepository,
    OpsPeerUnitRepository,
    OpsRelationRepository,
    OpsRepository,
)

TRepository = TypeVar("TRepository", bound=OpsRepository)
TCommon = TypeVar("TCommon", bound=BaseModel)
TPeerCommon = TypeVar("TPeerCommon", bound=PeerModel)
TCommonBis = TypeVar("TCommonBis", bound=BaseModel)


class RepositoryInterface(Generic[TRepository, TCommon]):
    """Repository builder."""

    def __init__(
        self,
        model: Model,
        relation_name: str,
        component: Unit | Application,
        repository_type: type[TRepository],
        data_model: type[TCommon] | TypeAdapter | None,
    ):
        self._model = model
        self.repository_type = repository_type
        self.relation_name = relation_name
        self.model = data_model
        self.component = component

    @property
    def relations(self) -> list[Relation]:
        """The list of Relation instances associated with this relation name."""
        return self._model.relations[self.relation_name]

    def repository(
        self, relation_id: int, component: Unit | Application | None = None
    ) -> TRepository:
        """Returns a repository for the relation."""
        relation = self._model.get_relation(self.relation_name, relation_id)
        if not relation:
            raise ValueError("Missing relation.")
        return self.repository_type(self._model, relation, component or self.component)

    @overload
    def build_model(
        self,
        relation_id: int,
        model: type[TCommon],
        component: Unit | Application | None = None,
    ) -> TCommon: ...

    @overload
    def build_model(
        self,
        relation_id: int,
        model: type[TCommonBis],
        component: Unit | Application | None = None,
    ) -> TCommonBis: ...

    @overload
    def build_model(
        self,
        relation_id: int,
        model: TypeAdapter[TCommonBis],
        component: Unit | Application | None = None,
    ) -> TCommonBis: ...

    @overload
    def build_model(
        self,
        relation_id: int,
        model: None = None,
        component: Unit | Application | None = None,
    ) -> TCommon: ...

    def build_model(
        self,
        relation_id: int,
        model: type[TCommon]
        | type[TCommonBis]
        | TypeAdapter[TCommonBis]
        | TypeAdapter[TCommon]
        | None = None,
        component: Unit | Application | None = None,
    ) -> TCommon | TCommonBis:
        """Builds a model using the repository for that relation."""
        model = model or self.model  # First the provided model (allows for specialisation)
        component = component or self.component
        if not model:
            raise ValueError("Missing model to specialise data")
        relation = self._model.get_relation(self.relation_name, relation_id)
        if not relation:
            raise ValueError("Missing relation.")
        return build_model(self.repository_type(self._model, relation, component), model)

    def write_model(
        self, relation_id: int, model: BaseModel, context: dict[str, str] | None = None
    ):
        """Writes the model using the repository."""
        relation = self._model.get_relation(self.relation_name, relation_id)
        if not relation:
            raise ValueError("Missing relation.")

        write_model(
            self.repository_type(self._model, relation, self.component), model, context=context
        )


class OpsRelationRepositoryInterface(RepositoryInterface[OpsRelationRepository, TCommon]):
    """Specialised Interface to build repositories for app peer relations."""

    def __init__(
        self,
        model: Model,
        relation_name: str,
        data_model: type[TCommon] | TypeAdapter | None = None,
    ):
        super().__init__(model, relation_name, model.app, OpsRelationRepository, data_model)


class OpsPeerRepositoryInterface(RepositoryInterface[OpsPeerRepository, TPeerCommon]):
    """Specialised Interface to build repositories for app peer relations."""

    def __init__(
        self,
        model: Model,
        relation_name: str,
        data_model: type[TPeerCommon] | TypeAdapter | None = None,
    ):
        super().__init__(model, relation_name, model.app, OpsPeerRepository, data_model)


class OpsPeerUnitRepositoryInterface(RepositoryInterface[OpsPeerUnitRepository, TPeerCommon]):
    """Specialised Interface to build repositories for this unit peer relations."""

    def __init__(
        self,
        model: Model,
        relation_name: str,
        data_model: type[TPeerCommon] | TypeAdapter | None = None,
    ):
        super().__init__(model, relation_name, model.unit, OpsPeerUnitRepository, data_model)


class OpsOtherPeerUnitRepositoryInterface(
    RepositoryInterface[OpsOtherPeerUnitRepository, TPeerCommon]
):
    """Specialised Interface to build repositories for another unit peer relations."""

    def __init__(
        self,
        model: Model,
        relation_name: str,
        unit: Unit,
        data_model: type[TPeerCommon] | TypeAdapter | None = None,
    ):
        super().__init__(model, relation_name, unit, OpsOtherPeerUnitRepository, data_model)


def build_model(
    repository: AbstractRepository,
    model: type[TCommon] | TypeAdapter[TCommon] | type[TCommonBis] | TypeAdapter[TCommonBis],
) -> TCommon | TCommonBis:
    """Builds a common model using the provided repository and provided model structure."""
    data = repository.get_data() or {}

    data.pop("data", None)

    # Beware this means all fields should have a default value here.
    if isinstance(model, TypeAdapter):
        return model.validate_python(data, context={"repository": repository})

    return model.model_validate(data, context={"repository": repository})


def write_model(
    repository: AbstractRepository, model: BaseModel, context: dict[str, str] | None = None
):
    """Writes the data stored in the model using the repository object."""
    context = context or {}
    dumped = model.model_dump(
        mode="json", context={"repository": repository} | context, exclude_none=False
    )
    for field, value in dumped.items():
        if value is None:
            repository.delete_field(field)
            continue
        dumped_value = value if isinstance(value, str) else json.dumps(value)
        repository.write_field(field, dumped_value)
