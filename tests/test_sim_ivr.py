"""Virtual IVR DN — single-phone dial tone / loopback without a second handset."""

from __future__ import annotations

import time

import messages  # noqa: F401
import pytest

from client import SCCPClient
from messages.generic import handle_keypad_press
from simulator.registry import DeviceRegistry
from simulator.server import SkinnySimulator
from state import PhoneState


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


def test_registry_skips_reserved_ivr_dn():
    reg = DeviceRegistry(dn_start=9998)
    reg.reserve_dn("9999")
    assert reg.assign("SEPA") == "9998"
    assert reg.assign("SEPB") == "10000"


def test_dial_ivr_auto_connects():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5200,
        tftp=False,
        ivr_dn="9999",
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address

    client, state = _register_client(host, port, "AABBCCDDEE20")
    assert sim.registry.get(state.device_name) == "5200"

    try:
        _dial(client, "9999")
        assert client.events.call_connected.wait(timeout=10), "caller not connected to IVR"
        call = client.state.active_calls_list[-1]
        assert str(call) in client.state.calls
        assert client.state.calls[str(call)]["call_state"] == 5
        labels = [label for label, _ in client.state.get_current_softkeys()]
        assert "EndCall" in labels
    finally:
        client.on_hook()
        time.sleep(0.2)
        client.stop()
        sim.stop()


def test_dial_ivr_end_call_hangs_up():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5500,
        tftp=False,
        ivr_dn="9999",
        rtp_sim_peer="tone",
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address

    client, _state = _register_client(host, port, "AABBCCDDEE22")

    try:
        _dial(client, "9999")
        assert client.events.call_connected.wait(timeout=10)
        client.events.call_connected.clear()
        client.events.call_ended.clear()

        client.press_softkey("EndCall")
        assert client.events.call_ended.wait(timeout=10), "EndCall did not end IVR call"
        assert not client.state.active_calls_list
    finally:
        client.stop()
        sim.stop()


def test_dial_ivr_starts_sim_media_hub():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5300,
        tftp=False,
        ivr_dn="9999",
        rtp_sim_peer="tone",
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address

    client, _state = _register_client(host, port, "AABBCCDDEE21")

    try:
        _dial(client, "9999")
        assert client.events.call_connected.wait(timeout=10)

        deadline = time.time() + 10
        while time.time() < deadline:
            if sim._media_hub and sim._media_hub._sessions:
                break
            time.sleep(0.1)
        assert sim._media_hub is not None
        assert sim._media_hub._sessions, "SimMediaHub should be active after IVR media ack"
    finally:
        client.on_hook()
        time.sleep(0.2)
        client.stop()
        sim.stop()


def test_ivr_menu_keypad_loopback():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5600,
        tftp=False,
        ivr_dn="9999",
        rtp_sim_peer="tone",
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address

    client, _state = _register_client(host, port, "AABBCCDDEE23")

    try:
        _dial(client, "9999")
        assert client.events.call_connected.wait(timeout=10)

        deadline = time.time() + 10
        while time.time() < deadline:
            if sim._media_hub and sim._media_hub._sessions:
                break
            time.sleep(0.1)
        assert sim._media_hub is not None
        ref = client.state.active_calls_list[-1]
        call_ref = client.numeric_call_ref(ref) or int(str(ref))

        handle_keypad_press(client, 1, 1)
        time.sleep(0.3)

        session = sim._media_hub._sessions.get(call_ref)
        assert session is not None
        assert session.legs[0].echo is not None
    finally:
        client.on_hook()
        time.sleep(0.2)
        client.stop()
        sim.stop()


def test_ivr_menu_hangup_key():
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5700,
        tftp=False,
        ivr_dn="9999",
        rtp_sim_peer="tone",
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address

    client, _state = _register_client(host, port, "AABBCCDDEE24")

    try:
        _dial(client, "9999")
        assert client.events.call_connected.wait(timeout=10)
        client.events.call_ended.clear()

        deadline = time.time() + 10
        while time.time() < deadline:
            if sim._media_hub and sim._media_hub._sessions:
                break
            time.sleep(0.1)
        assert sim._media_hub and sim._media_hub._sessions

        handle_keypad_press(client, 1, 9)
        assert client.events.call_ended.wait(timeout=10), "IVR 9 should hang up"
    finally:
        client.stop()
        sim.stop()
