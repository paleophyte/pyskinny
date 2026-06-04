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
CALL_STATE_OFFHOOK = 1
CALL_STATE_PROCEED = 12

# Skinny soft-key events (match messages/generic.py)
SK_NEWCALL = 2
SK_HOLD = 3
SK_ENDCALL = 9
SK_RESUME = 10
SK_ANSWER = 11

# Cisco tone IDs used by pyskinny client
TONE_DIAL = 33  # InsideDialTone (0x21) — CUCM uses this for 7912 New Call
TONE_DIAL_OUTSIDE = 0x20  # DialTone
TONE_RING = 36
TONE_HOLD = 58
TONE_REMOTE_HOLD = 59

# device_type from RegisterReq (see messages/generic.py DEVICE_TYPE_MAP)
DEVICE_TYPE_7912 = 30007


def is_legacy_skinny_phone(device_type: int) -> bool:
    return device_type == DEVICE_TYPE_7912


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


def normalize_skinny_packet(packet: bytes) -> bytes:
    """Fix data_length field when a captured blob length does not match the header."""
    if len(packet) < 12:
        return packet
    dl, ver, mid = struct.unpack("<III", packet[:12])
    body = packet[12:]
    expected = 4 + len(body)
    if dl == expected:
        return packet
    return struct.pack("<III", expected, ver, mid) + body


def button_template_res(*, legacy: bool = False) -> bytes:
    if legacy:
        from simulator.cucm_legacy_assets import LEGACY_BUTTON_TEMPLATE_RES

        return normalize_skinny_packet(LEGACY_BUTTON_TEMPLATE_RES)
    from simulator.protocol import pack_message

    # type 9 = Line, instance 1 -> (9 << 8) | 1
    buttons = struct.pack("<H", (9 << 8) | 1)
    body = struct.pack("<III", 0, 1, 1) + buttons
    return pack_message(0x0097, body)


def softkey_template_res(*, legacy: bool = False) -> bytes:
    if legacy:
        from simulator.cucm_legacy_assets import LEGACY_SOFTKEY_TEMPLATE_RES

        return normalize_skinny_packet(LEGACY_SOFTKEY_TEMPLATE_RES)
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


def softkey_set_res(*, legacy: bool = False) -> bytes:
    if legacy:
        from simulator.cucm_legacy_assets import LEGACY_SOFTKEY_SET_RES
        from simulator.protocol import pack_message

        pkt = normalize_skinny_packet(LEGACY_SOFTKEY_SET_RES)
        body = bytearray(pkt[12:])
        # CUCM blob set 3 (Ring In) only had EndCall; add Answer for remote softkey use.
        set_idx = 3
        off = 12 + set_idx * 48
        body[off] = 11
        body[off + 1] = 9
        struct.pack_into("<H", body, off + 16, 311)
        struct.pack_into("<H", body, off + 18, 309)
        return pack_message(0x0109, bytes(body))
    from simulator.protocol import pack_message

    # template_index, info_index (see messages/generic.py)
    set_defs: dict[int, list[tuple[int, int]]] = {
        0: [(2, 302), (1, 301)],           # On Hook — NewCall, Redial
        1: [(3, 303), (9, 309), (4, 304)],  # Connected — Hold, EndCall, Transfer
        2: [(10, 310), (9, 309)],           # On Hold — Resume, EndCall
        3: [(11, 311)],                     # Ring In — Answer
        4: [(9, 309)],                      # Off Hook — EndCall
        8: [(9, 309)],                      # Ring Out — EndCall
    }
    # total_softkeyset_count = key slots per set (12 on 7912, 16 on newer phones).
    # Each set is always 48 bytes on the wire (16 + 32), per messages/capabilities.py.
    key_slots = 12 if legacy else 16
    num_sets = 9 if legacy else 15
    body = struct.pack("<III", 0, num_sets, key_slots)
    for idx in range(num_sets):
        pairs = set_defs.get(idx, [])
        tpl = [p[0] for p in pairs] + [0] * (16 - len(pairs))
        info = b"".join(struct.pack("<H", p[1]) for p in pairs)
        info += b"\x00\x00" * (16 - len(pairs))
        body += bytes(tpl[:16]) + info[:32]
    return pack_message(0x0109, body)


def set_speaker_mode(mode: int = 1) -> bytes:
    """Speaker on (1) — some 79xx need this before dial tone."""
    from simulator.protocol import pack_message

    return pack_message(0x0088, struct.pack("<I", mode))


def set_ringer(
    ring_mode: int = 1,
    ring_duration: int = 1,
    line: int = 0,
    call_ref: int = 0,
) -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0085, struct.pack("<IIII", ring_mode, ring_duration, line, call_ref))


def set_lamp(stimulus: int = 9, instance: int = 1, lamp_mode: int = 2) -> bytes:
    """Line lamp on (stimulus 9 = Line, lamp_mode 2 = on)."""
    from simulator.protocol import pack_message

    return pack_message(0x0086, struct.pack("<III", stimulus, instance, lamp_mode))


def clear_prompt_status(line: int = 1, call_ref: int = 0) -> bytes:
    from simulator.protocol import pack_message

    return pack_message(0x0113, struct.pack("<II", line, call_ref))


def call_state(
    state: int,
    line: int = 1,
    call_ref: int = 0,
) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack("<III", state, line, call_ref)
    body += struct.pack("<III", 0, 4, 0)
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


