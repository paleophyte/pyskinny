"""Default run_console media: silent RTP TX, no microphone open."""

from __future__ import annotations

import argparse
import logging

from audio_worker import RTPSender, SilenceSource
from messages.phone import _configure_rtp_sender
from utils.cli_media import add_connection_cli_args, add_media_cli_args, init_phone_state_from_args


def test_default_console_uses_silent_rtp_tx():
    parser = argparse.ArgumentParser()
    add_connection_cli_args(parser)
    add_media_cli_args(parser)
    args = parser.parse_args(
        ["--server", "10.0.0.181", "--device", "222233334444", "--model", "7960"]
    )
    state = init_phone_state_from_args(args)
    state.enable_audio = True  # exercise defaults even when pytest --no-audio is set
    from state import apply_media_options

    apply_media_options(state, args, None)
    assert state.kv_dict.get("audio_play_mode") == "silent"

    class _Client:
        pass

    client = _Client()
    client.state = state
    client.logger = logging.getLogger("test.default_console_media")

    tx = RTPSender("127.0.0.1", 5004, log=client.logger)
    _configure_rtp_sender(client, tx)
    assert isinstance(tx._source, SilenceSource)
