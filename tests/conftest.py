import os
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--no-audio",
        action="store_true",
        default=False,
        help="Disable dial tone, DTMF beeps, and other speaker output during tests",
    )


def pytest_configure(config):
    if not config.getoption("--no-audio"):
        return
    import state as state_mod

    _orig_init = state_mod.PhoneState.__init__

    def _init_no_audio(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        self.enable_audio = False

    state_mod.PhoneState.__init__ = _init_no_audio
    config._pyskinny_phone_state_init = _orig_init


def pytest_unconfigure(config):
    orig = getattr(config, "_pyskinny_phone_state_init", None)
    if orig is not None:
        import state as state_mod

        state_mod.PhoneState.__init__ = orig


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
