"""Mic TX falls back to silence when no PortAudio input device."""

from __future__ import annotations

import logging

from audio_worker import RTPSender, _resolve_input_device


def test_resolve_input_device_rejects_negative(monkeypatch):
    class _FakeSd:
        default = type("D", (), {"device": (-1, -1)})()

    monkeypatch.setitem(__import__("sys").modules, "sounddevice", _FakeSd())
    assert _resolve_input_device() is None
    assert _resolve_input_device(-1) is None


def test_send_microphone_falls_back_to_silence(monkeypatch):
    monkeypatch.setattr("audio_worker._resolve_input_device", lambda device=None: None)
    log = logging.getLogger("test.mic_fallback")
    tx = RTPSender("127.0.0.1", 9, log=log)
    tx.send_microphone()
    from audio_worker import SilenceSource

    assert isinstance(tx._source, SilenceSource)
