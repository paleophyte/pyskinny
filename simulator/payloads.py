"""Minimal Skinny server response payloads for phone registration."""

from __future__ import annotations

import struct
import time


def _cstring(text: str, length: int) -> bytes:
    return text.encode("ascii", errors="replace")[: length - 1].ljust(length, b"\x00")


# SCCP call-state values (subset)
CALL_STATE_ONHOOK = 2
CALL_STATE_RINGOUT = 3
CALL_STATE_RINGIN = 4
CALL_STATE_CONNECTED = 5
CALL_STATE_HOLD = 8
CALL_STATE_PROCEED = 12

# Skinny soft-key events (match messages/generic.py)
SK_NEWCALL = 2
SK_HOLD = 3
SK_ENDCALL = 9
SK_RESUME = 10
SK_ANSWER = 11

# Cisco tone IDs used by pyskinny client
TONE_DIAL = 33
TONE_RING = 36
TONE_HOLD = 58
TONE_REMOTE_HOLD = 59


def register_ack(keepalive: int = 30) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack("<I", keepalive)
    body += b"MMDDYY"
    body += struct.pack("<H", 0)
    body += struct.pack("<I", keepalive)
    body += struct.pack("<BBH", 5, 0, 0)
    return pack_message(0x0081, body)


def capabilities_req() -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x009B, b"")


def button_template_res() -> bytes:
    """One Line button (instance 1)."""
    from simulator.protocol import pack_message

    # type 9 = Line, instance 1 -> (9 << 8) | 1
    buttons = struct.pack("<H", (9 << 8) | 1)
    body = struct.pack("<III", 0, 1, 1) + buttons
    return pack_message(0x0097, body)


def softkey_template_res() -> bytes:
    from simulator.protocol import pack_message

    keys = [
        (b"Redial\x00", 1),
        (b"NewCall\x00", 2),
        (b"Answer\x00", 11),
        (b"Hold\x00", 3),
        (b"Resume\x00", 10),
        (b"EndCall\x00", 9),
    ]
    body = struct.pack("<III", 0, len(keys), 12)
    for label, event in keys:
        body += label.ljust(16, b"\x00")[:16]
        body += struct.pack("<I", event)
    return pack_message(0x0108, body)


def softkey_set_res() -> bytes:
    from simulator.protocol import pack_message

    skti = bytes([2, 1, 11, 3, 10, 9] + [0] * 10)
    skii = b""
    for info_id in (302, 301, 311, 303, 309):
        skii += struct.pack("<H", info_id)
    skii = skii.ljust(32, b"\x00")
    body = struct.pack("<III", 0, 1, 1) + skti + skii
    return pack_message(0x0109, body)


def call_state(
    state: int,
    line: int = 1,
    call_ref: int = 0,
) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack("<III", state, line, call_ref)
    body += struct.pack("<III", 0, 0, 0)
    return pack_message(0x0111, body)


def call_info(
    caller_name: str,
    caller_num: str,
    called_name: str,
    called_num: str,
    *,
    line: int = 1,
    call_ref: int = 0,
    call_type: int = 2,
) -> bytes:
    from simulator.protocol import pack_message

    body = _cstring(caller_name, 40)
    body += _cstring(caller_num, 24)
    body += _cstring(called_name, 40)
    body += _cstring(called_num, 24)
    body += struct.pack("<III", line, call_ref, call_type)
    return pack_message(0x008F, body)


def start_tone(tone: int, line: int = 1, call_ref: int = 0) -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0082, struct.pack("<IIII", tone, 0, line, call_ref))


def stop_tone(line: int = 1, call_ref: int = 0) -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0083, struct.pack("<II", line, call_ref))


def activate_call_plane(line: int = 1) -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0116, struct.pack("<I", line))


def dialed_number(number: str, line: int = 1, call_ref: int = 0) -> bytes:
    from simulator.protocol import pack_message

    body = _cstring(number, 24)
    body += struct.pack("<II", line, call_ref)
    return pack_message(0x011D, body)


