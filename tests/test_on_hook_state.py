"""On-hook clears dangling active_call after NewCall / dial."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from client import SCCPClient
from state import PhoneState


def test_on_hook_clears_active_call_without_call_list():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    state.enable_audio = False
    state.active_call = True
    state.call_active = True
    state.active_call_line_instance = 1
    state.active_calls_list = []

    client = SCCPClient(state)
    client.audio = MagicMock()

    with patch("client.send_onhook"), patch("messages.phone.end_local_call"):
        client.on_hook()

    assert state.active_call is False
    assert state.call_active is False
    assert state.active_call_line_instance == 0
    assert state.selected_call_reference is None
