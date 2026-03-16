# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Conftest module for pytest."""

import argparse
import logging
import shlex
import shutil
from datetime import datetime
from pathlib import Path
import subprocess

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

LXD_CONTROLLER = "lxd-controller"


def pytest_addoption(parser):
    parser.addoption(
        "--os-series", help="Ubuntu series for dp libs charm (e.g. jammy)", default="jammy"
    )
    parser.addoption(
        "--build-bases-index",
        type=int,
        help="Index of charmcraft.yaml base that matches --os-series",
        default=0,
    )


def pytest_configure(config):
    if (config.option.os_series is None) ^ (config.option.build_bases_index is None):
        raise argparse.ArgumentError(
            None,
            "--os-series and --build-bases-index must be given together",
        )
    # Note: Update defaults whenever charmcraft.yaml is changed
    valid_combinations = [(0, "noble")]
    if (config.option.build_bases_index, config.option.os_series) not in valid_combinations:
        raise argparse.ArgumentError(
            None, f"Only base index combinations {valid_combinations} are accepted."
        )


@pytest.fixture(scope="session")
def dp_libs_ubuntu_series(pytestconfig) -> str:
    if pytestconfig.option.os_series:
        return pytestconfig.option.os_series
    raise ValueError("Missing os series.")


@pytest.fixture(scope="module")
def ops_test(ops_test: OpsTest, pytestconfig) -> OpsTest:
    """Re-defining OpsTest.build_charm in a way that it takes CI caching and build parameters into account.

    Build parameters (for charms available for multiple OS versions) are considered both when building the
    charm, or when fetching pre-built, CI cached version of it.
    """
    _build_charm = ops_test.build_charm

    # Add bases_index option (indicating which OS version to use)
    # when building the charm within the scope of the test run
    async def build_charm(charm_path, bases_index: int | None = None) -> Path | None:
        if not bases_index and pytestconfig.option.build_bases_index is not None:
            bases_index = pytestconfig.option.build_bases_index

        logger.info(f"Building charm {charm_path} with base index {bases_index}")

        return await _build_charm(charm_path, bases_index=bases_index)

    ops_test.build_charm = build_charm
    return ops_test


@pytest.fixture(scope="module", autouse=True)
def copy_v0_data_interfaces_library_into_charm(ops_test: OpsTest):
    """Copy the data_interfaces library to the different charm folder."""
    subprocess.run(
        shlex.split("charmcraft fetch-lib charms.data_platform_libs.v0.data_interfaces"),
        cwd="tests/integration/backward-compatibility-charm",
    )


@pytest.fixture(scope="module", autouse=True)
def copy_data_interfaces_library_into_charm(ops_test: OpsTest):
    """Copy the data_interfaces library to the different charm folder."""
    library_path = "data_plaform_helpers/"
    install_path = "tests/integration/database-charm/src/" + library_path
    shutil.copytree(library_path, install_path)
    install_path = "tests/integration/dummy-database-charm/src/" + library_path
    shutil.copytree(library_path, install_path)
    install_path = "tests/integration/kafka-charm/src/" + library_path
    shutil.copytree(library_path, install_path)
    install_path = "tests/integration/application-charm/src/" + library_path
    shutil.copytree(library_path, install_path)
    install_path = "tests/integration/opensearch-charm/src/" + library_path
    shutil.copytree(library_path, install_path)
    install_path = "tests/integration/kafka-connect-charm/src/" + library_path
    shutil.copytree(library_path, install_path)


@pytest.fixture(scope="module")
async def application_charm(ops_test: OpsTest):
    """Build the application charm."""
    charm_path = "tests/integration/application-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def backward_compatibility_charm(ops_test: OpsTest):
    """Build a v0 charm to integrate with a v1 client."""
    charm_path = "tests/integration/backward-compatibility-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def database_charm(ops_test: OpsTest):
    """Build the database charm."""
    charm_path = "tests/integration/database-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def dummy_database_charm(ops_test: OpsTest):
    """Build the database charm."""
    charm_path = "tests/integration/dummy-database-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def application_s3_charm(ops_test: OpsTest):
    """Build the application-s3 charm."""
    charm_path = "tests/integration/application-s3-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def s3_charm(ops_test: OpsTest):
    """Build the S3 charm."""
    charm_path = "tests/integration/s3-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def kafka_charm(ops_test: OpsTest):
    """Build the Kafka charm."""
    charm_path = "tests/integration/kafka-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def kafka_connect_charm(ops_test: OpsTest):
    """Build the Kafka Connect dummy charm."""
    charm_path = "tests/integration/kafka-connect-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def opensearch_charm(ops_test: OpsTest):
    """Build the OpenSearch charm.

    TODO we could simplify a lot of these charm builds by having a single test charm that includes
    all these relations. This might be easily achieved by merging this repo with the
    data-integrator charm repo.
    """
    charm_path = "tests/integration/opensearch-charm"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(autouse=True)
async def without_errors(ops_test: OpsTest, request):
    """This fixture is to list all those errors that mustn't occur during execution."""
    # To be executed after the tests
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    yield
    whitelist = []
    if "log_errors_allowed" in request.keywords:
        for marker in [
            mark for mark in request.node.iter_markers() if mark.name == "log_errors_allowed"
        ]:
            for arg in marker.args:
                whitelist.append(arg)

        # All errors allowed
        if not whitelist:
            return

    _, dbg_log, _ = await ops_test.juju("debug-log", "--ms", "--replay")
    lines = dbg_log.split("\n")
    for _, line in enumerate(lines):
        logitems = line.split(" ")
        if not line or len(logitems) < 3:
            continue
        if logitems[1] < now:
            continue
        if logitems[2] == "ERROR":
            assert any(white in line for white in whitelist)
