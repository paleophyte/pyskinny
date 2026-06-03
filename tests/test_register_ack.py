import struct
import threading
from types import SimpleNamespace

import messages  # noqa: F401 — register handlers
from messages.register import parse_register_ack
from state import PhoneState


class _FakeClient:
    def __init__(self):
        self.state = PhoneState(server="10.0.0.1", mac="222233334444", model="7970")
        self.running = True


def test_parse_register_ack_minimal_payload():
    client = _FakeClient()
    payload = struct.pack("<I", 30)
    payload += b"MMDDYY"
    payload += struct.pack("<H", 0)

    parse_register_ack(client, payload)

    assert client.state.keepalive_interval == 30
    assert client.state.date_template == "MMDDYY"


def test_parse_register_ack_extended_payload():
    client = _FakeClient()
    payload = struct.pack("<I", 25)
    payload += b"YYMMDD"
    payload += struct.pack("<H", 0)
    payload += struct.pack("<I", 25)  # second keepalive
    payload += struct.pack("<BBH", 5, 0, 0x00AB)

    parse_register_ack(client, payload)

    assert client.state.second_keepalive_interval == 25
    assert client.state.feature_flags == 0x00AB
