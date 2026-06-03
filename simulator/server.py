"""Minimal SCCP / Skinny CallManager simulator."""

from __future__ import annotations

import logging
import socket
import threading

from simulator.registry import DeviceRegistry
from simulator.session import SkinnySession

logger = logging.getLogger(__name__)


class SkinnySimulator:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2000,
        dn_start: int = 1000,
        server_name: str = "SkinnySim",
    ):
        self.host = host
        self.port = port
        self.server_name = server_name
        self.registry = DeviceRegistry(dn_start=dn_start)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def address(self) -> tuple[str, int]:
        if self._sock:
            return self._sock.getsockname()  # type: ignore[return-value]
        return self.host, self.port

    def start(self, background: bool = True) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(32)
        bound = self._sock.getsockname()
        logger.info(
            "Skinny simulator listening on %s:%s (DNs from %s)",
            bound[0],
            bound[1],
            self.registry._dn_start,
        )
        if background:
            self._thread = threading.Thread(target=self._serve_forever, name="skinny-sim", daemon=True)
            self._thread.start()
        else:
            self._serve_forever()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _serve_forever(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                self._sock.settimeout(1.0)
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            t = threading.Thread(
                target=self._handle_client,
                args=(conn, addr),
                name=f"skinny-{addr[0]}:{addr[1]}",
                daemon=True,
            )
            t.start()

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        session = SkinnySession(conn, addr, self.registry, self.server_name)
        session.run()
