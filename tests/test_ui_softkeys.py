"""UI softkey set selection (ring-in, validKeyMask)."""

from __future__ import annotations

from state import PhoneState
from utils.softkeys import ui_softkey_context


def _ring_in_state() -> PhoneState:
    state = PhoneState(model="7970")
    state.softkey_template = {
        "1": {"label": "Answer", "event": 11},
        "2": {"label": "EndCall", "event": 9},
    }
    state.softkey_set_definition = {
        "3": {"0": {"template_index": 11, "template_index_name": "Answer"}},
        "4": {"0": {"template_index": 9, "template_index_name": "EndCall"}},
    }
    state.selected_softkeys = {
        "16777325": {
            "softkeyset_index": 4,
            "validkey_mask": 0x1,
            "call_reference": 16777325,
        },
    }
    state.selected_call_reference = "16777325"
    state.active_calls_list = ["16777325"]
    state.calls = {
        "16777325": {
            "call_state": 4,
            "call_state_name": "RingIn",
            "call_reference": 16777325,
            "line_instance": 1,
        },
    }
    return state


def test_ui_softkey_context_ring_in_prefers_answer_set():
    state = _ring_in_state()
    set_idx, mask = ui_softkey_context(state)
    assert set_idx == 3
    assert mask is None
    labels = [lab for lab, _ in state.get_current_softkeys(set_idx, valid_key_mask=mask)]
    assert labels == ["Answer"]


def test_valid_key_mask_hides_disabled_positions():
    state = PhoneState(model="7970")
    state.softkey_template = {
        "1": {"label": "Hold", "event": 3},
        "2": {"label": "EndCall", "event": 9},
    }
    state.softkey_set_definition = {
        "1": {
            "0": {"template_index": 3},
            "1": {"template_index": 9},
        },
    }
    # Only position 1 (EndCall) enabled
    labels = [lab for lab, _ in state.get_current_softkeys(1, valid_key_mask=0x2)]
    assert labels == ["EndCall"]
