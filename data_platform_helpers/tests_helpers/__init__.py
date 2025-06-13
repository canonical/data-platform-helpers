import logging
from importlib.util import find_spec

from pytest_operator.plugin import OpsTest

from .vms.integration_helpers import IntergrationHelpers


if find_spec("pytest_operator") is None:
    logging.error(
        "'test_helpers' submodule dependencies requirements are not met."
        "Try installing 'tests' extras with 'pip install data-platform-helpers[tests]'"
    )
    raise ImportError


class TestsHelpers:
    def __init__(self, ops_test: OpsTest):
        self.integration = IntergrationHelpers(ops_test)
