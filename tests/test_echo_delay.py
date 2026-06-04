"""EchoSource delay and gain for loopback verification."""

from __future__ import annotations

import numpy as np

from audio_worker import EchoSource


def test_echo_source_applies_delay_and_gain():
    sr = 8000
    echo = EchoSource(sr, delay_ms=100, gain_db=6.0)
    echo.push(np.ones(400, dtype=np.float32))
    silent = echo.read(800)
    assert np.max(np.abs(silent)) == 0.0

    echo.push(np.ones(1200, dtype=np.float32))
    delayed = echo.read(800)
    assert delayed.size == 800
    assert np.max(np.abs(delayed)) > 0.5
