import logging

import pytest

from data_platform_helpers.charm_actions import get_password, set_password
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.fixture
def test_charm():
    """A fixture that returns the information necessary for deploying a charm along with
    the username that is to be tested against get-password and set-password actions"""
    return {
        "deploy_args": {
            "entity_url": "postgresql-k8s",
            "channel": "14/stable",
            "series": "jammy",
            "revision": 444,
            "num_units": 1,
            "application_name": "postgresql",
            "trust": True,
        },
        "test_username": "operator",
    }


async def test_deploy_charm(ops_test: OpsTest, test_charm):
    """Deploy the postgresql-k8s charm and see it deploys successfully and settles to active state."""
    logger.info("Deploying test charm...")
    deploy_args = test_charm["deploy_args"]
    await ops_test.model.deploy(**deploy_args)

    logger.info("Waiting for test charm to be idle and active...")
    await ops_test.model.wait_for_idle(
        apps=[deploy_args["application_name"]], timeout=1000, status="active"
    )


async def test_get_password(ops_test: OpsTest, test_charm):
    """Test the get-password action and assert it returns the password for the test user"""
    password = await get_password(
        ops_test=ops_test,
        app_name=test_charm["deploy_args"]["application_name"],
        username=test_charm["test_username"],
    )
    assert password is not None
    assert len(password) > 0


async def test_set_password(ops_test: OpsTest, test_charm):
    """Test the set-password action and assert that the password has been successfully set for the test user"""
    new_password = "foobar"
    result = await set_password(
        ops_test=ops_test,
        app_name=test_charm["deploy_args"]["application_name"],
        username=test_charm["test_username"],
        password=new_password,
    )
    assert new_password == result

    get_password_result = await get_password(
        ops_test=ops_test,
        app_name=test_charm["deploy_args"]["application_name"],
        username=test_charm["test_username"],
    )
    assert get_password_result == new_password
