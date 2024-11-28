import re
from ipaddress import IPv4Address
from typing import Dict, List

from juju.unit import Unit
from pytest_operator.plugin import OpsTest


# TODO: this should be moved to a models definition module
class UnitExtension(Unit):
    """An extension to libjuju's Unit, adding some useful properties"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def from_unit(unit: Unit):
        return UnitExtension(entity_id=unit.entity_id, model=unit.model)

    @property
    def entity_type(self):
        return "unit"

    @property
    def id(self) -> int:
        return int(self.name.split("/")[-1])


class IntergrationHelpers:
    def __init__(self, ops_test: OpsTest):
        self.ops_test = ops_test

    def get_application_unit_names(self, app: str) -> List[str]:
        """Retrieves list of unit names for a given app."""
        if juju_app := self.ops_test.model.applications.get(app):
            return [unit.name for unit in juju_app.units]

        return []

    async def get_leader_unit(self, app: str) -> UnitExtension | None:
        """Retrieves the leader unit of a given app."""
        leader_unit = None
        if juju_app := self.ops_test.model.applications.get(app):
            for unit in juju_app.units:
                if await unit.is_leader_from_status():
                    leader_unit = UnitExtension.from_unit(unit)
                    break

        return leader_unit

    async def get_unit_ipv4_address(self, unit: Unit) -> IPv4Address | None:
        """A safer alternative for `juju.unit.get_public_address()` which is robust to network changes"""
        return_code, stdout, stderr = await self.ops_test.juju(
            "ssh", f"{unit.name}", "hostname -i"
        )
        ipv4_matches = re.findall(
            "[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", stdout
        )

        if ipv4_matches:
            return IPv4Address(ipv4_matches[0])

        return None

    async def get_application_unit_ipv4s(
        self, app: str
    ) -> Dict[str, IPv4Address | None]:
        """Returns a dict mapping of unit name to IPv4 address for a given app."""
        unit_ips = {}

        if juju_app := self.ops_test.model.applications.get(app):
            for unit in juju_app.units:
                unit_ips[unit.name] = await self.get_unit_ipv4_address(unit)

        return unit_ips
