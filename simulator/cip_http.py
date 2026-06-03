"""Minimal CCMCIP-style HTTP stubs so phones stop 401'ing on authenticationURL."""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

_CIP_XML_OK = b'<?xml version="1.0" encoding="UTF-8"?><CiscoIPPhone><Response/></CiscoIPPhone>'


class _CipHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        logger.debug("CCMCIP %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self._respond()

    def _respond(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(_CIP_XML_OK)))
        self.end_headers()
        self.wfile.write(_CIP_XML_OK)


def start_cip_http(host: str = "0.0.0.0", port: int = 8088) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _CipHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"cip-http-{port}",
        daemon=True,
    )
    thread.start()
    logger.info("CCMCIP HTTP stub listening on %s:%s", host, port)
    return server
