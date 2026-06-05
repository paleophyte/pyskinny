"""Canonical Skinny (SCCP) message ID -> name registry."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Single source of truth for wire decode / logging. Handlers register here at import
# time via dispatcher.register_handler; sim and decode utilities import this module only.
_SKINNY_MESSAGE_NAMES: dict[int, str] = {
    0x0000: "KeepAliveReq",
    0x0001: "RegisterReq",
    0x0002: "IpPort",
    0x0003: "KeypadButton",
    0x0005: "Stimulus",
    0x0006: "OffHook",
    0x0007: "OnHook",
    0x0008: "HookFlash",
    0x0009: "ForwardStatReq",
    0x000A: "SpeedDialStatReq",
    0x000B: "LineStatReq",
    0x000C: "ConfigStatReq",
    0x000D: "TimeDateReq",
    0x000E: "ButtonTemplateReq",
    0x0010: "CapabilitiesRes",
    0x0020: "Alarm",
    0x0022: "OpenReceiveChannelAck",
    0x0025: "SoftKeySetReq",
    0x0026: "SoftKeyEvent",
    0x0027: "UnregisterReq",
    0x0028: "SoftKeyTemplateReq",
    0x0029: "Reset",
    0x002D: "RegisterAvailableLines",
    0x0030: "Restart",
    0x0034: "FeatureStatReq",
    0x0081: "RegisterAck",
    0x0082: "StartTone",
    0x0083: "StopTone",
    0x0085: "SetRinger",
    0x0086: "SetLamp",
    0x0088: "SetSpeakerMode",
    0x008A: "StartMediaTransmission",
    0x008B: "StopMediaTransmission",
    0x008C: "StartMediaReception",
    0x008D: "StopMediaReception",
    0x008F: "CallInfo",
    0x0090: "ForwardStatRes",
    0x0091: "SpeedDialStatRes",
    0x0092: "LineStatRes",
    0x0093: "ConfigStatRes",
    0x0094: "TimeDateRes",
    0x0097: "ButtonTemplateRes",
    0x0099: "DisplayText",
    0x009B: "CapabilitiesReq",
    0x009D: "RegisterReject",
    0x0100: "KeepAliveAck",
    0x0105: "OpenReceiveChannel",
    0x0106: "CloseReceiveChannel",
    0x0108: "SoftKeyTemplateRes",
    0x0109: "SoftKeySetRes",
    0x0110: "SelectSoftKeys",
    0x0111: "CallState",
    0x0112: "DisplayPromptStatus",
    0x0113: "ClearPromptStatus",
    0x0114: "DisplayNotify",
    0x0116: "ActivateCallPlane",
    0x0118: "UnregisterAck",
    0x011D: "DialedNumber",
    0x011F: "FeatureStatRes",
    0x0120: "DisplayPriNotify",
    0x0130: "CallSelectStatRes",
}


def register_skinny_message_name(msg_id: int, name: str) -> None:
    """Register a handler name; static entries win on conflict."""
    mid = int(msg_id)
    label = str(name).strip()
    if not label:
        return
    existing = _SKINNY_MESSAGE_NAMES.get(mid)
    if existing is None:
        _SKINNY_MESSAGE_NAMES[mid] = label
    elif existing != label:
        logger.debug(
            "Skinny name conflict 0x%04X: keeping %r (ignored %r)",
            mid,
            existing,
            label,
        )


def get_message_name(msg_id: int | None) -> str:
    if msg_id is None:
        return "Unknown"
    mid = int(msg_id)
    name = _SKINNY_MESSAGE_NAMES.get(mid)
    if name:
        return name
    return f"Unknown (0x{mid:04X})"
