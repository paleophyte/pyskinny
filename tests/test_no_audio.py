"""Tests for pytest --no-audio (silent test runs)."""

from __future__ import annotations

from state import PhoneState


def test_no_audio_flag_disables_phone_state_audio(request):
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    if request.config.getoption("--no-audio"):
        assert state.enable_audio is False
    else:
        assert state.enable_audio is True
