"""ToneThenEchoSource for sim loopback preamble."""

from __future__ import annotations

import numpy as np

from audio_worker import EchoSource, ToneThenEchoSource


def test_tone_then_echo_switches_after_preamble():
    sr = 8000
    echo = EchoSource(sr, delay_ms=0, gain_db=0.0)
    echo.push(np.ones(8000, dtype=np.float32))
    src = ToneThenEchoSource(sr, echo, tone_hz=1000.0, preamble_sec=0.05)

    tone_block = src.read(400)
    assert np.max(np.abs(tone_block)) > 0.01

    echo_block = src.read(800)
    assert np.max(np.abs(echo_block)) > 0.5
