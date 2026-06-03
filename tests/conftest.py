import os
import pytest


@pytest.fixture
def cucm_lab():
    """Lab CUCM settings from environment (integration tests only)."""
    server = os.environ.get("PYSKINNY_CUCM_SERVER")
    if not server:
        pytest.skip("Set PYSKINNY_CUCM_SERVER to run integration tests (e.g. 10.0.0.180)")

    mac = os.environ.get("PYSKINNY_TEST_MAC", "222233334444")
    model = os.environ.get("PYSKINNY_TEST_MODEL", "7970")
    skip_tftp = os.environ.get("PYSKINNY_SKIP_TFTP", "1").lower() in ("1", "true", "yes")
    register_timeout = float(os.environ.get("PYSKINNY_REGISTER_TIMEOUT", "45"))

    return {
        "server": server,
        "mac": mac,
        "model": model,
        "skip_tftp": skip_tftp,
        "register_timeout": register_timeout,
    }
