import logging
from importlib.util import find_spec

if find_spec("pytest_operator") is None:
    logging.error(
        "'test_helpers' submodule dependencies requirements are not met."
        "Try installing 'tests' extras with 'pip install data-platform-helpers[tests]'"
    )
    raise ImportError
