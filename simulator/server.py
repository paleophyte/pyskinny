"""Minimal SCCP / Skinny CallManager simulator."""

from __future__ import annotations

import logging
import socket
import threading

from simulator.call_hub import CallHub
from simulator.media_hub import SimMediaHub
from simulator.registry import DeviceRegistry
from simulator.session import SkinnySession
from simulator.tftp_service import TftpConfigService, resolve_advertise_host
from simulator.cip_http import start_cip_http

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
        auto_answer: list[str] | None = None,
        cip_port: int = 8088,
        rtp_sim_peer: str = "off",
        rtp_sim_tone_hz: float = 1000.0,
        rtp_sim_loopback_delay_ms: float = 1500.0,
        rtp_sim_loopback_gain_db: float = 12.0,
        rtp_sim_loopback_preamble_sec: float = 2.0,
        ivr_dn: str | None = None,
    ):
        self.host = host
        self.port = port
        self.server_name = server_name
        self.registry = DeviceRegistry(dn_start=dn_start)
        self.ivr_dn = str(ivr_dn) if ivr_dn else None
        if self.ivr_dn:
            self.registry.reserve_dn(self.ivr_dn)
        media_hub = SimMediaHub(
            mode=rtp_sim_peer,
            loopback_delay_ms=rtp_sim_loopback_delay_ms,
            loopback_gain_db=rtp_sim_loopback_gain_db,
            loopback_preamble_sec=rtp_sim_loopback_preamble_sec,
        ) if rtp_sim_peer != "off" else None
        if self.ivr_dn and media_hub is None:
            media_hub = SimMediaHub(mode="tone")
        self.hub = CallHub(media_hub=media_hub, ivr_dn=self.ivr_dn)
        self._media_hub = media_hub
        if auto_answer:
            for target in auto_answer:
                self.hub.set_auto_answer(target)
        if self._media_hub is not None:
            self._media_hub.tone_hz = rtp_sim_tone_hz
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.tftp: TftpConfigService | None = None
        self._cip_http = None
        self.cip_port = cip_port

        if tftp:
            cm_host = resolve_advertise_host(host, advertise_host)
            if self._media_hub is not None:
                self._media_hub.set_advertise_ip(cm_host)
            self.tftp = TftpConfigService(
                self.registry,
                cm_host,
                skinny_port=port,
                root=tftp_root,
                listen_host=tftp_host or host,
                listen_port=tftp_port,
                cip_port=cip_port,
            )
        elif self._media_hub is not None:
            self._media_hub.set_advertise_ip(resolve_advertise_host(host, advertise_host))

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
            self._cip_http = start_cip_http(self.host, self.cip_port)
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
            "Skinny simulator listening on %s:%s (DNs from %s%s)",
            bound[0],
            bound[1],
            self.registry._dn_start,
            f", IVR DN {self.ivr_dn}" if self.ivr_dn else "",
        )
        if self.tftp:
            logger.info(
                "Phones should use CallManager / TFTP address %s (Skinny port %s, TFTP port %s%s, CCMCIP http://%s:%s)",
                self.tftp.cm_host,
                self.port,
                self.tftp.listen_port,
                (
                    " — fell back from 69; run: python -m simulator.tftp_relay (as admin)"
                    if self.tftp.fell_back_from_privileged
                    else ""
                ),
                self.tftp.cm_host,
                self.cip_port,
            )
        if background:
            self._thread = threading.Thread(target=self._serve_forever, name="skinny-sim", daemon=True)
            self._thread.start()
        else:
            self._serve_forever()

    def stop(self) -> None:
        self._stop.set()
        if self._media_hub is not None:
            self._media_hub.stop_all()
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
            self.hub,
            tftp=self.tftp,
        )
        session.run()
