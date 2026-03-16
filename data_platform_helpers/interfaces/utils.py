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
"""Utilitary functions."""

import hashlib
import json
import random
import string
from logging import getLogger
from typing import Any

from ops.model import Application, Relation, Unit

logger = getLogger(__name__)

RESOURCE_ALIASES = [
    "database",
    "subject",
    "topic",
    "index",
    "plugin-url",
    "prefix",
]


def gen_salt() -> str:
    """Generates a consistent salt."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def gen_hash(resource_name: str, salt: str) -> str:
    """Generates a consistent hash based on the resource name and salt."""
    hasher = hashlib.sha256()
    hasher.update(f"{resource_name}:{salt}".encode())
    return hasher.hexdigest()[:16]


def ensure_leader_for_app(f):
    """Decorator to ensure that only leader can perform given operation."""

    def wrapper(self, *args, **kwargs):
        if self.component == self._local_app and not self._local_unit.is_leader():
            logger.error(f"This operation ({f.__name__}) can only be performed by the leader unit")
            return None
        return f(self, *args, **kwargs)

    return wrapper


def get_encoded_dict(
    relation: Relation, member: Unit | Application, field: str
) -> dict[str, Any] | None:
    """Retrieve and decode an encoded field from relation data."""
    data = json.loads(relation.data[member].get(field, "{}"))
    if isinstance(data, dict):
        return data
    logger.error("Unexpected datatype for %s instead of dict.", str(data))
    return None
