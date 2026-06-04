"""Two-party call tests against the Skinny simulator."""

from __future__ import annotations

import socket
import time

import messages  # noqa: F401
import pytest

from client import SCCPClient
from messages.generic import handle_keypad_press
from simulator.server import SkinnySimulator
from state import PhoneState


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def sim_server():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5000,
        tftp=False,
        admin_port=0,
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address
    yield sim, host, port
    sim.stop()


def _register_client(host: str, skinny_port: int, mac: str) -> tuple[SCCPClient, PhoneState]:
    state = PhoneState(server=host, mac=mac, model="7970", port=skinny_port, tftp_port=6969)
    client = SCCPClient(state)
    client.get_tftp_config = False
    client.start()
    assert state.is_registered.wait(timeout=20), f"{state.device_name} failed to register"
    return client, state


def _dial(client: SCCPClient, number: str) -> None:
    client.press_softkey("NewCall")
    time.sleep(0.25)
    for ch in number:
        if ch.isdigit():
            handle_keypad_press(client, 1, int(ch))
        elif ch == "#":
            handle_keypad_press(client, 1, 0x0F)
        elif ch == "*":
            handle_keypad_press(client, 1, 0x0E)
        time.sleep(0.05)


def test_two_phones_register_and_call(sim_server):
    sim, host, port = sim_server

    client_a, state_a = _register_client(host, port, "AABBCCDDEE01")
    client_b, state_b = _register_client(host, port, "AABBCCDDEE02")

    dn_a = sim.registry.get(state_a.device_name)
    dn_b = sim.registry.get(state_b.device_name)
    assert dn_a == "5000"
    assert dn_b == "5001"

    try:
        _dial(client_a, dn_b)

        assert client_b.events.call_ringing.wait(timeout=10), "callee did not ring"
        client_b.press_softkey("Answer")

        assert client_a.events.call_connected.wait(timeout=10), "caller not connected"
        assert client_b.events.call_connected.wait(timeout=10), "callee not connected"

        assert str(client_a.state.active_calls_list), "caller has no active call ref"
        assert str(client_b.state.active_calls_list), "callee has no active call ref"
    finally:
        client_a.stop()
        client_b.stop()
        assert state_a.is_unregistered.wait(timeout=10)
        assert state_b.is_unregistered.wait(timeout=10)


def test_two_phones_hold_and_resume(sim_server):
    sim, host, port = sim_server

    client_a, state_a = _register_client(host, port, "AABBCCDDEE03")
    client_b, state_b = _register_client(host, port, "AABBCCDDEE04")
    dn_b = sim.registry.get(state_b.device_name)

    try:
        _dial(client_a, dn_b)
        assert client_b.events.call_ringing.wait(timeout=10)
        client_b.press_softkey("Answer")
        assert client_a.events.call_connected.wait(timeout=10)
        assert client_b.events.call_connected.wait(timeout=10)

        ref = str(client_a.state.active_calls_list[-1])
        assert client_a.state.calls[ref]["call_state"] == 5

        client_a.press_softkey("Hold")
        time.sleep(0.75)
        assert client_a.state.calls[ref]["call_state"] == 8
        assert client_b.state.calls[ref]["call_state"] == 8

        client_a.press_softkey("Resume")
        time.sleep(0.5)
        assert client_a.state.calls[ref]["call_state"] == 5
        assert client_b.state.calls[ref]["call_state"] == 5
        assert client_a.events.call_connected.wait(timeout=10)
        assert client_b.events.call_connected.wait(timeout=10)
    finally:
        client_a.stop()
        client_b.stop()
        assert state_a.is_unregistered.wait(timeout=10)
        assert state_b.is_unregistered.wait(timeout=10)


def test_connected_keypad_relays_to_callee(sim_server):
    """Caller Skinny keypad during a connected call (for callee macro WAIT_DIGIT)."""
    sim, host, port = sim_server

    client_a, state_a = _register_client(host, port, "AABBCCDDEE08")
    client_b, state_b = _register_client(host, port, "AABBCCDDEE09")
    dn_b = sim.registry.get(state_b.device_name)

    try:
        _dial(client_a, dn_b)
        assert client_b.events.call_ringing.wait(timeout=10)
        client_b.press_softkey("Answer")
        assert client_a.events.call_connected.wait(timeout=10)
        assert client_b.events.call_connected.wait(timeout=10)

        handle_keypad_press(client_a, 1, 1)
        time.sleep(0.3)

        ch = client_b.wait_for_digit(timeout=1.0)
        assert ch == "1"
    finally:
        client_a.stop()
        client_b.stop()
        state_a.is_unregistered.wait(timeout=10)
        state_b.is_unregistered.wait(timeout=10)


def test_simulator_blind_transfer(sim_server):
    sim, host, port = sim_server

    client_a, state_a = _register_client(host, port, "AABBCCDDEE05")
    client_b, state_b = _register_client(host, port, "AABBCCDDEE06")
    client_c, state_c = _register_client(host, port, "AABBCCDDEE07")

    dn_b = sim.registry.get(state_b.device_name)
    dn_c = sim.registry.get(state_c.device_name)

    try:
        _dial(client_a, dn_b)
        assert client_b.events.call_ringing.wait(timeout=10)
        client_b.press_softkey("Answer")
        assert client_a.events.call_connected.wait(timeout=10)
        assert client_b.events.call_connected.wait(timeout=10)

        client_a.blind_transfer(dn_c, pause=0.15)

        assert client_c.events.call_ringing.wait(timeout=10), "transfer target did not ring"
        deadline = time.time() + 5
        while time.time() < deadline and client_a.state.active_calls_list:
            time.sleep(0.1)
        assert not client_a.state.active_calls_list, "transferor should be on hook"

        client_c.press_softkey("Answer")
        assert client_b.events.call_connected.wait(timeout=10), "transferred party not connected"
        assert client_c.events.call_connected.wait(timeout=10), "transfer target not connected"
    finally:
        client_a.stop()
        client_b.stop()
        client_c.stop()
        state_a.is_unregistered.wait(timeout=10)
        state_b.is_unregistered.wait(timeout=10)
        state_c.is_unregistered.wait(timeout=10)


def test_simulator_auto_answer_connects_without_manual_answer():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5100,
        tftp=False,
        auto_answer=["AABBCCDDEE12"],
        admin_port=0,
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address

    client_a, state_a = _register_client(host, port, "AABBCCDDEE11")
    client_b, state_b = _register_client(host, port, "AABBCCDDEE12")
    dn_b = sim.registry.get(state_b.device_name)

    try:
        _dial(client_a, dn_b)

        assert client_a.events.call_connected.wait(timeout=10), "caller not connected"
        assert client_b.events.call_connected.wait(timeout=10), "callee not connected (auto-answer)"
    finally:
        client_a.stop()
        client_b.stop()
        sim.stop()
        assert state_a.is_unregistered.wait(timeout=10)
        assert state_b.is_unregistered.wait(timeout=10)
