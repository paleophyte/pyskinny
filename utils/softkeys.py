"""Resolve CM SoftKeyTemplate / SoftKeySet entries for UI and SoftKeyEvent."""

from __future__ import annotations

from messages.generic import DEFAULT_SOFTKEY_EVENTS, SOFTKEY_TEMPLATE_INDEXES


def resolve_template_by_index(softkey_template: dict, template_index: int) -> dict:
    """
    Map a SoftKeySet softKeyTemplateIndex byte to a template entry.

    CM may use the Cisco enum (3 = Hold), a matching event id, or a 1-based
  position in SoftKeyTemplateRes — try all three.
    """
    if not template_index:
        return {}

    enum_label = SOFTKEY_TEMPLATE_INDEXES.get(int(template_index))
    if enum_label and enum_label != "Undefined":
        for entry in softkey_template.values():
            if entry.get("label") == enum_label:
                return entry

    for entry in softkey_template.values():
        if int(entry.get("event", 0) or 0) == int(template_index):
            return entry

    return softkey_template.get(str(template_index), {}) or {}


def resolve_softkey_event_for_label(softkey_template: dict, label: str) -> int | None:
    """Event id for SoftKeyEvent, from template or DEFAULT_SOFTKEY_EVENTS."""
    for entry in softkey_template.values():
        if entry.get("label") == label:
            event = entry.get("event")
            if event is not None:
                return int(event)
    default = DEFAULT_SOFTKEY_EVENTS.get(label)
    return int(default) if default is not None else None


def template_label_set(softkey_template: dict) -> set[str]:
    return {
        str(entry.get("label"))
        for entry in softkey_template.values()
        if entry.get("label")
    }


def ui_softkey_context(state) -> tuple[int | None, int | None]:
    """
    Softkey set index + validKeyMask for UI (console / web).

    Prefers SelectSoftKeys for the selected or most recent active call ref.
    Falls back to Ring In / Ring Out sets when call state says ringing.
    """
    set_idx: int | None = None
    mask: int | None = None

    refs: list[str] = []
    sel = getattr(state, "selected_call_reference", None)
    if sel:
        refs.append(str(sel))
    for ref in reversed(getattr(state, "active_calls_list", None) or []):
        sref = str(ref)
        if sref not in refs:
            refs.append(sref)

    for ref in refs:
        meta = (getattr(state, "selected_softkeys", None) or {}).get(ref)
        if meta:
            set_idx = meta.get("softkeyset_index")
            mask = meta.get("validkey_mask")
            break

    if refs:
        call = (getattr(state, "calls", None) or {}).get(refs[0], {})
        call_state = call.get("call_state")
        if call_state == 4 and set_idx != 3:
            set_idx = 3
            mask = None
        elif call_state == 3 and set_idx != 8:
            set_idx = 8
            mask = None

    if set_idx is None:
        set_idx = getattr(state, "selected_softkey_set", 0)
    return set_idx, mask


def connected_softkey_labels(softkey_set_definition: dict, softkey_template: dict) -> list[str]:
    """Labels on the Connected softkey set (index 1), if defined."""
    sk_def = softkey_set_definition.get("1", {})
    labels: list[str] = []
    for _k, meta in sorted(sk_def.items(), key=lambda item: int(item[0])):
        entry = resolve_template_by_index(softkey_template, int(meta.get("template_index", 0) or 0))
        label = entry.get("label") or SOFTKEY_TEMPLATE_INDEXES.get(
            int(meta.get("template_index", 0) or 0), ""
        )
        if label and label != "Undefined":
            labels.append(label)
    return labels
