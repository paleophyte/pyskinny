"""CM2 captured assets and button-template phone profile."""

from __future__ import annotations

import struct
import time

import messages  # noqa: F401

from client import SCCPClient
from simulator.cm2_assets import CM2_BUTTON_TEMPLATE_RES
from simulator.payloads import (
    button_template_res,
    is_cm2_button_phone,
    normalize_skinny_packet,
    phone_template_profile,
)
from simulator.server import SkinnySimulator
from state import PhoneState


def test_cm2_button_phone_types():
    assert is_cm2_button_phone(14)
    assert phone_template_profile(14) == "cm2"
    assert phone_template_profile(30007) == "legacy7912"
    assert phone_template_profile(30006) == "modern"


def test_cm2_button_template_res_matches_capture():
    pkt = normalize_skinny_packet(CM2_BUTTON_TEMPLATE_RES)
    assert struct.unpack("<I", pkt[8:12])[0] == 0x0097
    body = pkt[12:]
    _offset, count, total = struct.unpack("<III", body[:12])
    assert count == 26
    assert total == 26
    assert len(body) >= 12 + count * 2


def test_button_template_res_cm2_profile():
    pkt = button_template_res(cm2=True)
    assert pkt == normalize_skinny_packet(CM2_BUTTON_TEMPLATE_RES)


def test_cm2_template_button_layout():
    body = normalize_skinny_packet(CM2_BUTTON_TEMPLATE_RES)[12:]
    count = struct.unpack("<III", body[:12])[1]
    buttons = []
    for i in range(count):
        btn_def = struct.unpack_from("<H", body, 12 + i * 2)[0]
        buttons.append(((btn_def >> 8) & 0xFF, btn_def & 0xFF))
    # Lines 1-4, then park/redial/speed dials per live CM2 Virtual30 template
    assert buttons[:4] == [(9, 1), (9, 2), (9, 3), (9, 4)]
    assert (126, 1) in buttons  # Call Park
    assert (1, 1) in buttons  # Last Number Redial


def test_virtual30_sim_register_gets_cm2_button_template():
    sim = SkinnySimulator(host="127.0.0.1", port=0, tftp=False, admin_port=0)
    sim.start(background=True)
    time.sleep(0.15)
    host, port = sim.address
    state = PhoneState(server=host, device_name="pyskinny01", model="Virtual30SPplus", port=port)
    state.enable_audio = False
    client = SCCPClient(state)
    client.get_tftp_config = False
    try:
        client.start()
        assert state.is_registered.wait(timeout=20)
        assert len(state.button_template) == 26
        assert not state.softkey_template
        assert state.button_template["1"]["type_name"] == "Line"
    finally:
        client.stop()
        sim.stop()
