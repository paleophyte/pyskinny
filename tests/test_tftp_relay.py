"""TFTP relay forwards RRQ/DATA to a backend tftpy server."""

from __future__ import annotations

import socket
import struct
import tempfile
import threading
import time
from pathlib import Path

import pytest
import tftpy

from simulator.tftp_relay import TftpRelay, _TransferSession
from simulator.tftp_service import FALLBACK_TFTP_PORT


def _rrq(filename: str) -> bytes:
    mode = b"octet"
    return struct.pack("!H", 1) + filename.encode() + b"\x00" + mode + b"\x00"


def _ack(block: int) -> bytes:
    return struct.pack("!HH", 4, block)


@pytest.fixture
def tftp_backend_port():
    """tftpy server on ephemeral port."""
    root = Path(tempfile.mkdtemp())
    (root / "hello.txt").write_text("relay-ok\n", encoding="utf-8")
    port_holder: list[int] = []

    def run():
        server = tftpy.TftpServer(str(root))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        port_holder.append(port)
        server.listen("127.0.0.1", port)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    for _ in range(50):
        if port_holder:
            break
        time.sleep(0.05)
    assert port_holder, "backend TFTP did not start"
    yield port_holder[0]
    time.sleep(0.1)


def test_relay_fetches_file(tftp_backend_port: int):
    relay_port = 18769
    relay = TftpRelay(
        listen_host="127.0.0.1",
        listen_port=relay_port,
        backend_host="127.0.0.1",
        backend_port=tftp_backend_port,
    )
    relay_thread = threading.Thread(target=relay.start, daemon=True)
    relay_thread.start()
    time.sleep(0.2)

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.bind(("127.0.0.1", 0))
    client.settimeout(5.0)
    client.sendto(_rrq("hello.txt"), ("127.0.0.1", relay_port))

    data = b""
    server_tid: tuple[str, int] | None = None
    block = 1
    while True:
        packet, addr = client.recvfrom(65535)
        if server_tid is None:
            server_tid = addr
        op = struct.unpack("!H", packet[:2])[0]
        if op == 3:
            data += packet[4:]
            client.sendto(_ack(block), server_tid)
            if len(packet) < 516:
                break
            block += 1
        elif op == 5:
            pytest.fail(f"TFTP error: {packet!r}")

    assert data.replace(b"\r\n", b"\n") == b"relay-ok\n"
    relay.stop()


def test_relay_drops_session_on_recv_error():
    """ConnectionResetError on a session socket must not kill the relay loop."""

    class BrokenSock:
        def recvfrom(self, *_args, **_kwargs):
            raise ConnectionResetError("simulated reset")

        def close(self):
            pass

    relay = TftpRelay(
        listen_host="127.0.0.1",
        listen_port=18770,
        backend_host="127.0.0.1",
        backend_port=1,
    )
    relay._running = True
    good = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    good.bind(("127.0.0.1", 0))
    bad = BrokenSock()
    session = _TransferSession(
        client_addr=("10.0.0.1", 9999),
        upstream_sock=bad,
        client_sock=good,
    )
    relay._sessions[session.client_addr] = session
    relay._on_session_socket(bad)
    assert session.client_addr not in relay._sessions
    good.close()
    relay.stop()
