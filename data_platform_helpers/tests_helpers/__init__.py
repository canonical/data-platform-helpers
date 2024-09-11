import logging

try:
    import pytest_operator
except ImportError as e:
    logging.error(
        "'test_helpers' submodule dependencies requirements are not met."
        "Try installing 'tests' extras with 'pip install data-platform-helpers[tests]'"
    )
    raise e
