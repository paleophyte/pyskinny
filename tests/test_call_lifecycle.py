"""Call lifecycle tracking — unit + handler dispatch tests."""

from __future__ import annotations

import struct
import threading
from types import SimpleNamespace

import messages  # noqa: F401
import pytest

from state import PhoneState
from utils.call_management import (
    apply_call_state_from_skinny,
    mark_call_connected,
    mark_call_ended,
    mark_call_held,
    mark_call_ringing,
)


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


def _call_state_payload(
    call_state: int,
    line: int,
    call_ref: int,
    *,
    privacy: int = 0,
) -> bytes:
    return struct.pack("<IIIIII", call_state, line, call_ref, privacy, 0, 0)


def test_mark_call_ringing_ringout_vs_ringin():
    client = _FakeClient()
    mark_call_ringing(client, 100, 1, call_state=3)
    assert client.state.calls["100"]["call_state_name"] == "RingOut"
    mark_call_ringing(client, 101, 1, call_state=4)
    assert client.state.calls["101"]["call_state_name"] == "RingIn"


def test_mark_call_held_keeps_other_connected_call():
    client = _FakeClient()
    mark_call_connected(client, 10, line_instance=1)
    mark_call_connected(client, 11, line_instance=1)
    mark_call_held(client, 10, line_instance=1)

    assert client.state.calls["10"]["call_state"] == 8
    assert client.state.calls["11"]["call_state"] == 5
    assert client.state.call_active is True
    assert client.state.call_connected is True
    assert "10" in client.state.active_calls_list
    assert "11" in client.state.active_calls_list


def test_mark_call_ended_one_of_two_calls():
    client = _FakeClient()
    mark_call_connected(client, 20, line_instance=1)
    mark_call_connected(client, 21, line_instance=1)
    mark_call_ended(client, call_reference=21)

    assert "21" not in client.state.active_calls_list
    assert "20" in client.state.active_calls_list
    assert client.state.call_connected is True
    assert client.events.call_ended.is_set() is False


def test_apply_call_state_from_skinny_hold_and_onhook():
    client = _FakeClient()
    apply_call_state_from_skinny(client, 5, 30, 1)
    apply_call_state_from_skinny(client, 8, 30, 1)
    assert client.state.calls["30"]["call_state"] == 8

    apply_call_state_from_skinny(client, 2, 30, 1)
    assert "30" not in client.state.active_calls_list
    assert client.state.calls["30"]["call_state_name"] == "OnHook"


def test_parse_call_state_handler():
    client = _FakeClient()
    from messages.phone import parse_call_state

    parse_call_state(client, _call_state_payload(4, 1, 16777216))
    assert client.state.calls["16777216"]["call_state"] == 4
    assert client.events.call_ringing.is_set()

    parse_call_state(client, _call_state_payload(5, 1, 16777216))
    assert client.state.calls["16777216"]["call_state"] == 5
    assert client.events.call_connected.is_set()

    parse_call_state(client, _call_state_payload(8, 1, 16777216))
    assert client.state.calls["16777216"]["call_state"] == 8
    assert client.state.call_connected is False

    parse_call_state(client, _call_state_payload(2, 1, 16777216))
    assert "16777216" not in client.state.active_calls_list
    assert client.events.call_ended.is_set()


def test_multi_call_onhook_leaves_held_call_active():
    client = _FakeClient()
    apply_call_state_from_skinny(client, 5, 40, 1)
    apply_call_state_from_skinny(client, 8, 40, 1)
    apply_call_state_from_skinny(client, 5, 41, 1)
    apply_call_state_from_skinny(client, 2, 41, 1)

    assert "41" not in client.state.active_calls_list
    assert "40" in client.state.active_calls_list
    assert client.state.calls["40"]["call_state"] == 8
    assert client.state.call_active is True
    assert client.state.call_connected is False
    assert client.events.call_ended.is_set() is False
