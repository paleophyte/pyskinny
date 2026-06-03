import threading
from types import SimpleNamespace

import pytest

from state import PhoneState
from utils.call_management import mark_call_connected, mark_call_ended, update_call_state


class _FakeClient:
    def __init__(self):
        self.state = PhoneState(server="10.0.0.1", mac="222233334444", model="7970")
        self._call_epoch = 0
        self.events = SimpleNamespace(
            call_ringing=threading.Event(),
            call_connected=threading.Event(),
            media_started=threading.Event(),
            call_ended=threading.Event(),
        )


def test_update_call_state_tracks_reference():
    client = _FakeClient()
    key = update_call_state(
        client,
        call_reference=16777221,
        line_instance=1,
        call_state=5,
        call_state_name="Connected",
        source="test",
    )
    assert key == "16777221"
    assert client.state.calls[key]["call_state_name"] == "Connected"
    assert key in client.state.calls_list


def test_mark_call_connected_sets_events():
    client = _FakeClient()
    mark_call_connected(client, call_reference=99, line_instance=1)
    assert client.state.call_connected is True
    assert client.events.call_connected.is_set()
    assert "99" in client.state.active_calls_list


def test_mark_call_ended_clears_active_list():
    client = _FakeClient()
    mark_call_connected(client, call_reference=42, line_instance=1)
    mark_call_ended(client, call_reference=42)
    assert "42" not in client.state.active_calls_list
    assert client.state.call_connected is False
    assert client.events.call_ended.is_set()
