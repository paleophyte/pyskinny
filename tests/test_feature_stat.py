"""FeatureStatReq / FeatureStatRes registration sequence."""

from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import messages.capabilities  # noqa: F401 — register handlers
from dispatcher import message_handlers
from messages.capabilities import parse_feature_stat_res, send_stat_requests_2
from messages.phone import send_open_receive_channel_ack


def test_open_receive_channel_ack_is_not_inbound_handler():
    entry = message_handlers.get(0x0034)
    if entry is not None:
        assert entry["handler"] is not send_open_receive_channel_ack
    assert callable(send_open_receive_channel_ack)


def test_send_stat_requests_2_includes_feature_stat_req():
    client = SimpleNamespace(
        state=SimpleNamespace(
            device_name="SEPTEST",
            line_count=2,
            button_template={"1": {"type": 9, "instance": 1}},
        ),
        sock=MagicMock(),
        logger=MagicMock(),
    )
    sent: list[tuple[int, bytes | None]] = []

    def _capture_send(client, msg_id, trailing_data=None, **kwargs):
        sent.append((msg_id, trailing_data))

    with patch("messages.capabilities.send_skinny_message", side_effect=_capture_send):
        with patch("messages.capabilities.get_skinny_message", return_value=b""):
            send_stat_requests_2(client, b"")

    msg_ids = [mid for mid, _ in sent]
    assert 0x0034 in msg_ids
    assert msg_ids.index(0x0034) < msg_ids.index(0x000D)


def test_parse_feature_stat_res_accepts_legacy_payload():
    state = SimpleNamespace(device_name="SEPTEST", feature_stat_count=0)
    client = SimpleNamespace(state=state)
    payload = struct.pack("<II", 1, 0) + (b"\x00" * 44)

    parse_feature_stat_res(client, payload)

    assert state.feature_stat_count == 1
