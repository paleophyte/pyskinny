"""Helpers for rtp_loopback flag on PhoneState."""

from __future__ import annotations

from state import PhoneState, apply_media_options


def test_rtp_loopback_defaults_false():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    assert state.rtp_loopback is False
    assert state.rtp_loopback_monitor is False


def test_apply_media_options_from_args():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    args = type("Args", (), {"rtp_loopback": True, "rtp_loopback_monitor": True})()
    apply_media_options(state, args, None)
    assert state.rtp_loopback is True
    assert state.rtp_loopback_monitor is True


def test_apply_media_options_ivr_lab_defaults():
    import argparse

    from utils.cli_media import add_media_cli_args

    parser = argparse.ArgumentParser()
    add_media_cli_args(parser)
    args = parser.parse_args([])
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    state.enable_audio = True  # exercise defaults even when pytest --no-audio is set
    apply_media_options(state, args, None)
    assert state.kv_dict.get("audio_play_mode") == "mic"
    assert state.rtp_loopback_monitor is True
    assert state.rtp_loopback is False


def test_apply_media_options_no_audio_skips_defaults():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    args = type("Args", (), {"no_audio": True})()
    apply_media_options(state, args, None)
    assert state.enable_audio is False
    assert state.kv_dict.get("audio_play_mode") is None
