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
"""Logic to compute diffs and modelling for diffs."""

import json
from typing import Any, NamedTuple

from ops.model import Application, Relation, Unit

from data_platform_helpers.interfaces.utils import RESOURCE_ALIASES


class Diff(NamedTuple):
    """A tuple for storing the diff between two data mappings.

    added - keys that were added
    changed - keys that still exist but have new values
    deleted - key that were deleted
    """

    added: set[str]
    changed: set[str]
    deleted: set[str]


def diff(old_data: dict[str, str] | None, new_data: dict[str, str]) -> Diff:
    """Retrieves the diff of the data in the relation changed databag for v1.

    Args:
        old_data: dictionary of the stored data before the event.
        new_data: dictionary of the received data to compute the diff.

    Returns:
        a Diff instance containing the added, deleted and changed
            keys from the event relation databag.
    """
    old_data = old_data or {}

    # These are the keys that were added to the databag and triggered this event.
    added = new_data.keys() - old_data.keys()
    # These are the keys that were removed from the databag and triggered this event.
    deleted = old_data.keys() - new_data.keys()
    # These are the keys that already existed in the databag,
    # but had their values changed.
    changed = {key for key in old_data.keys() & new_data.keys() if old_data[key] != new_data[key]}
    # Return the diff with all possible changes.
    return Diff(added, changed, deleted)


def resource_added(diff: Diff, aliases: list[str] | None = None) -> bool:
    """Ensures that one of the aliased resources has been added."""
    all_aliases = RESOURCE_ALIASES + ["resource"] + (aliases or [])
    return any(item in diff.added for item in all_aliases)


def store_new_data(
    relation: Relation,
    component: Unit | Application,
    new_data: dict[str, str],
    short_uuid: str | None = None,
    global_data: dict[str, Any] = {},
):
    """Stores the new data in the databag for diff computation.

    Args:
        relation: The relation considered to write data to
        component: The component databag to write data to
        new_data: a dictionary containing the data to write
        short_uuid: Only present in V1, the request-id of that data to write.
        global_data: request-independent, global state data to be written.
    """
    global_data = {k: v for k, v in global_data.items() if v}
    # First, the case for V0
    if not short_uuid:
        relation.data[component].update({"data": json.dumps(new_data | global_data)})
    # Then the case for V1, where we have a ShortUUID
    else:
        data = json.loads(relation.data[component].get("data", "{}")) | global_data
        if not isinstance(data, dict):
            raise ValueError
        data[short_uuid] = new_data
        relation.data[component].update({"data": json.dumps(data)})
