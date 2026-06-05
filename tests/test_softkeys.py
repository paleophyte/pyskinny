"""SoftKey template / set resolution helpers."""

from __future__ import annotations

from state import PhoneState
from utils.softkeys import (
    connected_softkey_labels,
    resolve_softkey_event_for_label,
    resolve_template_by_index,
)


def test_resolve_template_by_enum_label_when_event_is_info_index():
    template = {
        "1": {"label": "Hold", "event": 303},
        "2": {"label": "EndCall", "event": 309},
    }
    hold = resolve_template_by_index(template, 3)
    assert hold.get("label") == "Hold"
    assert resolve_softkey_event_for_label(template, "Hold") == 303


def test_connected_set_uses_enum_not_wire_position():
    state = PhoneState(model="7970")
    state.softkey_template = {
        "1": {"label": "Redial", "event": 1},
        "2": {"label": "NewCall", "event": 2},
        "3": {"label": "Answer", "event": 11},
        "4": {"label": "Hold", "event": 303},
        "5": {"label": "EndCall", "event": 309},
    }
    state.softkey_set_definition = {
        "1": {
            "0": {"template_index": 3, "template_index_name": "Hold"},
            "1": {"template_index": 9, "template_index_name": "EndCall"},
        },
    }
    assert connected_softkey_labels(state.softkey_set_definition, state.softkey_template) == [
        "Hold",
        "EndCall",
    ]
    labels = [lab for lab, _ in state.get_current_softkeys(1)]
    assert labels == ["Hold", "EndCall"]
