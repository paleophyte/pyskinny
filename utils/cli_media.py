"""Shared CLI flags for RTP / audio troubleshooting."""

from __future__ import annotations

import argparse


def add_media_cli_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("RTP / audio troubleshooting")
    group.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable local speaker output (dial tone, DTMF beeps, RTP monitor)",
    )
    group.add_argument(
        "--rtp-play-mode",
        choices=("silent", "mic", "tone", "loopback"),
        default=None,
        help="RTP TX mode (default: silent; loopback echoes RX back to remote)",
    )
    group.add_argument(
        "--rtp-mic",
        action="store_true",
        help="Send microphone audio on RTP TX (shorthand for --rtp-play-mode mic)",
    )
    group.add_argument(
        "--rtp-wav",
        default=None,
        metavar="PATH",
        help="Loop a WAV file on RTP TX",
    )
    group.add_argument(
        "--rtp-loopback",
        action="store_true",
        help="Echo received RTP back to the remote party",
    )
    group.add_argument(
        "--rtp-loopback-monitor",
        action="store_true",
        help="With --rtp-loopback, also play received RTP on the local speaker",
    )
    group.add_argument(
        "--rtp-tone",
        action="store_true",
        help="Send a continuous test tone on RTP TX (shorthand for --rtp-play-mode tone)",
    )
    group.add_argument(
        "--rtp-tone-hz",
        type=float,
        default=None,
        metavar="HZ",
        help="Test tone frequency in Hz (default: 1000)",
    )
    group.add_argument(
        "--rtp-record",
        action="store_true",
        help="Record RTP RX/TX to WAV files under logs/rtp/",
    )
    group.add_argument(
        "--rtp-record-dir",
        default=None,
        metavar="DIR",
        help="Directory for RTP recordings (default: logs/rtp)",
    )
    group.add_argument(
        "--rtp-pt",
        type=int,
        default=None,
        metavar="PT",
        help="Force RTP payload type (0=PCMU, 8=PCMA); overrides Skinny compression_type",
    )
