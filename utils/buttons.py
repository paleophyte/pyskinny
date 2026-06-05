"""Button-template helpers for CM2-era phones (ButtonTemplateRes, Stimulus)."""

from __future__ import annotations

from messages.generic import BUTTON_TYPES, STIMULUS_NAMES
from state import PhoneState

# Skinny Stimulus types for features that are not always present as template buttons.
FEATURE_STIMULUS = {
    "Hold": 5,
    "Transfer": 4,
    "NewCall": 7,
    "Redial": 6,
    "Conference": 125,
    "CallPark": 126,
}


def button_type_name(btn_type: int) -> str:
    return BUTTON_TYPES.get(str(btn_type), f"Type {btn_type}")


def format_button_label(
    state: PhoneState,
    *,
    button_pos: int,
    btn_type: int,
    instance: int,
    type_name: str | None = None,
) -> str:
    """Human label for a template button (matches console/web naming)."""
    name = type_name or button_type_name(btn_type)
    if name == "Line":
        line = (state.lines or {}).get(str(instance), {})
        dn = (line.get("line_dir_number") or "").strip()
        return f"Line {instance}" + (f" ({dn})" if dn else "")
    if name == "Speed Dial":
        sd = (state.speed_dials or {}).get(str(instance), {})
        number = sd.get("speed_dial_number") or sd.get("number") or sd.get("speedDialDirNumber")
        return f"Speed Dial {instance}" + (f" ({number})" if number else "")
    return f"{name} (inst {instance})"


def iter_template_buttons(state: PhoneState):
    """Yield sorted (position, meta, label) for each defined template button."""
    template = state.button_template or {}
    for pos in sorted(template.keys(), key=int):
        meta = template[pos]
        btn_type = int(meta.get("type", 255))
        if btn_type == 255:
            continue
        instance = int(meta.get("instance", 0) or 0)
        type_name = meta.get("type_name") or button_type_name(btn_type)
        label = format_button_label(
            state,
            button_pos=int(pos),
            btn_type=btn_type,
            instance=instance,
            type_name=type_name,
        )
        yield int(pos), meta, label


def line_buttons(state: PhoneState) -> list[tuple[int, int, str]]:
    """(position, line_instance, label) for Line buttons."""
    out = []
    for pos, meta, label in iter_template_buttons(state):
        if meta.get("type_name") == "Line" or int(meta.get("type", 0)) == 9:
            out.append((pos, int(meta.get("instance", 1)), label))
    return out


def hold_resume_hints(state: PhoneState) -> dict:
    """
    How to drive hold on button-template phones.

    CM2 Virtual30 templates usually have Line / Park / Redial buttons only.
    Hold is sent as Stimulus type 5 (see STIMULUS_NAMES), not SoftKeyEvent.
    """
    lines = line_buttons(state)
    default_line = lines[0][1] if lines else 1
    return {
        "uses_softkeys": bool(state.softkey_template),
        "uses_buttons": bool(state.button_template) and not state.softkey_template,
        "hold_stimulus": FEATURE_STIMULUS["Hold"],
        "hold_stimulus_name": STIMULUS_NAMES.get(FEATURE_STIMULUS["Hold"], "Hold"),
        "resume_note": "Resume is often the same Hold stimulus (toggle) or Line + off-hook on CM2.",
        "default_line_instance": default_line,
        "line_buttons": lines,
    }
