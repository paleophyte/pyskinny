"""TFTP server that serves generated Cisco-style phone configs."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path

import tftpy

from simulator.registry import DeviceRegistry
from simulator.tftp_config import (
    _sep_name_from_filename,
    build_sep_config,
    build_xml_default,
)
from utils.client import get_local_ip

logger = logging.getLogger(__name__)

PRIVILEGED_TFTP_PORT = 69
FALLBACK_TFTP_PORT = 6969


def can_bind_udp_port(host: str, port: int) -> bool:
    """Return True if a UDP socket can bind to host:port (probe only, no listen)."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host or "0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def resolve_tftp_listen_port(host: str, requested: int) -> int:
    """
    Pick the TFTP listen port.

    When the default port 69 is requested but cannot be bound (typical without
    Administrator/root), fall back to FALLBACK_TFTP_PORT (6969).
    Any other explicit --tftp-port value is used as-is.
    """
    if requested != PRIVILEGED_TFTP_PORT:
        return requested

    bind_host = host if host else "0.0.0.0"
    if can_bind_udp_port(bind_host, PRIVILEGED_TFTP_PORT):
        return PRIVILEGED_TFTP_PORT

    logger.warning(
        "Cannot bind TFTP port %s on %s (usually requires Administrator/root). "
        "Falling back to port %s. "
        "pyskinny clients must use tftp_port=%s; hardware phones expect port %s.",
        PRIVILEGED_TFTP_PORT,
        bind_host,
        FALLBACK_TFTP_PORT,
        FALLBACK_TFTP_PORT,
        PRIVILEGED_TFTP_PORT,
    )
    return FALLBACK_TFTP_PORT


def resolve_advertise_host(bind_host: str, explicit: str | None = None) -> str:
    """IP address embedded in phone XML (CallManager / TFTP target)."""
    if explicit:
        return explicit
    if bind_host and bind_host not in ("0.0.0.0", ""):
        return bind_host
    return get_local_ip("8.8.8.8")


class TftpConfigService:
    """
    Serves XMLDefault.cnf.xml and per-device SEP*.cnf.xml from a TFTP root.

    Unknown SEP files are created on demand (DN reserved from the registry).
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        cm_host: str,
        *,
        skinny_port: int = 2000,
        root: str | Path | None = None,
        listen_host: str = "0.0.0.0",
        listen_port: int = PRIVILEGED_TFTP_PORT,
    ):
        self.registry = registry
        self.cm_host = cm_host
        self.skinny_port = skinny_port
        self.listen_host = listen_host
        self.requested_port = listen_port
        self.listen_port = resolve_tftp_listen_port(listen_host, listen_port)
        self.fell_back_from_privileged = (
            listen_port == PRIVILEGED_TFTP_PORT and self.listen_port != PRIVILEGED_TFTP_PORT
        )
        self._root = Path(root) if root else Path(tempfile.mkdtemp(prefix="pyskinny-tftp-"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._server: tftpy.TftpServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._write_xml_default()
        self._seed_static_assets()

    def _seed_static_assets(self) -> None:
        """Copy bundled Ringlist.xml etc. into TFTP root when not already present."""
        assets_dir = Path(__file__).resolve().parent / "tftp_assets"
        if not assets_dir.is_dir():
            return
        for src in assets_dir.rglob("*"):
            if not src.is_file() or src.name == "README.txt":
                continue
            rel = src.relative_to(assets_dir)
            dest = self._root / rel
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            logger.debug("Seeded TFTP asset %s", rel)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def bound_port(self) -> int:
        if self._server and self._server.listenport:
            return int(self._server.listenport)
        return self.listen_port

    def _write_xml_default(self) -> None:
        path = self._root / "XMLDefault.cnf.xml"
        path.write_text(
            build_xml_default(self.cm_host, self.skinny_port),
            encoding="utf-8",
        )
        logger.debug("Wrote %s", path)

    def write_device_config(self, device_name: str, directory_number: str | None = None) -> Path:
        """Write or refresh SEP<mac>.cnf.xml on disk."""
        dn = directory_number or self.registry.assign(device_name)
        text = build_sep_config(
            device_name,
            dn,
            self.cm_host,
            skinny_port=self.skinny_port,
        )
        path = self._root / f"{device_name}.cnf.xml"
        with self._lock:
            path.write_text(text, encoding="utf-8")
        logger.info("TFTP config %s -> DN %s (CM %s)", path.name, dn, self.cm_host)
        return path

    def _dyn_file(self, requested: str, **kwargs):
        """tftpy dyn_file_func: materialize XML on disk and return a real file object."""
        name = requested.replace("\\", "/").lstrip("/")
        sep = _sep_name_from_filename(name)
        if sep:
            dn = self.registry.assign(sep)
            text = build_sep_config(
                sep,
                dn,
                self.cm_host,
                skinny_port=self.skinny_port,
            )
        elif name == "XMLDefault.cnf.xml":
            text = build_xml_default(self.cm_host, self.skinny_port)
        else:
            return None

        path = self._root / name
        with self._lock:
            path.write_text(text, encoding="utf-8")
        return open(path, "rb")

    def start(self, background: bool = True) -> None:
        self._server = tftpy.TftpServer(
            str(self._root),
            dyn_file_func=self._dyn_file,
        )
        if background:
            self._thread = threading.Thread(
                target=self._listen,
                name="skinny-tftp",
                daemon=True,
            )
            self._thread.start()
        else:
            self._listen()

    def _listen(self) -> None:
        assert self._server is not None
        try:
            self._server.listen(self.listen_host, self.listen_port)
        except OSError as exc:
            logger.error(
                "Cannot bind TFTP port %s on %s: %s",
                self.listen_port,
                self.listen_host,
                exc,
            )
            raise

    def stop(self) -> None:
        if self._server:
            try:
                self._server.stop(now=True)
            except Exception:
                pass
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None
