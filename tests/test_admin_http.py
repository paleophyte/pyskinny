"""Tests for simulator web admin (Reset / Restart like CUCM)."""

from __future__ import annotations

import socket
import struct
import urllib.request

from simulator.admin_http import start_admin_http
from simulator.call_hub import CallHub
from simulator.registry import DeviceRegistry
from simulator.session import SkinnySession
from simulator import payloads


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _fake_session(device: str, dn: str, ip: str = "10.0.0.5") -> SkinnySession:
    srv, cli = socket.socketpair()
    session = SkinnySession.__new__(SkinnySession)
    session.conn = cli
    session.addr = (ip, 12345)
    session.registry = DeviceRegistry()
    session.server_name = "TestSim"
    session.hub = CallHub()
    session.tftp = None
    session.device_name = device
    session.directory_number = dn
    session.station_ip = ip
    session.source_port = 5001
    session._registered = True
    session._lines = 1
    session.device_type = 30006
    session._legacy_phone = False
    session.active_call = None
    session.awaiting_media_ack = False
    session.sent: list[bytes] = []

    def _send(packet: bytes) -> None:
        session.sent.append(packet)

    session.send = _send  # type: ignore[method-assign]
    session.disconnect = lambda: cli.close()  # type: ignore[method-assign]
    srv.close()
    return session


def _msg_id(packet: bytes) -> int:
    return struct.unpack("<III", packet[:12])[2]


def test_reset_and_restart_payloads():
    assert _msg_id(payloads.reset_device()) == 0x0029
    assert _msg_id(payloads.restart_device()) == 0x0030


def test_admin_restart_sends_skinny_message():
    port = _free_port()
    hub = CallHub()
    reg = DeviceRegistry(dn_start=1000)
    reg.assign("SEP111122223333")
    session = _fake_session("SEP111122223333", "1000")
    hub.register_session(session)

    server = start_admin_http(
        "127.0.0.1",
        port,
        hub=hub,
        registry=reg,
        server_name="TestSim",
    )
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/phones/SEP111122223333/restart",
            method="POST",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            import json

            body = json.loads(resp.read())
            assert body["ok"] is True
        assert _msg_id(session.sent[-1]) == 0x0030
    finally:
        server.shutdown()
        server.server_close()


def test_admin_reset_unknown_device():
    port = _free_port()
    hub = CallHub()
    reg = DeviceRegistry()
    server = start_admin_http(
        "127.0.0.1",
        port,
        hub=hub,
        registry=reg,
        server_name="TestSim",
    )
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/phones/SEPNOPE/reset",
            method="POST",
            headers={"Accept": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()
