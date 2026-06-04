"""Skinny compression_type ↔ RTP payload mapping (extensible registry)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaCodecSpec:
    """One Skinny media payload capability and its RTP representation."""

    compression_type: int
    name: str
    rtp_payload_type: int | None
    sample_rate: int = 8000
    encode_supported: bool = False
    decode_supported: bool = False


# Cisco Skinny payload capabilities (OpenReceiveChannel / StartMediaTransmission).
# Add entries here as encode/decode support lands in audio_worker.
SKINNY_CODEC_REGISTRY: dict[int, MediaCodecSpec] = {
    2: MediaCodecSpec(
        2, "G711Alaw64k", rtp_payload_type=8, encode_supported=True, decode_supported=True
    ),
    4: MediaCodecSpec(
        4, "G711Ulaw64k", rtp_payload_type=0, encode_supported=True, decode_supported=True
    ),
    6: MediaCodecSpec(6, "G7231", rtp_payload_type=4, encode_supported=False, decode_supported=False),
    12: MediaCodecSpec(12, "GSM_FR", rtp_payload_type=3, encode_supported=False, decode_supported=False),
    18: MediaCodecSpec(18, "G729", rtp_payload_type=18, encode_supported=False, decode_supported=False),
    19: MediaCodecSpec(19, "G729AnnexA", rtp_payload_type=18, encode_supported=False, decode_supported=False),
}

DEFAULT_SKINNY_COMPRESSION = 4
DEFAULT_CODEC = SKINNY_CODEC_REGISTRY[DEFAULT_SKINNY_COMPRESSION]


def lookup_skinny_compression(compression_type: int) -> MediaCodecSpec | None:
    return SKINNY_CODEC_REGISTRY.get(int(compression_type))


def resolve_rtp_payload_type(
    compression_type: int,
    *,
    override_pt: int | None = None,
) -> tuple[int, MediaCodecSpec, bool]:
    """
    Map Skinny compression_type to RTP PT for TX.

    Returns (payload_type, spec, used_fallback).
    """
    if override_pt is not None:
        spec = lookup_skinny_compression(compression_type) or DEFAULT_CODEC
        return int(override_pt), spec, False

    spec = lookup_skinny_compression(compression_type)
    if spec is None:
        return DEFAULT_CODEC.rtp_payload_type or 0, DEFAULT_CODEC, True

    if spec.rtp_payload_type is None:
        return DEFAULT_CODEC.rtp_payload_type or 0, spec, True

    if not spec.encode_supported:
        # TX path only supports G711 today; keep PT honest but caller should warn.
        return spec.rtp_payload_type, spec, True

    return spec.rtp_payload_type, spec, False


def codec_label(compression_type: int) -> str:
    spec = lookup_skinny_compression(compression_type)
    if spec is None:
        return f"unknown({compression_type})"
    return spec.name
