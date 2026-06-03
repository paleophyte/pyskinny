"""Minimal SCCP / Skinny CallManager simulator."""

from __future__ import annotations

import logging
import socket
import threading

from simulator.registry import DeviceRegistry
from simulator.session import SkinnySession
from simulator.tftp_service import TftpConfigService, resolve_advertise_host

logger = logging.getLogger(__name__)


class SkinnySimulator:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2000,
        dn_start: int = 1000,
        server_name: str = "SkinnySim",
        *,
        tftp: bool = True,
        tftp_host: str | None = None,
        tftp_port: int = 69,
        advertise_host: str | None = None,
        tftp_root: str | None = None,
    ):
        self.host = host
        self.port = port
        self.server_name = server_name
        self.registry = DeviceRegistry(dn_start=dn_start)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.tftp: TftpConfigService | None = None

        if tftp:
            cm_host = resolve_advertise_host(host, advertise_host)
            self.tftp = TftpConfigService(
                self.registry,
                cm_host,
                skinny_port=port,
                root=tftp_root,
                listen_host=tftp_host or host,
                listen_port=tftp_port,
            )

    @property
    def address(self) -> tuple[str, int]:
        if self._sock:
            return self._sock.getsockname()  # type: ignore[return-value]
        return self.host, self.port

    @property
    def tftp_address(self) -> tuple[str, int] | None:
        if not self.tftp:
            return None
        host = self.tftp.cm_host
        return host, self.tftp.bound_port

    def provision(self, mac_or_sep: str) -> str:
        """Pre-create TFTP + DN assignment for a device (e.g. before phone boot)."""
        name = mac_or_sep.upper()
        if not name.startswith("SEP"):
            from utils.client import normalize_mac_address

            name = "SEP" + normalize_mac_address(name)
        dn = self.registry.assign(name)
        if self.tftp:
            self.tftp.write_device_config(name, dn)
        return dn

    def start(self, background: bool = True) -> None:
        if self.tftp:
            self.tftp.start(background=True)
            logger.info(
                "TFTP serving from %s (XML + dynamic SEP*.cnf.xml) on %s:%s",
                self.tftp.root,
                self.tftp.listen_host,
                self.tftp.bound_port if self.tftp._server else self.tftp.listen_port,
            )

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
        if self.tftp:
            logger.info(
                "Phones should use CallManager / TFTP address %s (Skinny port %s, TFTP port %s%s)",
                self.tftp.cm_host,
                self.port,
                self.tftp.listen_port,
                " — fell back from 69" if self.tftp.fell_back_from_privileged else "",
            )
        if background:
            self._thread = threading.Thread(target=self._serve_forever, name="skinny-sim", daemon=True)
            self._thread.start()
        else:
            self._serve_forever()

    def stop(self) -> None:
        self._stop.set()
        if self.tftp:
            self.tftp.stop()
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
        session = SkinnySession(
            conn,
            addr,
            self.registry,
            self.server_name,
            tftp=self.tftp,
        )
        session.run()
