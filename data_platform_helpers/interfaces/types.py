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
"""Types."""

from enum import Enum
from os import PathLike
from typing import (
    Annotated,
    NewType,
    TypeAlias,
    TypedDict,
)

from pydantic import Field
from typing_extensions import TypeAliasType

SecretGroup = NewType("SecretGroup", str)


SecretString = TypeAliasType("SecretString", Annotated[str, Field(pattern="secret:.*")])


OptionalSecretStr: TypeAlias = str | None
OptionalSecretBool: TypeAlias = bool | None

OptionalSecrets = (OptionalSecretStr, OptionalSecretBool)

OptionalPathLike = PathLike | str | None

UserSecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "user"]
TlsSecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "tls"]
TlsSecretBool = Annotated[OptionalSecretBool, Field(exclude=True, default=None), "tls"]
MtlsSecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "mtls"]
ExtraSecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "extra"]
EntitySecretStr = Annotated[OptionalSecretStr, Field(exclude=True, default=None), "entity"]


class Scope(Enum):
    """Peer relations scope."""

    APP = "app"
    UNIT = "unit"


class RelationStatusDict(TypedDict):
    """Base type for dict representation of `RelationStatus` dataclass."""

    code: int
    message: str
    resolution: str
