"""Skinny / SCCP framing helpers (server side)."""

from __future__ import annotations

import struct
from dataclasses import dataclass


def pack_message(msg_id: int, payload: bytes = b"") -> bytes:
    """Build a Skinny message (data_length, version, msg_id, payload)."""
    data_length = len(payload) + 4
    return struct.pack("<III", data_length, 0, msg_id) + payload


def read_message(sock) -> tuple[int, bytes] | None:
    """
    Read one Skinny message from a connected socket.
    Returns (msg_id, payload) or None on clean close.
    """
    header = _recv_exact(sock, 12)
    if not header:
        return None
    data_length, _version, msg_id = struct.unpack("<III", header)
    payload_len = max(0, data_length - 4)
    payload = _recv_exact(sock, payload_len) if payload_len else b""
    if payload is None and payload_len:
        return None
    return msg_id, payload


def _recv_exact(sock, nbytes: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < nbytes:
        chunk = sock.recv(nbytes - len(buf))
        if not chunk:
            return None if not buf else None
        buf.extend(chunk)
    return bytes(buf)


@dataclass
class RegisterReqInfo:
    device_name: str
    device_type: int
    station_ip: str


def parse_register_req(payload: bytes) -> RegisterReqInfo:
    """Parse RegisterReq body (after the 12-byte Skinny header)."""
    device_name = payload[0:16].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    # reserved @ 16, instance @ 20
    station_ip_int = struct.unpack("!I", payload[24:28])[0]
    station_ip = ".".join(str((station_ip_int >> (8 * i)) & 0xFF) for i in range(3, -1, -1))
    device_type = struct.unpack("<I", payload[28:32])[0] if len(payload) >= 32 else 0
    return RegisterReqInfo(device_name=device_name, device_type=device_type, station_ip=station_ip)
