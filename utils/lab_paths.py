"""Paths to lab capture and debug artifacts (gitignored under debugs/)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEBUGS = ROOT / "debugs"


def lab_pcap(name: str) -> Path:
    """Resolve a pcap/pcapng under debugs/, with fallback to repo root."""
    preferred = DEBUGS / name
    if preferred.is_file():
        return preferred
    legacy = ROOT / name
    if legacy.is_file():
        return legacy
    return preferred
