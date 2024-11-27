# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


from pytest_operator.plugin import OpsTest


async def run_action(
    ops_test: OpsTest, action_name: str, app_name: str, unit_index: int = 0, **kwargs
):
    """Run a given action in a specified unit with the given set of kwargs, and return the result."""
    unit = ops_test.model.applications[app_name].units[unit_index]
    action = await unit.run_action(action_name=action_name, **kwargs)
    result = await action.wait()
    return result.results


async def get_password(
    ops_test: OpsTest,
    app_name: str,
    unit_index: int = 0,
    action_name: str = "get-password",
    username: str | None = "operator",
) -> dict:
    """Get password corresponding to the given username."""
    kwargs = {}
    if username is not None:
        kwargs.update({"username": username})
    result = await run_action(
        ops_test=ops_test,
        action_name=action_name,
        app_name=app_name,
        unit_index=unit_index,
        **kwargs,
    )
    password = result.get("password")
    return password


async def set_password(
    ops_test: OpsTest,
    password: str,
    app_name: str,
    unit_index: int = 0,
    action_name: str = "get-password",
    username: str | None = "operator",
) -> dict:
    """Set password for the given username."""
    kwargs = {"password": password}
    if username is not None:
        kwargs.update({"username": username})
    result = await run_action(
        ops_test=ops_test,
        action_name=action_name,
        app_name=app_name,
        unit_index=unit_index,
        **kwargs,
    )
    password = result.get("password")
    return password
