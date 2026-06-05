"""CM2 hold state inference when CM omits CallState Hold."""

from __future__ import annotations

import struct
import threading
from types import SimpleNamespace

import messages  # noqa: F401

from messages.phone import parse_stop_media_transmission
from state import PhoneState
from utils.call_management import mark_call_connected


def test_stop_media_transmission_marks_connected_call_held():
    state = PhoneState(server="10.0.0.11", device_name="pyskinny01", model="Virtual30SPplus")
    client = SimpleNamespace(
        state=state,
        events=SimpleNamespace(
            call_connected=threading.Event(),
            call_ended=threading.Event(),
            call_ringing=threading.Event(),
            media_started=threading.Event(),
        ),
    )
    mark_call_connected(client, "cm2-1", line_instance=1)
    client.state.media_active = True

    parse_stop_media_transmission(client, struct.pack("<III", 0, 0, 0))

    assert state.calls["cm2-1"]["call_state"] == 8
    assert state.calls["cm2-1"]["call_state_name"] == "Hold"
    assert state.media_active is False
