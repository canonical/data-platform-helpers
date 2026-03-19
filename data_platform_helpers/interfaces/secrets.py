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
"""Secret + caching."""

from logging import getLogger

from ops import Model, Secret, SecretInfo
from ops.model import Application, ModelError, Relation, SecretNotFoundError, Unit

from data_platform_helpers.interfaces.errors import (
    SecretAlreadyExistsError,
    SecretsUnavailableError,
)

logger = getLogger(__name__)

MODEL_ERRORS = {
    "not_leader": "this unit is not the leader",
    "no_label_and_uri": "ERROR either URI or label should be used for getting an owned secret but not both",
    "owner_no_refresh": "ERROR secret owner cannot use --refresh",
    "permission_denied": "ERROR permission denied",
}


class CachedSecret:
    """Locally cache a secret.

    The data structure is precisely reusing/simulating as in the actual Secret Storage
    """

    KNOWN_MODEL_ERRORS = [
        MODEL_ERRORS["no_label_and_uri"],
        MODEL_ERRORS["owner_no_refresh"],
        MODEL_ERRORS["permission_denied"],
    ]

    def __init__(
        self,
        model: Model,
        component: Application | Unit,
        label: str,
        secret_uri: str | None = None,
    ):
        self._secret_meta: Secret | None = None
        self._secret_content: dict[str, str] = {}
        self._secret_uri = secret_uri
        self.label = label
        self._model = model
        self.component = component
        self.current_label = None

    @property
    def meta(self) -> Secret | None:
        """Getting cached secret meta-information."""
        if self._secret_meta:
            return self._secret_meta

        if not (self._secret_uri or self.label):
            return None

        try:
            self._secret_meta = self._model.get_secret(label=self.label)
        except SecretNotFoundError:
            # Falling back to seeking for potential legacy labels
            logger.debug(f"Secret with label {self.label} not found")
        except ModelError as err:
            if not any(msg in str(err) for msg in self.KNOWN_MODEL_ERRORS):
                raise

        # If still not found, to be checked by URI, to be labelled with the proposed label
        if not self._secret_meta and self._secret_uri:
            try:
                self._secret_meta = self._model.get_secret(id=self._secret_uri, label=self.label)
            except ModelError as err:
                if not any(msg in str(err) for msg in self.KNOWN_MODEL_ERRORS):
                    raise

        return self._secret_meta

    ##########################################################################
    # Public functions
    ##########################################################################

    def add_secret(
        self,
        content: dict[str, str],
        relation: Relation | None = None,
        label: str | None = None,
    ) -> Secret:
        """Create a new secret."""
        if self._secret_uri:
            raise SecretAlreadyExistsError(
                "Secret is already defined with uri %s", self._secret_uri
            )

        label = self.label if not label else label

        secret = self.component.add_secret(content, label=label)
        if relation and relation.app != self._model.app:
            # If it's not a peer relation, grant is to be applied
            secret.grant(relation)
        self._secret_uri = secret.id
        self._secret_meta = secret
        return self._secret_meta

    def get_content(self) -> dict[str, str]:
        """Getting cached secret content."""
        if not self._secret_content:
            if self.meta:
                try:
                    self._secret_content = self.meta.get_content(refresh=True)
                except (ValueError, ModelError) as err:
                    # https://bugs.launchpad.net/juju/+bug/2042596
                    # Only triggered when 'refresh' is set
                    if isinstance(err, ModelError) and not any(
                        msg in str(err) for msg in self.KNOWN_MODEL_ERRORS
                    ):
                        raise
                    # Due to: ValueError: Secret owner cannot use refresh=True
                    self._secret_content = self.meta.get_content()
        return self._secret_content

    def set_content(self, content: dict[str, str]) -> None:
        """Setting cached secret content."""
        if not self.meta:
            return

        if content == self.get_content():
            return

        if content:
            self.meta.set_content(content)
            self._secret_content = content
        else:
            self.meta.remove_all_revisions()

    def get_info(self) -> SecretInfo | None:
        """Passthrough the SecretCache to get the secret info."""
        if self.meta:
            return self.meta.get_info()
        return None

    def remove(self) -> None:
        """Remove secret."""
        if not self.meta:
            raise SecretsUnavailableError("Non-existent secret was attempted to be removed.")
        try:
            self.meta.remove_all_revisions()
        except SecretNotFoundError:
            pass
        self._secret_content = {}
        self._secret_meta = None
        self._secret_uri = None


class SecretCache:
    """A data structure storing CachedSecret objects."""

    def __init__(self, model: Model, component: Application | Unit):
        self._model = model
        self.component = component
        self._secrets: dict[str, CachedSecret] = {}

    def get(self, label: str, uri: str | None = None) -> CachedSecret | None:
        """Getting a secret from Juju Secret store or cache."""
        if not self._secrets.get(label):
            secret = CachedSecret(self._model, self.component, label, uri)
            if secret.meta:
                self._secrets[label] = secret
        return self._secrets.get(label)

    def add(self, label: str, content: dict[str, str], relation: Relation) -> CachedSecret:
        """Adding a secret to Juju Secret."""
        if self._secrets.get(label):
            raise SecretAlreadyExistsError(f"Secret {label} already exists")

        secret = CachedSecret(self._model, self.component, label)
        secret.add_secret(content, relation)
        self._secrets[label] = secret
        return self._secrets[label]

    def remove(self, label: str) -> None:
        """Remove a secret from the cache."""
        if secret := self.get(label):
            try:
                secret.remove()
                self._secrets.pop(label)
            except (SecretsUnavailableError, KeyError):
                pass
            else:
                return
        logger.debug("Non-existing Juju Secret was attempted to be removed %s", label)
