# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
from pytest_operator.plugin import OpsTest
import tenacity
import yaml


def cut_network_from_unit_with_ip_change(machine_name: str) -> None:
    """Cut network from a lxc container in a way the changes the IP.

    Args:
        machine_name: lxc container hostname
    """
    # apply a mask (device type `none`)
    cut_network_command = f"lxc config device add {machine_name} eth0 none"
    subprocess.check_call(cut_network_command.split())


async def cut_network_from_unit_without_ip_change(ops_test: OpsTest, machine_name: str) -> None:
    """Cut network from a lxc container (without causing the change of the unit IP address)."""

    override_command = f"lxc config device override {machine_name} eth0"
    try:
        subprocess.check_call(override_command.split())
    except subprocess.CalledProcessError:
        # Ignore if the interface was already overridden.
        pass

    limit_set_command = f"lxc config device set {machine_name} eth0 limits.egress=0kbit"
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.ingress=1kbit"
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.priority=10"
    subprocess.check_call(limit_set_command.split())


async def restore_network_for_unit_with_ip_change(machine_name: str) -> None:
    """Restore network from a lxc container by removing mask from eth0."""
    restore_network_command = f"lxc config device remove {machine_name} eth0"
    subprocess.check_call(restore_network_command.split())


async def restore_network_for_unit_without_ip_change(machine_name: str) -> None:
    """Restore network from a lxc container (without causing the change of the unit IP address)."""
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.egress="
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.ingress="
    subprocess.check_call(limit_set_command.split())
    limit_set_command = f"lxc config device set {machine_name} eth0 limits.priority="
    subprocess.check_call(limit_set_command.split())


def is_machine_reachable_from(origin_machine: str, target_machine: str) -> bool:
    """Test network reachability between hosts.

    Args:
        origin_machine: hostname of the machine to test connection from
        target_machine: hostname of the machine to test connection to
    """
    try:
        subprocess.check_call(f"lxc exec {origin_machine} -- ping -c 5 {target_machine}".split())
        return True
    except subprocess.CalledProcessError:
        return False


@tenacity.retry(stop=tenacity.stop_after_attempt(60), wait=tenacity.wait_fixed(15))
def assert_ip_different_after_retore(model_name: str, hostname: str, old_ip: str) -> bool:
    """Wait until network is restored.

    Args:
        model_name: The name of the model
        hostname: The name of the instance
        old_ip: old registered IP address
    """
    assert get_unit_ip(model_name, hostname) == old_ip, "IP address has not changed yet."


@tenacity.retry(stop=tenacity.stop_after_attempt(20), wait=tenacity.wait_fixed(15))
async def wait_network_restore(ops_test: OpsTest, unit_name: str) -> None:
    """Wait until network is restored.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit
        old_ip: old registered IP address
    """
    return_code, stdout, _ = await ops_test.juju("ssh", unit_name, "ip", "a")
    if return_code != 0:
        raise Exception

    juju_unit_ip = await get_unit_ip(ops_test, unit_name)

    if juju_unit_ip in stdout:
        raise Exception


async def get_unit_ip(ops_test: OpsTest, unit_name: str) -> str:
    """Wrapper for getting unit ip.

    Args:
        ops_test: The ops test object passed into every test case
        unit_name: The name of the unit to get the address
    Returns:
        The (str) ip of the unit
    """
    app_name = unit_name.split("/")[0]
    unit_num = unit_name.split("/")[1]
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["public-address"]
    return address


async def get_controller_machine(ops_test: OpsTest) -> str:
    """Return controller machine hostname.

    Args:
        ops_test: The ops test framework instance
    Returns:
        Controller hostname (str)
    """
    _, raw_controller, _ = await ops_test.juju("show-controller")

    controller = yaml.safe_load(raw_controller.strip())

    return [
        machine.get("instance-id")
        for machine in controller[ops_test.controller_name]["controller-machines"].values()
    ][0]


@tenacity.retry(stop=tenacity.stop_after_attempt(60), wait=tenacity.wait_fixed(15), reraise=True)
def wait_network_restore_with_ip_change(model_name: str, hostname: str, old_ip: str) -> None:
    """Wait until network is restored.

    Args:
        model_name: The name of the model
        hostname: The name of the instance
        old_ip: old registered IP address
    """
    if get_unit_ip(model_name, hostname) == old_ip:
        raise Exception("Network not restored, IP address has not changed yet.")
