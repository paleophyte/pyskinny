"""
Run a minimal Skinny CallManager simulator with optional TFTP.

  # Simulator TFTP on 6969 (no admin needed)
  python -m examples.run_simulator -v --tftp-port 6969

  # Optional admin terminal — phones still hit port 69
  python -m simulator.tftp_relay

  # Client
  python -m examples.run_cli
  phone# set server 127.0.0.1
  phone# set mac AABBCCDDEEFF
  phone# set model 7970
  phone# connect
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from simulator.server import SkinnySimulator
from simulator.tftp_service import PRIVILEGED_TFTP_PORT
from utils.logs import configure_logging_from_verbose


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal Skinny (SCCP) CallManager simulator")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address for Skinny + TFTP (default: all interfaces)")
    parser.add_argument("--port", type=int, default=2000, help="Skinny TCP port (default: 2000)")
    parser.add_argument("--dn-start", type=int, default=1000, help="First auto-assigned DN (default: 1000)")
    parser.add_argument("--name", default="SkinnySim", help="Server name sent in ConfigStatRes")
    parser.add_argument(
        "--advertise-host",
        default=None,
        help="IP/host written into phone XML (default: --host, or auto-detect if 0.0.0.0)",
    )
    parser.add_argument("--no-tftp", action="store_true", help="Disable embedded TFTP server")
    parser.add_argument(
        "--tftp-port",
        type=int,
        default=PRIVILEGED_TFTP_PORT,
        help=f"TFTP UDP port (default: {PRIVILEGED_TFTP_PORT}, auto-fallback to 6969 if unprivileged)",
    )
    parser.add_argument(
        "--tftp-root",
        default=None,
        help="Directory for generated XML (default: temp dir)",
    )
    parser.add_argument(
        "--provision",
        action="append",
        metavar="MAC",
        default=[],
        help="Pre-generate SEP config for MAC (repeatable; for hardware phones that TFTP before Skinny)",
    )
    parser.add_argument(
        "--auto-answer",
        action="append",
        metavar="MAC",
        default=[],
        help="Auto-answer incoming calls for MAC/SEP (repeatable)",
    )
    parser.add_argument(
        "--auto-answer-all",
        action="store_true",
        help="Auto-answer incoming calls on every registered phone",
    )
    parser.add_argument(
        "--rtp-sim-peer",
        choices=("off", "tone", "loopback", "bridge"),
        default="off",
        help="Simulator hosts RTP: tone=play test tone, loopback=echo each leg, bridge=relay A<->B",
    )
    parser.add_argument(
        "--rtp-sim-tone-hz",
        type=float,
        default=1000.0,
        metavar="HZ",
        help="Tone frequency when --rtp-sim-peer tone (default: 1000)",
    )
    parser.add_argument(
        "--rtp-sim-loopback-delay",
        type=float,
        default=1500.0,
        metavar="MS",
        help="Loopback echo delay in ms (default: 1500)",
    )
    parser.add_argument(
        "--rtp-sim-loopback-gain",
        type=float,
        default=12.0,
        metavar="DB",
        help="Loopback echo gain in dB (default: 12)",
    )
    parser.add_argument(
        "--rtp-sim-loopback-preamble",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Play test tone this long before loopback starts (default: 2, 0=off)",
    )
    parser.add_argument(
        "--ivr-dn",
        default=None,
        metavar="DN",
        help="Virtual auto-answer IVR DN (e.g. 9999); single phone can dial for sim RTP tone/loopback",
    )
    parser.add_argument(
        "--admin-port",
        type=int,
        default=8090,
        metavar="PORT",
        help="Web admin UI port for Reset/Restart/bulk (0=disable, default: 8090)",
    )
    parser.add_argument(
        "--no-admin",
        action="store_true",
        help="Disable the web admin UI (same as --admin-port 0)",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    auto_answer = list(args.auto_answer)
    if args.auto_answer_all:
        auto_answer.append("*")

    configure_logging_from_verbose(args.verbose)

    rtp_sim_peer = args.rtp_sim_peer
    if args.ivr_dn and rtp_sim_peer == "off":
        rtp_sim_peer = "loopback"

    sim = SkinnySimulator(
        host=args.host,
        port=args.port,
        dn_start=args.dn_start,
        server_name=args.name,
        tftp=not args.no_tftp,
        tftp_port=args.tftp_port,
        advertise_host=args.advertise_host,
        tftp_root=args.tftp_root,
        auto_answer=auto_answer or None,
        rtp_sim_peer=rtp_sim_peer,
        rtp_sim_tone_hz=args.rtp_sim_tone_hz,
        rtp_sim_loopback_delay_ms=args.rtp_sim_loopback_delay,
        rtp_sim_loopback_gain_db=args.rtp_sim_loopback_gain,
        rtp_sim_loopback_preamble_sec=args.rtp_sim_loopback_preamble,
        ivr_dn=args.ivr_dn,
        admin_port=0 if args.no_admin else args.admin_port,
    )

    for mac in args.provision:
        dn = sim.provision(mac)
        logging.info("Provisioned %s -> DN %s", mac, dn)

    def _stop(*_):
        logging.info("Shutting down simulator...")
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (AttributeError, ValueError):
        pass

    sim.start(background=False)


if __name__ == "__main__":
    main()
