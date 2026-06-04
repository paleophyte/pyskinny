"""CCMCIP-style HTTP for phone authenticationURL and related stubs."""

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_CIP_XML_OK = b'<?xml version="1.0" encoding="UTF-8"?><CiscoIPPhone><Response/></CiscoIPPhone>'


def _auth_config() -> tuple[str | None, str | None, bool]:
    """Optional lab credentials via SIMULATOR_CIP_USER / SIMULATOR_CIP_PASS."""
    user = os.environ.get("SIMULATOR_CIP_USER")
    password = os.environ.get("SIMULATOR_CIP_PASS")
    strict = os.environ.get("SIMULATOR_STRICT_CIP_AUTH", "").lower() in ("1", "true", "yes")
    return user, password, strict


def _parse_request_params(path: str, body: bytes) -> dict[str, str]:
    params: dict[str, str] = {}
    parsed = urlparse(path)
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if values:
            params[key.lower()] = values[0]
    if body:
        text = body.decode("utf-8", errors="replace")
        for key, values in parse_qs(text, keep_blank_values=True).items():
            if values:
                params[key.lower()] = values[0]
    return params


def _authorize(params: dict[str, str]) -> bool:
    expected_user, expected_pass, strict = _auth_config()
    if not strict or not expected_user:
        return True
    user = params.get("userid") or params.get("username") or ""
    password = params.get("password") or ""
    return user == expected_user and password == (expected_pass or "")


class _CipHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        logger.debug("CCMCIP %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self._handle(body)

    def _handle(self, body: bytes = b"") -> None:
        path = self.path or ""
        params = _parse_request_params(path, body)
        if "authenticate" in path.lower():
            self._handle_authenticate(params)
            return
        self._send_bytes(_CIP_XML_OK, content_type="text/xml; charset=utf-8")

    def _handle_authenticate(self, params: dict[str, str]) -> None:
        user = params.get("userid") or params.get("username") or "?"
        device = params.get("devicename") or params.get("device") or "?"
        ok = _authorize(params)
        logger.info(
            "CCMCIP authenticate from %s user=%s device=%s -> %s",
            self.client_address[0],
            user,
            device,
            "AUTHORIZED" if ok else "UN-AUTHORIZED",
        )
        if ok:
            self._send_bytes(b"AUTHORIZED", content_type="text/plain")
        else:
            self._send_bytes(b"UN-AUTHORIZED", content_type="text/plain")

    def _send_bytes(self, payload: bytes, *, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_cip_http(host: str = "0.0.0.0", port: int = 8088) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _CipHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"cip-http-{port}",
        daemon=True,
    )
    thread.start()
    logger.info("CCMCIP HTTP listening on %s:%s (authenticate.asp -> plain AUTHORIZED)", host, port)
    return server
