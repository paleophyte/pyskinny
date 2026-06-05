"""CM2 call state when CM omits CallState Hold / OnHook."""

from __future__ import annotations

import struct
import threading
from types import SimpleNamespace

import messages  # noqa: F401

from messages.phone import parse_set_lamp, parse_stop_media_transmission
from state import PhoneState
from utils.call_management import mark_call_connected


def _client_with_call() -> SimpleNamespace:
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    client = SimpleNamespace(
        state=state,
        events=SimpleNamespace(
            call_connected=threading.Event(),
            call_ended=threading.Event(),
            call_ringing=threading.Event(),
            media_started=threading.Event(),
        ),
    )
    mark_call_connected(client, "cm2-1", line_instance=1)
    client.state.media_active = True
    return client


def test_set_lamp_hold_mode_marks_call_held():
    client = _client_with_call()
    parse_set_lamp(client, struct.pack("<III", 9, 1, 4))
    assert client.state.calls["cm2-1"]["call_state"] == 8
    assert client.state.calls["cm2-1"]["call_state_name"] == "Hold"


def test_stop_media_alone_does_not_mark_hold():
    client = _client_with_call()
    parse_stop_media_transmission(client, struct.pack("<III", 0, 0, 0))
    assert client.state.calls["cm2-1"]["call_state"] == 5
    assert client.state.media_active is False


def test_set_lamp_off_ends_active_call_on_remote_hangup():
    client = _client_with_call()
    parse_set_lamp(client, struct.pack("<III", 9, 1, 1))
    assert "cm2-1" not in client.state.active_calls_list
    assert client.state.calls["cm2-1"]["call_state"] == 2
    assert client.events.call_ended.is_set()


def test_set_lamp_on_resumes_from_hold():
    client = _client_with_call()
    parse_set_lamp(client, struct.pack("<III", 9, 1, 4))
    parse_set_lamp(client, struct.pack("<III", 9, 1, 2))
    assert client.state.calls["cm2-1"]["call_state"] == 5


def test_set_lamp_off_ignored_with_multiple_calls_on_line():
    client = _client_with_call()
    mark_call_connected(client, "cm2-2", line_instance=1)
    parse_set_lamp(client, struct.pack("<III", 9, 1, 1))
    assert "cm2-1" in client.state.active_calls_list
    assert "cm2-2" in client.state.active_calls_list
