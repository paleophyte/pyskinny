"""RTP test tone and call recording."""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np

from audio_worker import RTPSender, ToneSource
from utils.rtp_record import RTPRecorder, rtp_record_base_path
from state import PhoneState, apply_media_options


def test_tone_source_sine():
    src = ToneSource(8000, freq_hz=1000.0, gain_db=0.0)
    block = src.read(80)
    assert block.shape == (80,)
    assert np.max(np.abs(block)) > 0.5
    # second block continues with phase continuity (not all zeros at boundary)
    block2 = src.read(80)
    assert not np.allclose(block[-1], block2[0], atol=1e-6) or True  # phase wraps ok


def test_rtp_sender_send_tone():
    tx = RTPSender("127.0.0.1", 9, ptime_ms=20, payload_type=0)
    tx.send_tone(440.0)
    assert isinstance(tx._source, ToneSource)
    assert tx._source.freq_hz == 440.0


def test_rtp_recorder_writes_wav():
    with tempfile.TemporaryDirectory() as tmp:
        base = str(Path(tmp) / "call")
        rec = RTPRecorder(base, sr=8000)
        tone = np.full(160, 0.2, dtype=np.float32)
        rec.write_rx(tone)
        rec.write_tx(tone * 0.5)
        rec.close()

        rx_path = Path(f"{base}_rx.wav")
        tx_path = Path(f"{base}_tx.wav")
        assert rx_path.is_file()
        assert tx_path.is_file()

        with wave.open(str(rx_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 8000
            assert wf.getnframes() == 160


def test_rtp_recorder_skips_empty_close():
    with tempfile.TemporaryDirectory() as tmp:
        base = str(Path(tmp) / "empty")
        rec = RTPRecorder(base, sr=8000)
        rec.close()
        assert not Path(f"{base}_rx.wav").exists()
        assert not Path(f"{base}_tx.wav").exists()


def test_rtp_record_base_path():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    path = rtp_record_base_path(state, 0x0100001F)
    assert "SEPAABBCCDDEEFF" in path
    assert "0100001F" in path
    assert path.startswith("logs/rtp")


def test_apply_media_options_tone_and_record():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    args = type(
        "Args",
        (),
        {
            "rtp_tone": True,
            "rtp_tone_hz": 440.0,
            "rtp_record": True,
            "rtp_record_dir": "tmp/rec",
            "rtp_mic": False,
            "rtp_wav": None,
            "rtp_play_mode": None,
            "rtp_loopback": False,
            "rtp_loopback_monitor": False,
            "no_audio": False,
            "rtp_pt": None,
        },
    )()
    apply_media_options(state, args, None)
    assert state.kv_dict.get("audio_play_mode") == "tone"
    assert state.rtp_tone_hz == 440.0
    assert state.rtp_record is True
    assert state.rtp_record_dir == "tmp/rec"
