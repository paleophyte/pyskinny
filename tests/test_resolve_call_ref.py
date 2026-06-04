"""Resolve numeric Skinny call refs from synthetic CallInfo keys."""

from __future__ import annotations

from client import SCCPClient
from state import PhoneState


def test_resolve_call_target_from_synthetic_active_call_key():
    state = PhoneState(model="7970", mac="AABBCCDDEE99", server="127.0.0.1")
    state.active_call = True
    state.active_call_line_instance = 1
    state.active_calls_list = ["cm2-3"]
    state.calls = {
        "cm2-3": {
            "call_reference": 16777218,
            "line_instance": 1,
            "call_state": 5,
        },
        "16777218": {
            "call_reference": 16777218,
            "line_instance": 1,
            "call_state": 5,
        },
    }
    state.selected_call_reference = "cm2-3"
    client = SCCPClient(state)
    client.running = True

    line, ref = client.resolve_call_target(1, "cm2-3")
    assert line == 1
    assert ref == 16777218
