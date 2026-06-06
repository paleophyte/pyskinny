"""Regression: CM3.x registration wire from cm31_register.pcapng / cm33_register.pcapng."""

from __future__ import annotations

import struct

import pytest

from tests.cucm_capture import load_fixture_group, msg_id, wire_from_hex

CM31 = "cm31_reg"
CM33 = "cm33_reg"


def _packet(group: str, key: str) -> bytes:
    return wire_from_hex(load_fixture_group(group)[key])


@pytest.mark.parametrize(
    "group,key,expected_id",
    [
        (CM31, "softkey_template", 0x0108),
        (CM31, "button_template", 0x0097),
        (CM31, "line_stat", 0x0092),
        (CM31, "time_date", 0x0094),
        (CM31, "select_softkeys", 0x0110),
        (CM31, "display", 0x0112),
        (CM31, "config_stat", 0x0093),
        (CM33, "softkey_template", 0x0108),
        (CM33, "line_stat", 0x0092),
        (CM33, "time_date", 0x0094),
    ],
)
def test_cm3x_reg_message_ids(group: str, key: str, expected_id: int):
    assert msg_id(_packet(group, key)) == expected_id


def test_cm31_line_stat_includes_directory_number():
    body = _packet(CM31, "line_stat")[12:]
    assert b"1003" in body


def test_cm33_line_stat_includes_directory_number():
    body = _packet(CM33, "line_stat")[12:]
    assert b"1003" in body


def test_cm33_line_stat_is_longer_than_cm31():
    assert len(_packet(CM33, "line_stat")) > len(_packet(CM31, "line_stat"))


def test_cm31_and_cm33_softkey_templates_differ():
    assert _packet(CM31, "softkey_template") != _packet(CM33, "softkey_template")


def test_cm31_time_date_res_payload_length():
    pkt = _packet(CM31, "time_date")
    data_len = struct.unpack("<I", pkt[:4])[0]
    assert data_len == 40
    assert len(pkt) == 44


def test_cm31_select_softkeys_idle_shape():
    pkt = _packet(CM31, "select_softkeys")
    assert len(pkt) == 24
    body = pkt[12:]
    assert struct.unpack("<II", body[:8]) == (0, 0)
