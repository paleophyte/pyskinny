"""Mic TX falls back to silence when no PortAudio input device."""

from __future__ import annotations

import logging

from audio_worker import MicSource, RTPSender, SilenceSource, _resolve_input_device


def test_resolve_input_device_rejects_negative(monkeypatch):
    class _FakeSd:
        default = type("D", (), {"device": (-1, -1)})()

        @staticmethod
        def query_devices(idx):
            raise OSError(f"Error querying device {idx}")

    monkeypatch.setitem(__import__("sys").modules, "sounddevice", _FakeSd())
    assert _resolve_input_device() is None
    assert _resolve_input_device(-1) is None


def test_send_microphone_falls_back_to_silence(monkeypatch):
    monkeypatch.setattr("audio_worker._resolve_input_device", lambda device=None: None)
    log = logging.getLogger("test.mic_fallback")
    tx = RTPSender("127.0.0.1", 9, log=log)
    tx.send_microphone()
    assert isinstance(tx._source, SilenceSource)


def test_swap_source_mic_portaudio_error_falls_back_to_silence(monkeypatch):
    class _PortAudioError(Exception):
        pass

    class _FakeSd:
        PortAudioError = _PortAudioError

        @staticmethod
        def InputStream(**_kwargs):
            raise _PortAudioError("Error querying device -1")

    monkeypatch.setattr("audio_worker._resolve_input_device", lambda device=None: 0)
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", _FakeSd())
    log = logging.getLogger("test.mic_fallback")
    tx = RTPSender("127.0.0.1", 9, log=log)
    tx.send_microphone()
    assert isinstance(tx._source, SilenceSource)


def test_mic_source_portaudio_error_is_runtime_error(monkeypatch):
    class _PortAudioError(Exception):
        pass

    class _FakeSd:
        PortAudioError = _PortAudioError

        @staticmethod
        def InputStream(**_kwargs):
            raise _PortAudioError("Error querying device -1")

    monkeypatch.setattr("audio_worker._resolve_input_device", lambda device=None: 0)
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", _FakeSd())
    src = MicSource(8000)
    try:
        src.start()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "PortAudio input unavailable" in str(exc)
