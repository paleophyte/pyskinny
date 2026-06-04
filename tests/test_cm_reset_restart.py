"""Client handling of CM Reset / Restart Skinny messages."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import messages  # noqa: F401
from client import SCCPClient
from dispatcher import dispatch_message
from state import PhoneState


def test_restart_from_cm_reregisters():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEE99", model="7970", port=2000)
    client = SCCPClient(state)
    client.get_tftp_config = False
    client.running = True
    client.sock = MagicMock()
    client.state.is_registered.set()
    state.active_calls_list = []

    connected = threading.Event()
    registered = threading.Event()

    client.connect = MagicMock(side_effect=lambda: connected.set())
    client._start_threads = MagicMock()
    client._send_register = MagicMock(side_effect=lambda: registered.set())
    client._close_skinny_socket = MagicMock()

    dispatch_message(client, 0x0030, b"")
    assert connected.wait(timeout=3)
    assert registered.wait(timeout=3)
    client.connect.assert_called_once()
    client._send_register.assert_called_once()
