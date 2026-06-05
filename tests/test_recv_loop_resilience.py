"""Recv loop should survive a single bad message handler."""

from __future__ import annotations

from unittest.mock import patch

from client import SCCPClient
from state import PhoneState


def test_recv_loop_continues_after_dispatch_error():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    state.enable_audio = False
    client = SCCPClient(state)
    client.running = True

    dispatched: list[int] = []

    def fake_dispatch(_client, msg_id, _payload):
        dispatched.append(msg_id)
        if len(dispatched) == 1:
            raise ValueError("simulated parse failure")

    reads = iter(
        [
            ("ok", 0x0100, 4, b""),
            ("ok", 0x0101, 4, b""),
            ("closed", None, None, None),
        ]
    )

    with patch("client.dispatch_message", side_effect=fake_dispatch):
        with patch.object(client, "read_skinny_message", side_effect=lambda: next(reads)):
            client._recv_loop()

    assert dispatched == [0x0100, 0x0101]
