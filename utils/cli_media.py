"""Shared CLI flags for RTP / audio troubleshooting."""

from __future__ import annotations

import argparse
import sys


def add_connection_cli_args(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    """Connection flags shared by client entry points."""
    parser.add_argument(
        "--config",
        action="store_true",
        help="Load connection details from examples/cli.config",
    )
    parser.add_argument("--server", required=required, help="CallManager/CUCM server address")
    device_group = parser.add_mutually_exclusive_group(required=required)
    device_group.add_argument("--mac", help="MAC address (e.g., ABCDEF012345)")
    device_group.add_argument("--device", help="Full SCCP device name (e.g., SEPABCDEF012345)")
    parser.add_argument("--model", required=required, help="Phone model (e.g., Cisco 7970)")


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
    group.add_argument(
        "--rtp-stats",
        action="store_true",
        help="Log RTP packet counters (summary on media stop; optional periodic updates)",
    )
    group.add_argument(
        "--rtp-stats-interval",
        type=float,
        default=None,
        metavar="SEC",
        help="Log RTP stats every SEC seconds while media is active (default: 5 with --rtp-stats)",
    )


def init_phone_state_from_args(args):
    """Build PhoneState from CLI args + optional config file; apply media flags."""
    from config import load_config, resolve_config_path
    from state import PhoneState, apply_media_options, build_state_from_args

    if getattr(args, "config", None):
        state = build_state_from_args(args)
        cfg_path = resolve_config_path(args.config)
        cfg = load_config(cfg_path) if cfg_path else None
    else:
        server = getattr(args, "server", None)
        model = getattr(args, "model", None)
        mac = getattr(args, "mac", None)
        device = getattr(args, "device", None)
        missing = []
        if not server:
            missing.append("--server")
        if not model:
            missing.append("--model")
        if not (mac or device):
            missing.append("--mac or --device")
        if missing:
            print(
                "Missing required connection details: "
                + ", ".join(missing)
                + ". Use --config or pass explicit connection flags.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        state = PhoneState(server=server, mac=mac, device_name=device, model=model)
        cfg = None

    apply_media_options(state, args, cfg)
    return state
