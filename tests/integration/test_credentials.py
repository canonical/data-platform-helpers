# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


from pytest_operator.plugin import OpsTest
from data_platform_helpers.charm_actions import get_password, set_password


async def test_deploy_charm(ops_test: OpsTest):
    ops_test.model.deploy(
        {
            "mysql-k8s",
            # ...
        }
    )


async def test_get_password(ops_test: OpsTest):
    password = await get_password(
        ops_test=ops_test,
        app_name="mysql-k8s",
        username="root",
    )
    assert password is not None
    assert len(password) > 0


async def test_set_password(ops_test: OpsTest):
    new_password = "foobar"
    result = await set_password(
        ops_test=ops_test, app_name="mysql-k8s", username="root", password=new_password
    )
    assert new_password == result

    get_password_result = await get_password(
        ops_test=ops_test,
        app_name="mysql-k8s",
        username="root",
    )
    assert get_password_result == new_password


# NOTES

# 1. How to integration-test?
# 2. Different charms have different signature for get-password.
# 3. Test the helper in all charms?
