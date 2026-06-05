"""Regression: blind transfer from blind_xfer.pcap (Virtual Phone pattern)."""

from __future__ import annotations

import struct

BLIND_XFER_START = bytes.fromhex("0c00000000000000050000000400000001000000")
BLIND_XFER_COMPLETE = bytes.fromhex("0c00000000000000050000000400000001000000")
DIAL_1 = bytes.fromhex("08000000000000000300000001000000")
DIAL_0 = bytes.fromhex("08000000000000000300000000000000")
DIAL_9 = bytes.fromhex("08000000000000000300000009000000")
ON_HOOK = bytes.fromhex("040000000000000007000000")


def _stimulus(packet: bytes) -> tuple[int, int]:
    assert struct.unpack("<III", packet[:12])[2] == 0x0005
    return struct.unpack("<II", packet[12:20])


def _keypad(packet: bytes) -> int:
    assert struct.unpack("<III", packet[:12])[2] == 0x0003
    return struct.unpack("<I", packet[12:16])[0]


def test_blind_xfer_uses_stimulus_four_twice():
    assert _stimulus(BLIND_XFER_START) == (4, 1)
    assert _stimulus(BLIND_XFER_COMPLETE) == (4, 1)


def test_blind_xfer_dials_1091():
    assert _keypad(DIAL_1) == 1
    assert _keypad(DIAL_0) == 0
    assert _keypad(DIAL_9) == 9
    assert _keypad(DIAL_1) == 1


def test_blind_xfer_ends_with_on_hook():
    assert struct.unpack("<III", ON_HOOK[:12])[2] == 0x0007
