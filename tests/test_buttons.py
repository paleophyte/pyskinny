"""Button template helpers (CM2 capture)."""

from __future__ import annotations

from types import SimpleNamespace

import messages  # noqa: F401

from messages.capabilities import parse_button_template
from simulator.cm2_assets import CM2_BUTTON_TEMPLATE_RES
from simulator.payloads import normalize_skinny_packet
from state import PhoneState
from utils.buttons import hold_resume_hints, iter_template_buttons


def _load_cm2_template(state: PhoneState) -> None:
    body = normalize_skinny_packet(CM2_BUTTON_TEMPLATE_RES)[12:]
    parse_button_template(SimpleNamespace(state=state), body)
    state.lines = {
        "1": {"line_dir_number": "1091"},
        "2": {"line_dir_number": "1092"},
    }


def test_cm2_template_button_labels():
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    _load_cm2_template(state)
    labels = [lab for _, _, lab in iter_template_buttons(state)]
    assert any(lab.startswith("Line 1") for lab in labels)
    assert any("Call Park" in lab for lab in labels)


def test_cm2_hold_hint_uses_stimulus_five():
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    _load_cm2_template(state)
    hints = hold_resume_hints(state)
    assert hints["uses_buttons"] is True
    assert hints["hold_stimulus"] == 5
    assert len(hints["line_buttons"]) >= 4
