"""
Live CallManager integration tests.

Run against the lab:

  set PYSKINNY_CUCM_SERVER=10.0.0.180
  set PYSKINNY_TEST_MAC=222233334444
  pytest -m integration -v

Optional phones (use a free MAC — only one SCCP session per device):
  222233334444 -> ext 1003
  222233334445 -> ext 1010
  222233334446 -> ext 1011
"""

import messages  # noqa: F401 — register SCCP message handlers
import pytest

from client import SCCPClient
from state import PhoneState
from utils.client import normalize_mac_address


@pytest.mark.integration
def test_sccp_register_and_unregister(cucm_lab):
    state = PhoneState(
        server=cucm_lab["server"],
        mac=cucm_lab["mac"],
        model=cucm_lab["model"],
    )
    client = SCCPClient(state)
    client.get_tftp_config = not cucm_lab["skip_tftp"]

    try:
        client.start()

        registered = state.is_registered.wait(timeout=cucm_lab["register_timeout"])
        assert registered, (
            f"{state.device_name} did not register within "
            f"{cucm_lab['register_timeout']}s on {cucm_lab['server']}"
        )
        assert state.keepalive_interval > 0
        assert state.device_name == "SEP" + normalize_mac_address(cucm_lab["mac"])
    finally:
        client.stop()
        assert state.is_unregistered.wait(timeout=15), "unregister did not complete"


@pytest.mark.integration
def test_each_lab_phone_registers(cucm_lab):
    """Register each lab 7970 sequentially (one MAC at a time)."""
    import time

    # Allow CUCM to release the device used by test_sccp_register_and_unregister.
    time.sleep(3)

    macs = [
        "222233334444",  # ext 1003
        "222233334445",  # ext 1010
        "222233334446",  # ext 1011
    ]

    for mac in macs:
        state = PhoneState(server=cucm_lab["server"], mac=mac, model=cucm_lab["model"])
        client = SCCPClient(state)
        client.get_tftp_config = not cucm_lab["skip_tftp"]

        try:
            client.start()
            assert state.is_registered.wait(timeout=cucm_lab["register_timeout"]), (
                f"SEP{normalize_mac_address(mac)} failed to register"
            )
        finally:
            client.stop()
            assert state.is_unregistered.wait(timeout=20), (
                f"SEP{normalize_mac_address(mac)} did not unregister cleanly"
            )
            time.sleep(2)  # let CUCM release the device before the next MAC
