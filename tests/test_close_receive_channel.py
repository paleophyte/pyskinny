"""CloseReceiveChannel tolerates short CM3.x payloads."""

from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock

from messages.phone import parse_close_receive_channel


def test_close_receive_channel_8_byte_payload():
    state = SimpleNamespace(
      _rtp_rx=MagicMock(),
      _rtp_echo_source=object(),
      _rtp_stats_monitor=None,
      _rtp_recorder=None,
    )
    client = SimpleNamespace(state=state)
    rx = state._rtp_rx
    payload = struct.pack("<II", 0, 1665)

    parse_close_receive_channel(client, payload)

    rx.stop.assert_called_once()
    assert state._rtp_rx is None
    assert state._rtp_echo_source is None


def test_close_receive_channel_12_byte_payload():
    state = SimpleNamespace(
      _rtp_rx=MagicMock(),
      _rtp_echo_source=None,
      _rtp_stats_monitor=None,
      _rtp_recorder=None,
    )
    client = SimpleNamespace(state=state)
    rx = state._rtp_rx
    payload = struct.pack("<III", 0, 1665, 16777221)

    parse_close_receive_channel(client, payload)

    rx.stop.assert_called_once()
    assert state._rtp_rx is None
