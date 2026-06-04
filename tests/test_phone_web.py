"""Tests for the phone remote web UI."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ui.phone_web import start_phone_web

# Minimal valid 1x1 PNG
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _MockPhoneHandler(BaseHTTPRequestHandler):
    screenshot: bool = True
    execute: bool = True
    execute_hits: list[str]

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        if "/CGI/Screenshot" in self.path:
            if not self.screenshot:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_TINY_PNG)))
            self.end_headers()
            self.wfile.write(_TINY_PNG)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if "/CGI/Execute" not in self.path:
            self.send_error(404)
            return
        if not self.execute:
            self.send_error(503)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        self.execute_hits.append(body)
        self.send_response(200)
        self.end_headers()


def _start_mock_phone(*, screenshot: bool = True, execute: bool = True) -> tuple[ThreadingHTTPServer, list[str], int]:
    hits: list[str] = []
    handler = type(
        "_BoundMockPhone",
        (_MockPhoneHandler,),
        {"screenshot": screenshot, "execute": execute, "execute_hits": hits},
    )
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, hits, port


def _post_json(url: str, payload: dict) -> tuple[int, dict | bytes, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            body = resp.read()
            if "json" in ct:
                return resp.status, json.loads(body.decode()), ct
            return resp.status, body, ct
    except urllib.error.HTTPError as exc:
        body = exc.read()
        ct = exc.headers.get("Content-Type", "")
        if "json" in ct:
            return exc.code, json.loads(body.decode()), ct
        return exc.code, body, ct


def test_phone_web_index_and_probe():
    mock, _hits, phone_port = _start_mock_phone()
    ui = start_phone_web("127.0.0.1", _free_port())
    ui_port = ui.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ui_port}/", timeout=3) as resp:
            html = resp.read().decode("utf-8")
        assert "Phone remote" in html or "LCD" in html

        status, data, _ct = _post_json(
            f"http://127.0.0.1:{ui_port}/api/probe",
            {"phone": {"ip": "127.0.0.1", "port": phone_port}},
        )
        assert status == 200
        assert data["screenshot"] is True
        assert data["execute"] is True
    finally:
        ui.shutdown()
        ui.server_close()
        mock.shutdown()
        mock.server_close()


def test_phone_web_screenshot_png():
    mock, _hits, phone_port = _start_mock_phone()
    ui = start_phone_web("127.0.0.1", _free_port())
    ui_port = ui.server_address[1]
    try:
        status, body, ct = _post_json(
            f"http://127.0.0.1:{ui_port}/api/screenshot",
            {"phone": {"ip": "127.0.0.1", "port": phone_port}},
        )
        assert status == 200
        assert ct.startswith("image/png")
        assert body.startswith(b"\x89PNG")
    finally:
        ui.shutdown()
        ui.server_close()
        mock.shutdown()
        mock.server_close()


def test_phone_web_execute_only_phone():
    mock, hits, phone_port = _start_mock_phone(screenshot=False, execute=True)
    ui = start_phone_web("127.0.0.1", _free_port())
    ui_port = ui.server_address[1]
    phone = {"ip": "127.0.0.1", "port": phone_port}
    try:
        status, data, _ = _post_json(
            f"http://127.0.0.1:{ui_port}/api/probe",
            {"phone": phone},
        )
        assert status == 200
        assert data["screenshot"] is False
        assert data["execute"] is True

        status, data, _ = _post_json(
            f"http://127.0.0.1:{ui_port}/api/action",
            {"phone": phone, "action": "softkey", "index": 2},
        )
        assert status == 200
        assert data["ok"] is True
        assert hits
        assert "Soft2" in hits[-1]
    finally:
        ui.shutdown()
        ui.server_close()
        mock.shutdown()
        mock.server_close()


def test_phone_web_screenshot_unsupported_returns_json():
    mock, _hits, phone_port = _start_mock_phone(screenshot=False, execute=False)
    ui = start_phone_web("127.0.0.1", _free_port())
    ui_port = ui.server_address[1]
    try:
        status, data, ct = _post_json(
            f"http://127.0.0.1:{ui_port}/api/screenshot",
            {"phone": {"ip": "127.0.0.1", "port": phone_port}},
        )
        assert status == 501
        assert "json" in ct
        assert "error" in data
    finally:
        ui.shutdown()
        ui.server_close()
        mock.shutdown()
        mock.server_close()
