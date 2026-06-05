"""Shared --web-port helpers for CLI, console, and macro entry points."""

from __future__ import annotations

import argparse
import logging
import threading
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from client import SCCPClient

logger = logging.getLogger(__name__)


def add_web_cli_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--web-port",
        type=int,
        default=None,
        metavar="PORT",
        help="Serve browser remote control for the local SCCP client",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="Bind address for --web-port (use 0.0.0.0 for LAN access in the lab)",
    )


def start_client_web_from_args(
    client: SCCPClient,
    args: Any,
    *,
    line: int = 1,
    lock: threading.Lock | None = None,
) -> ThreadingHTTPServer | None:
    port = getattr(args, "web_port", None)
    if not port:
        return None
    from ui.client_web import start_client_web

    host = getattr(args, "web_host", None) or "127.0.0.1"
    server = start_client_web(client, host=host, port=port, line=line, lock=lock)
    display = "127.0.0.1" if host == "0.0.0.0" else host
    logger.info("Web UI http://%s:%s/", display, port)
    return server


def stop_client_web(server: ThreadingHTTPServer | None) -> None:
    if server is None:
        return
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
