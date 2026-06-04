"""RTP stats counters and CLI wiring."""

from __future__ import annotations

import struct

import numpy as np

from utils.rtp_stats import RTPStats
from utils.g711 import pcmu_encode_from_float32
from audio_worker import RTPReceiver, RTPSender
from state import PhoneState, apply_media_options


def test_rtp_stats_rx_tx_counts():
    stats = RTPStats()
    stats.note_rx(0, 1, 0x1234, 160, known_codec=True)
    stats.note_rx(0, 3, 0x1234, 160, known_codec=True)  # gap: expected 2
    stats.note_tx(0, 160)
    assert stats.rx_packets == 2
    assert stats.tx_packets == 1
    assert stats.rx_seq_gaps == 1
    assert "rx=2" in stats.summary()


def test_apply_media_options_rtp_stats():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    args = type(
        "Args",
        (),
        {
            "no_audio": False,
            "rtp_play_mode": None,
            "rtp_mic": False,
            "rtp_tone": False,
            "rtp_wav": None,
            "rtp_loopback": False,
            "rtp_loopback_monitor": False,
            "rtp_tone_hz": None,
            "rtp_record": False,
            "rtp_record_dir": None,
            "rtp_pt": None,
            "rtp_stats": True,
            "rtp_stats_interval": 3.0,
        },
    )()
    apply_media_options(state, args, None)
    assert state.rtp_stats is True
    assert state.rtp_stats_interval == 3.0


def test_rtp_receiver_feeds_stats():
    stats = RTPStats()
    rx = RTPReceiver(worker=None, bind_ip="127.0.0.1", port=0)
    rx.attach_stats(stats)
    rx.start()
    pcm = np.zeros(160, dtype=np.float32)
    payload = pcmu_encode_from_float32(pcm)
    header = struct.pack("!BBHII", 0x80, 0, 10, 320, 0xAABBCCDD)
    rx.sock.sendto(header + payload, ("127.0.0.1", rx.port))
    import time
    time.sleep(0.15)
    rx.stop()
    assert stats.rx_packets >= 1
