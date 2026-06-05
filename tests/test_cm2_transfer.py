"""CM2 transfer and wire call-ref helpers."""

from __future__ import annotations

import struct
import threading
from types import SimpleNamespace
from unittest.mock import patch

from client import SCCPClient
from messages.generic import handle_keypad_press
from state import PhoneState
from utils.call_management import mark_call_connected, skinny_wire_call_ref


def test_skinny_wire_call_ref_maps_synthetic_key():
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    client = SCCPClient(state)
    mark_call_connected(client, "cm2-1", line_instance=1)
    client.state.calls["cm2-1"]["call_reference"] = 16777225
    assert skinny_wire_call_ref(client, "cm2-1") == 16777225
    assert skinny_wire_call_ref(client, 0) == 16777225 or skinny_wire_call_ref(client, 0) == 0


@patch("messages.generic.send_skinny_message")
def test_keypad_press_never_packs_synthetic_ref(mock_send):
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    client = SCCPClient(state)
    mark_call_connected(client, "cm2-1", line_instance=1)
    client.state.calls["cm2-1"]["call_reference"] = 16777225
    client.state.selected_call_reference = "cm2-1"
    handle_keypad_press(client, 1, 5, "cm2-1")
    body = mock_send.call_args[0][2]
    _btn, _line, wire_ref = struct.unpack("<III", body)
    assert wire_ref == 16777225


@patch("client.handle_button_press")
def test_press_transfer_on_button_phone_uses_stimulus_four(mock_stimulus):
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    state.enable_audio = False
    state.button_template = {"1": {"type": 9, "instance": 1, "type_name": "Line"}}
    client = SCCPClient(state)
    mark_call_connected(client, "cm2-1", line_instance=1)
    client.press_transfer()
    mock_stimulus.assert_called_once_with(client, 4, 1)
