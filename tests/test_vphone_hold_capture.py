"""Regression: CM2 Virtual Phone hold/unhold from vphone_hold_unhold.pcap."""

from __future__ import annotations

import struct

# Phone -> CM (frame 1 hold, frame 8 resume toggle, frame 14 line)
VPHONE_HOLD_STIMULUS = bytes.fromhex("0c00000000000000050000000300000001000000")
VPHONE_RESUME_TOGGLE = bytes.fromhex("0c00000000000000050000000300000001000000")
VPHONE_LINE_STIMULUS = bytes.fromhex("0c00000000000000050000000900000001000000")


def _stimulus_body(packet: bytes) -> tuple[int, int]:
    assert struct.unpack("<III", packet[:12])[2] == 0x0005
    return struct.unpack("<II", packet[12:20])


def test_vphone_hold_sends_stimulus_three_on_line_one():
    stype, line = _stimulus_body(VPHONE_HOLD_STIMULUS)
    assert stype == 3
    assert line == 1


def test_vphone_resume_is_same_hold_toggle():
    stype, line = _stimulus_body(VPHONE_RESUME_TOGGLE)
    assert stype == 3
    assert line == 1


def test_vphone_line_stimulus_after_resume():
    stype, line = _stimulus_body(VPHONE_LINE_STIMULUS)
    assert stype == 9
    assert line == 1
