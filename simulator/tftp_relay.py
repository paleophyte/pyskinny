"""
UDP relay: listen on TFTP port 69 (requires Administrator on Windows) and forward
to the simulator TFTP server on another port (default 6969).

TFTP uses ephemeral UDP ports after the initial RRQ/WRQ; this relay tracks each
client transfer and re-forwards DATA/ACK/ERROR between the phone and backend.

Typical lab (two terminals):

  # Admin — port 69
  python -m simulator.tftp_relay -v

  # Normal user — simulator on 6969
  python -m examples.run_simulator -vv --advertise-host 10.102.172.11 --tftp-port 6969 \\
      --tftp-root simulator/tftp_assets
"""

from __future__ import annotations

import argparse
import logging
import select
import socket
import sys
import time
from dataclasses import dataclass, field

from simulator.tftp_service import FALLBACK_TFTP_PORT, PRIVILEGED_TFTP_PORT

logger = logging.getLogger(__name__)

TFTP_OPCODE_RRQ = 1
TFTP_OPCODE_WRQ = 2
TFTP_OPCODE_DATA = 3
TFTP_OPCODE_ACK = 4
TFTP_OPCODE_ERROR = 5

SESSION_IDLE_SEC = 120.0
POLL_SEC = 0.25


def _opcode(packet: bytes) -> int | None:
    if len(packet) < 2:
        return None
    return int.from_bytes(packet[:2], "big")


def _is_terminal_data(packet: bytes) -> bool:
    if _opcode(packet) != TFTP_OPCODE_DATA:
        return False
    return len(packet) < 516


@dataclass
class _TransferSession:
    client_addr: tuple[str, int]
    upstream_sock: socket.socket
    client_sock: socket.socket
    backend_addr: tuple[str, int] | None = None
    last_activity: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def close(self) -> None:
        for sock in (self.upstream_sock, self.client_sock):
            try:
                sock.close()
            except OSError:
                pass


class TftpRelay:
    def __init__(
        self,
        listen_host: str = "0.0.0.0",
        listen_port: int = PRIVILEGED_TFTP_PORT,
        backend_host: str = "127.0.0.1",
        backend_port: int = FALLBACK_TFTP_PORT,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.backend_addr = (backend_host, backend_port)
        self._control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sessions: dict[tuple[str, int], _TransferSession] = {}
        self._running = False

    def start(self) -> None:
        try:
            self._control.bind((self.listen_host, self.listen_port))
        except OSError as exc:
            raise SystemExit(
                f"Cannot bind {self.listen_host}:{self.listen_port} ({exc}). "
                "On Windows, run this process as Administrator for port 69."
            ) from exc
        bound = self._control.getsockname()
        logger.info(
            "TFTP relay on %s:%s -> %s:%s",
            bound[0],
            bound[1],
            self.backend_addr[0],
            self.backend_addr[1],
        )
        self._running = True
        self._loop()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            self._expire_idle()
            readers = [self._control]
            for session in self._sessions.values():
                readers.append(session.upstream_sock)
                readers.append(session.client_sock)
            try:
                readable, _, _ = select.select(readers, [], [], POLL_SEC)
            except OSError:
                break
            for sock in readable:
                if sock is self._control:
                    self._on_control()
                else:
                    self._on_session_socket(sock)

    def _expire_idle(self) -> None:
        now = time.monotonic()
        stale = [
            key
            for key, session in self._sessions.items()
            if now - session.last_activity > SESSION_IDLE_SEC
        ]
        for key in stale:
            logger.debug("Session idle timeout %s", key)
            self._sessions.pop(key).close()

    def _on_control(self) -> None:
        packet, client_addr = self._control.recvfrom(65535)
        op = _opcode(packet)
        if op not in (TFTP_OPCODE_RRQ, TFTP_OPCODE_WRQ):
            logger.debug("Ignoring non-RRQ/WRQ on control port from %s op=%s", client_addr, op)
            return
        filename = packet[2:].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        logger.info("RRQ/WRQ from %s file=%r (%s bytes)", client_addr, filename, len(packet))
        old = self._sessions.pop(client_addr, None)
        if old:
            old.close()
        self._start_session(client_addr, packet)

    def _start_session(self, client_addr: tuple[str, int], first_packet: bytes) -> None:
        upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        upstream.bind((self.listen_host if self.listen_host else "0.0.0.0", 0))
        client_side = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_side.bind((self.listen_host if self.listen_host else "0.0.0.0", 0))
        session = _TransferSession(
            client_addr=client_addr,
            upstream_sock=upstream,
            client_sock=client_side,
        )
        self._sessions[client_addr] = session
        try:
            upstream.sendto(first_packet, self.backend_addr)
        except OSError as exc:
            logger.error("Forward to backend failed: %s", exc)
            self._sessions.pop(client_addr, None)
            session.close()
            return
        logger.debug(
            "Session %s upstream=%s client_face=%s",
            client_addr,
            upstream.getsockname(),
            client_side.getsockname(),
        )

    def _on_session_socket(self, sock: socket.socket) -> None:
        session = self._session_for_socket(sock)
        if not session:
            return
        packet, addr = sock.recvfrom(65535)
        session.touch()
        if sock is session.upstream_sock:
            if session.backend_addr is None:
                session.backend_addr = addr
                logger.debug("Backend TID %s for client %s", addr, session.client_addr)
            session.client_sock.sendto(packet, session.client_addr)
            if _opcode(packet) == TFTP_OPCODE_ERROR or _is_terminal_data(packet):
                self._end_session(session.client_addr)
        else:
            dest = session.backend_addr or self.backend_addr
            session.upstream_sock.sendto(packet, dest)
            if _opcode(packet) == TFTP_OPCODE_ERROR:
                self._end_session(session.client_addr)

    def _session_for_socket(self, sock: socket.socket) -> _TransferSession | None:
        for session in self._sessions.values():
            if sock in (session.upstream_sock, session.client_sock):
                return session
        return None

    def _end_session(self, client_addr: tuple[str, int]) -> None:
        session = self._sessions.pop(client_addr, None)
        if session:
            logger.debug("Session done %s", client_addr)
            session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Relay TFTP UDP port 69 to a backend (e.g. simulator on 6969)",
    )
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument(
        "--listen-port",
        type=int,
        default=PRIVILEGED_TFTP_PORT,
        help=f"Front port (default {PRIVILEGED_TFTP_PORT}, needs admin on Windows)",
    )
    parser.add_argument("--backend-host", default="127.0.0.1")
    parser.add_argument(
        "--backend-port",
        type=int,
        default=FALLBACK_TFTP_PORT,
        help=f"Simulator TFTP port (default {FALLBACK_TFTP_PORT})",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    )

    relay = TftpRelay(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        backend_host=args.backend_host,
        backend_port=args.backend_port,
    )
    try:
        relay.start()
    except KeyboardInterrupt:
        logger.info("Stopped")
        relay.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
