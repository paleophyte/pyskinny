"""Skinny compression_type to RTP payload mapping."""

from __future__ import annotations

from utils.media_codecs import (
    DEFAULT_CODEC,
    codec_label,
    lookup_skinny_compression,
    resolve_rtp_payload_type,
)
from state import PhoneState, apply_media_options


def test_g711_ulaw_maps_to_pt0():
    pt, spec, fb = resolve_rtp_payload_type(4)
    assert pt == 0
    assert spec.name == "G711Ulaw64k"
    assert fb is False
    assert spec.encode_supported


def test_g711_alaw_maps_to_pt8():
    pt, spec, _ = resolve_rtp_payload_type(2)
    assert pt == 8
    assert spec.name == "G711Alaw64k"


def test_unknown_compression_falls_back():
    pt, spec, fb = resolve_rtp_payload_type(999)
    assert pt == 0
    assert fb is True
    assert spec is DEFAULT_CODEC


def test_pt_override():
    pt, spec, fb = resolve_rtp_payload_type(4, override_pt=99)
    assert pt == 99
    assert spec.compression_type == 4
    assert fb is False


def test_g729_not_encode_supported():
    spec = lookup_skinny_compression(18)
    assert spec is not None
    assert spec.encode_supported is False
    pt, _, fb = resolve_rtp_payload_type(18)
    assert pt == 18
    assert fb is True


def test_codec_label_unknown():
    assert "unknown" in codec_label(4242)


def test_apply_media_play_mode_and_no_audio():
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    args = type(
        "Args",
        (),
        {
            "no_audio": True,
            "rtp_play_mode": "mic",
            "rtp_mic": False,
            "rtp_tone": False,
            "rtp_wav": None,
            "rtp_loopback": False,
            "rtp_loopback_monitor": False,
            "rtp_tone_hz": None,
            "rtp_record": False,
            "rtp_record_dir": None,
            "rtp_pt": 8,
            "rtp_stats": False,
            "rtp_stats_interval": None,
        },
    )()
    apply_media_options(state, args, None)
    assert state.enable_audio is False
    assert state.kv_dict["audio_play_mode"] == "mic"
    assert state.rtp_pt_override == 8
