"""Softkey template lookup for console / CLI actions."""

from __future__ import annotations

from state import PhoneState


def test_get_current_softkeys_resolves_by_event_id():
    state = PhoneState(model="7970")
    state.softkey_template = {
        "1": {"label": "Redial", "event": 1},
        "2": {"label": "NewCall", "event": 2},
        "3": {"label": "Answer", "event": 11},
        "4": {"label": "Hold", "event": 3},
        "5": {"label": "Resume", "event": 10},
        "6": {"label": "EndCall", "event": 9},
        "7": {"label": "Transfer", "event": 4},
    }
    state.softkey_set_definition = {
        "1": {
            "0": {
                "template_index": 3,
                "template_index_name": "Hold",
                "info_index": 303,
                "template_info_name": "Hold",
            },
            "1": {
                "template_index": 9,
                "template_index_name": "EndCall",
                "info_index": 309,
                "template_info_name": "EndCall",
            },
            "2": {
                "template_index": 4,
                "template_index_name": "Transfer",
                "info_index": 304,
                "template_info_name": "Transfer",
            },
        },
        "4": {
            "0": {
                "template_index": 9,
                "template_index_name": "EndCall",
                "info_index": 309,
                "template_info_name": "EndCall",
            },
        },
    }
    state.selected_softkey_set = 1

    labels = [label for label, _event in state.get_current_softkeys()]
    assert labels == ["Hold", "EndCall", "Transfer"]

    state.selected_softkey_set = 4
    assert state.get_current_softkeys() == [("EndCall", 9)]
