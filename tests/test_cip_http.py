"""Tests for CCMCIP authenticate.asp stub."""

from __future__ import annotations

import socket
import urllib.parse
import urllib.request

from simulator.cip_http import start_cip_http


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_authenticate_returns_plain_authorized():
    port = _free_port()
    server = start_cip_http("127.0.0.1", port)
    try:
        query = urllib.parse.urlencode(
            {
                "UserID": "Administrator",
                "Password": "secret",
                "devicename": "SEP001380AD9E5F",
            }
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/CCMCIP/authenticate.asp",
            data=query.encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read()
            assert resp.status == 200
            assert body == b"AUTHORIZED"
    finally:
        server.shutdown()
        server.server_close()


def test_authenticate_get_with_query():
    port = _free_port()
    server = start_cip_http("127.0.0.1", port)
    try:
        url = (
            f"http://127.0.0.1:{port}/CCMCIP/authenticate.asp?"
            "UserID=u&Password=p&devicename=SEP001122334455"
        )
        with urllib.request.urlopen(url, timeout=3) as resp:
            assert resp.read() == b"AUTHORIZED"
    finally:
        server.shutdown()
        server.server_close()
