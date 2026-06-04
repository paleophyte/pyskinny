"""Reliable client shutdown / unregister."""

from __future__ import annotations

import time

import messages  # noqa: F401
import pytest

from client import SCCPClient
from messages.generic import handle_keypad_press
from simulator.server import SkinnySimulator
from state import PhoneState


@pytest.fixture
def sim_server():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5300,
        tftp=False,
        admin_port=0,
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address
    yield sim, host, port
    sim.stop()


def test_stop_unregisters_after_connected_call(sim_server):
    sim, host, port = sim_server

    state_a = PhoneState(server=host, mac="AABBCCDDEE31", model="7970", port=port, tftp_port=6969)
    state_b = PhoneState(server=host, mac="AABBCCDDEE32", model="7970", port=port, tftp_port=6969)
    client_a = SCCPClient(state_a)
    client_b = SCCPClient(state_b)
    client_a.get_tftp_config = False
    client_b.get_tftp_config = False
    client_a.start()
    client_b.start()
    assert state_a.is_registered.wait(timeout=20)
    assert state_b.is_registered.wait(timeout=20)

    dn_b = sim.registry.get(state_b.device_name)
    client_a.press_softkey("NewCall")
    time.sleep(0.2)
    for ch in dn_b:
        handle_keypad_press(client_a, 1, int(ch))
        time.sleep(0.05)
    assert client_b.events.call_ringing.wait(timeout=10)
    client_b.press_softkey("Answer")
    assert client_a.events.call_connected.wait(timeout=10)

    client_a.stop()
    client_b.stop()
    assert state_a.is_unregistered.wait(timeout=10), "caller should unregister cleanly"
    assert state_b.is_unregistered.wait(timeout=10), "callee should unregister cleanly"