def start_tone(
    tone: int,
    line: int = 1,
    call_ref: int = 0,
    *,
    legacy: bool = False,
    direction: int = 2,
) -> bytes:
    from simulator.protocol import pack_message

    if legacy:
        # CM 3.x / 7912: often only tone index in payload
        return pack_message(0x0082, struct.pack("<I", tone))
    return pack_message(0x0082, struct.pack("<IIII", tone, direction, line, call_ref))


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


# CUCM pass-through party id seen on 7912 legacy media (OpenRx / StartMedia / Ack).
PASS_THROUGH_PARTY_ID = 0x01000101


def open_receive_channel(
    call_ref: int = 0,
    *,
    ptime_ms: int = 20,
    compression_type: int = 4,
    pass_through_party_id: int = PASS_THROUGH_PARTY_ID,
) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack(
        "<IIIIIIIIHH",
        call_ref,
        pass_through_party_id,
        ptime_ms,
        compression_type,
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
    compression_type: int = 4,
    pass_through_party_id: int = PASS_THROUGH_PARTY_ID,
    precedence_value: int = 0,
) -> bytes:
    from simulator.protocol import pack_message

    body = struct.pack(
        "<IIIIIIIIHH",
        call_ref,
        pass_through_party_id,
        remote_ip,
        remote_port,
        ptime_ms,
        compression_type,
        precedence_value,
        0,
        0,
        0,
    )
    body += struct.pack("<IIIHH", 0, call_ref, 0, 0, 0)
    body += b"\x00" * 32
    return pack_message(0x008A, body)


def parse_open_receive_channel_ack(payload: bytes) -> dict[str, int]:
    """Parse OpenReceiveChannelAck (7912 sends 16 bytes; CM may send 20)."""
    if len(payload) < 12:
        raise ValueError(f"OpenReceiveChannelAck too short ({len(payload)} bytes)")
    status, port = struct.unpack("<II", payload[0:4] + payload[8:12])
    ip_raw = payload[4:8]
    ip_int = struct.unpack("!I", ip_raw)[0]
    out: dict[str, int] = {"status": status, "ip": ip_int, "port": port}
    if len(payload) >= 16:
        out["pass_through_party_id"] = struct.unpack("<I", payload[12:16])[0]
    if len(payload) >= 20:
        out["call_reference"] = struct.unpack("<I", payload[16:20])[0]
    return out


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
    fqdn = directory_number.encode("ascii", errors="replace")[:39].ljust(40, b"\x00")
    label = directory_number.encode("ascii", errors="replace")[:39].ljust(40, b"\x00")
    body = struct.pack("<I", line_number) + dn + fqdn + label + struct.pack("<I", 0)
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


def legacy_display_text(
    text: str,
    line_instance: int = 1,
    call_reference: int = 0,
    *,
    tagged: bool = True,
) -> bytes:
    """7912 display lines use 0x8017-tagged text during calls (CUCM capture)."""
    from simulator.protocol import pack_message

    if tagged:
        raw = b"\x80\x17" + text.encode("ascii", errors="replace")[:30]
    else:
        raw = text.encode("ascii", errors="replace")
    raw = raw[:32].ljust(32, b"\x00")
    body = struct.pack("<I", 0) + raw + struct.pack("<II", line_instance, call_reference)
    return pack_message(0x0112, body)


def legacy_display_prompt_dial(line_instance: int = 1, call_reference: int = 0) -> bytes:
    """Empty dial prompt during New Call (CUCM cm_cap frame 85, tag 0x8020)."""
    from simulator.protocol import pack_message

    raw = b"\x80\x20" + b"\x00" * 30
    raw = raw[:32].ljust(32, b"\x00")
    body = struct.pack("<I", 0) + raw + struct.pack("<II", line_instance, call_reference)
    return pack_message(0x0112, body)


def display_pri_notify(
    text: str,
    *,
    timeout: int = 10,
    priority: int = 5,
    tagged: bool = True,
) -> bytes:
    from simulator.protocol import pack_message

    if tagged:
        raw = b"\x80\x17" + text.encode("ascii", errors="replace")[:30]
    else:
        raw = text.encode("ascii", errors="replace")
    raw = raw[:32].ljust(32, b"\x00")
    body = struct.pack("<II", timeout, priority) + raw
    return pack_message(0x0120, body)


def legacy_select_softkeys_idle() -> bytes:
    from simulator.cucm_legacy_assets import LEGACY_SELECT_SOFTKEYS_IDLE

    return normalize_skinny_packet(LEGACY_SELECT_SOFTKEYS_IDLE)


def legacy_display_prompt_idle() -> bytes:
    from simulator.cucm_legacy_assets import LEGACY_DISPLAY_PROMPT_IDLE

    return normalize_skinny_packet(LEGACY_DISPLAY_PROMPT_IDLE)


def legacy_display_prompt_ready() -> bytes:
    from simulator.cucm_legacy_assets import LEGACY_DISPLAY_PROMPT_READY

    return normalize_skinny_packet(LEGACY_DISPLAY_PROMPT_READY)


def legacy_select_softkeys_onhook() -> bytes:
    from simulator.cucm_legacy_assets import LEGACY_SELECT_SOFTKEYS_ONHOOK

    return normalize_skinny_packet(LEGACY_SELECT_SOFTKEYS_ONHOOK)


def feature_stat_res(*, legacy: bool = False) -> bytes:
    if legacy:
        from simulator.cucm_legacy_assets import LEGACY_FEATURE_STAT_RES

        return normalize_skinny_packet(LEGACY_FEATURE_STAT_RES)
    from simulator.protocol import pack_message

    body = struct.pack("<II", 1, 0)
    body += b"\x00" * 44
    return pack_message(0x011F, body)


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
