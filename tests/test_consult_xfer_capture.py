"""Regression: consult transfer from consult_xfer.pcap (Virtual Phone / CM2 pattern).

Phone TX matches blind transfer (Stimulus 4 → dial 1091 → Stimulus 4 → OnHook).
Consult is distinguished on the CM side by CallInfo (0x008F) and StartTone (0x0082)
after the last dial digit while the consult leg rings, before the second Transfer.
"""

from __future__ import annotations

import struct

# Phone -> CM (consult_xfer.pcap frames 15, 21, 24, 26, 28, 33, 37)
CONSULT_XFER_START = bytes.fromhex("0c00000000000000050000000400000001000000")
CONSULT_XFER_COMPLETE = bytes.fromhex("0c00000000000000050000000400000001000000")
DIAL_1 = bytes.fromhex("08000000000000000300000001000000")
DIAL_0 = bytes.fromhex("08000000000000000300000000000000")
DIAL_9 = bytes.fromhex("08000000000000000300000009000000")
ON_HOOK = bytes.fromhex("040000000000000007000000")

# CM -> phone between last dial and second Transfer (frames 29, 31)
CONSULT_CM_CALL_INFO = bytes.fromhex(
    "84000000000000008f0000004a6f686e20446f650000680008fe8e0940fe8e09"
    "b0fe8e09e4fe8e09f8558e00000000000000000031303939000000007cfe8e09"
    "fcfd8e09837b7200709edf00009edf0010fe8e09b08c72007cfe8e097a000000"
    "f702000028fe8e09a0ccf177cc030000000000003130393100fe8e09e4fe8e09"
    "98ff8e097cfe8e09"
)
CONSULT_CM_START_TONE = bytes.fromhex("08000000000000008200000024000000")

PHONE_TX_SEQUENCE = (
    CONSULT_XFER_START,
    DIAL_1,
    DIAL_0,
    DIAL_9,
    DIAL_1,
    CONSULT_XFER_COMPLETE,
    ON_HOOK,
)

CONSULT_CM_BETWEEN_DIAL_AND_COMPLETE = (
    CONSULT_CM_CALL_INFO,
    CONSULT_CM_START_TONE,
)


def _msg_id(packet: bytes) -> int:
    return struct.unpack("<III", packet[:12])[2]


def _stimulus(packet: bytes) -> tuple[int, int]:
    assert _msg_id(packet) == 0x0005
    return struct.unpack("<II", packet[12:20])


def _keypad(packet: bytes) -> int:
    assert _msg_id(packet) == 0x0003
    return struct.unpack("<I", packet[12:16])[0]


def _start_tone(packet: bytes) -> int:
    assert _msg_id(packet) == 0x0082
    return struct.unpack("<I", packet[12:16])[0]


def test_consult_xfer_phone_tx_sequence():
    ids = [_msg_id(p) for p in PHONE_TX_SEQUENCE]
    assert ids == [0x0005, 0x0003, 0x0003, 0x0003, 0x0003, 0x0005, 0x0007]


def test_consult_xfer_uses_stimulus_four_twice():
    assert _stimulus(CONSULT_XFER_START) == (4, 1)
    assert _stimulus(CONSULT_XFER_COMPLETE) == (4, 1)


def test_consult_xfer_dials_1091():
    digits = [_keypad(p) for p in PHONE_TX_SEQUENCE if _msg_id(p) == 0x0003]
    assert digits == [1, 0, 9, 1]


def test_consult_xfer_ends_with_on_hook():
    assert _msg_id(ON_HOOK) == 0x0007


def test_consult_xfer_cm_messages_between_dial_and_complete():
    ids = [_msg_id(p) for p in CONSULT_CM_BETWEEN_DIAL_AND_COMPLETE]
    assert ids == [0x008F, 0x0082]


def test_consult_xfer_cm_call_info_lists_consult_parties():
    assert _msg_id(CONSULT_CM_CALL_INFO) == 0x008F
    body = CONSULT_CM_CALL_INFO[12:]
    assert b"1099" in body
    assert b"1091" in body
    assert b"John Doe" in body


def test_consult_xfer_cm_start_tone_is_alerting():
    assert _start_tone(CONSULT_CM_START_TONE) == 0x24  # AlertingTone
