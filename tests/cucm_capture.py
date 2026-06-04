"""Helpers for CUCM pcap regression tests (committed wire hex in tests/fixtures/)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from simulator import payloads

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cucm_frames.json"

# CUCM call refs seen in lab pcaps
REF_NEW_CALL = 0x0100001A
REF_INCOMING_CALL = 0x0100001F
LINE = 1


def load_fixture_group(group: str) -> dict[str, str]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if group not in data:
        raise KeyError(f"unknown fixture group {group!r}")
    return data[group]


def wire_from_hex(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)


def msg_id(packet: bytes) -> int:
    return struct.unpack("<I", packet[8:12])[0]


def body(packet: bytes) -> bytes:
    return packet[12:]


def normalize(packet: bytes) -> bytes:
    return payloads.normalize_skinny_packet(packet)


def assert_packet_equal(
    expected: bytes,
    actual: bytes,
    *,
    label: str = "",
    normalize_wire: bool = False,
) -> None:
    if normalize_wire:
        expected = normalize(expected)
        actual = normalize(actual)
    prefix = f"{label}: " if label else ""
    assert actual == expected, (
        f"{prefix}packet mismatch\n"
        f"  expected ({len(expected)}): {expected.hex()}\n"
        f"  actual   ({len(actual)}): {actual.hex()}"
    )


def assert_frame(group: str, frame: str | int, actual: bytes, **kwargs) -> None:
    hex_str = load_fixture_group(group)[str(frame)]
    assert_packet_equal(wire_from_hex(hex_str), actual, label=f"{group}[{frame}]", **kwargs)
