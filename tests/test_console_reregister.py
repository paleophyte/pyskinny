"""Client auto-reconnect after CM Reset/Restart (run_console uses same client path)."""

from __future__ import annotations

import json
import socket
import time
import urllib.request

import messages  # noqa: F401
import pytest

from client import SCCPClient
from simulator.server import SkinnySimulator
from state import PhoneState


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def sim_with_admin():
    admin_port = _free_port()
    sim = SkinnySimulator(
        host="127.0.0.1",
        port=0,
        dn_start=5200,
        tftp=False,
        admin_port=admin_port,
    )
    sim.start(background=True)
    time.sleep(0.15)
    host, skinny_port = sim.address
    yield sim, host, skinny_port, admin_port
    sim.stop()


def _register_client(host: str, skinny_port: int, mac: str) -> tuple[SCCPClient, PhoneState]:
    state = PhoneState(server=host, mac=mac, model="7970", port=skinny_port, tftp_port=6969)
    client = SCCPClient(state)
    client.get_tftp_config = False
    client.start()
    assert state.is_registered.wait(timeout=20), f"{state.device_name} failed to register"
    return client, state


def _admin_post(admin_port: int, path: str) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{admin_port}{path}",
        method="POST",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def test_admin_restart_reregisters_connected_client(sim_with_admin):
    sim, host, skinny_port, admin_port = sim_with_admin
    client, state = _register_client(host, skinny_port, "AABBCCDDEEAB")
    device = state.device_name

    try:
        old_sock = client.sock
        body = _admin_post(admin_port, f"/phones/{device}/restart")
        assert body["ok"] is True

        deadline = time.time() + 25
        reconnected = False
        while time.time() < deadline:
            if (
                client.sock is not None
                and client.sock is not old_sock
                and state.is_registered.is_set()
            ):
                reconnected = True
                break
            time.sleep(0.01)

        assert reconnected, "client should reconnect and re-register after Restart"
        assert client.running is True
    finally:
        client.stop()
        assert state.is_unregistered.wait(timeout=10), f"{state.device_name} failed to unregister"


def test_admin_reset_reregisters_connected_client(sim_with_admin):
    sim, host, skinny_port, admin_port = sim_with_admin
    client, state = _register_client(host, skinny_port, "AABBCCDDEEAC")
    device = state.device_name

    try:
        old_sock = client.sock
        body = _admin_post(admin_port, f"/phones/{device}/reset")
        assert body["ok"] is True

        deadline = time.time() + 30
        reconnected = False
        while time.time() < deadline:
            if (
                client.sock is not None
                and client.sock is not old_sock
                and state.is_registered.is_set()
            ):
                reconnected = True
                break
            time.sleep(0.01)

        assert reconnected
    finally:
        client.stop()
        assert state.is_unregistered.wait(timeout=10), f"{state.device_name} failed to unregister"
