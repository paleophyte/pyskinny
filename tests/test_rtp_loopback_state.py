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