def open_receive_channel(call_ref: int = 0, ptime_ms: int = 20) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack(
        "<IIIIIIIIHH",
        0,
        0,
        ptime_ms,
        0,
        0,
        0,
        call_ref,
        0,
        0,
        0,
    )
    body += b"\x00" * 32
    return pack_message(0x0105, body)


def start_media_transmission(
    call_ref: int,
    remote_ip: int,
    remote_port: int,
    *,
    ptime_ms: int = 20,
) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack(
        "<IIIIIIIIHH",
        0,
        0,
        remote_ip,
        remote_port,
        ptime_ms,
        0,
        0,
        0,
        0,
        1,
    )
    body += struct.pack("<I", 0)
    body += struct.pack("<I", call_ref)
    body += struct.pack("<HH", 0, 0)
    body += b"\x00" * 32
    return pack_message(0x008A, body)


def config_stat_res(device_name: str, server_label: str, lines: int = 1, speed_dials: int = 0) -> bytes:
    from simulator.protocol import pack_message

    dev = device_name.encode("ascii", errors="replace")[:15].ljust(16, b"\x00")
    user = b"SkinnySim\x00".ljust(40, b"\x00")
    server = server_label.encode("ascii", errors="replace")[:39].ljust(40, b"\x00")
    body = dev
    body += struct.pack("<II", 0, 0)
    body += user + server
    body += struct.pack("<II", lines, speed_dials)
    return pack_message(0x0093, body)


def line_stat_res(line_number: int, directory_number: str) -> bytes:
    from simulator.protocol import pack_message

    dn = directory_number.encode("ascii", errors="replace")[:23].ljust(24, b"\x00")
    body = struct.pack("<I", line_number) + dn
    return pack_message(0x0092, body)


def forward_stat_res(line_number: int = 1) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack("<III", 0, line_number, 0)
    body += b"\x00" * 24  # forward all
    body += struct.pack("<I", 0)
    body += b"\x00" * 24  # forward busy
    body += struct.pack("<I", 0)
    body += b"\x00" * 24  # forward no answer
    return pack_message(0x0090, body)


def speed_dial_stat_res(speed_dial_number: int, dn: str = "", label: str = "") -> bytes:
    from simulator.protocol import pack_message

    dn_b = dn.encode("ascii", errors="replace")[:23].ljust(24, b"\x00")
    label_b = label.encode("ascii", errors="replace")[:39].ljust(40, b"\x00")
    body = struct.pack("<I", speed_dial_number) + dn_b + label_b
    return pack_message(0x0091, body)


def time_date_res() -> bytes:
    from simulator.protocol import pack_message

    now = time.gmtime()
    w_year = now.tm_year
    w_month = now.tm_mon
    w_day = now.tm_mday
    w_day_of_week = (now.tm_wday + 1) % 7  # skinny convention varies; client uses calendar
    w_hour = now.tm_hour
    w_minute = now.tm_min
    w_second = now.tm_sec
    w_millisecond = 0
    w_systemtime = int(time.time())
    body = struct.pack(
        "<IIIIIIIII",
        w_year,
        w_month,
        w_day_of_week,
        w_day,
        w_hour,
        w_minute,
        w_second,
        w_millisecond,
        w_systemtime,
    )
    return pack_message(0x0094, body)


def display_prompt_status(prompt: str = "Ready", line_instance: int = 1, call_reference: int = 0) -> bytes:
    from simulator.protocol import pack_message

    text = prompt.encode("ascii", errors="replace")[:31].ljust(32, b"\x00")
    body = struct.pack("<I", 0) + text + struct.pack("<II", line_instance, call_reference)
    return pack_message(0x0112, body)


def select_soft_keys(
    line_instance: int = 1,
    call_reference: int = 0,
    softkey_set_index: int = 0,
    valid_key_mask: int = 0xFFFFFFFF,
) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack("<IIII", line_instance, call_reference, softkey_set_index, valid_key_mask)
    return pack_message(0x0110, body)


def keepalive_ack() -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0100, b"")


def unregister_ack(status: int = 0) -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0118, struct.pack("<I", status))
