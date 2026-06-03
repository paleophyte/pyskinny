"""
Run a minimal Skinny CallManager simulator with optional TFTP.

  # Terminal 1 (port 69 often needs Administrator on Windows)
  python -m examples.run_simulator -v

  # Non-privileged TFTP (pyskinny clients must use matching tftp port)
  python -m examples.run_simulator --tftp-port 6969 -v

  # Terminal 2
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
        help=f"TFTP UDP port (default: {PRIVILEGED_TFTP_PORT}; use 6969 without admin)",
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
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    configure_logging_from_verbose(args.verbose)

    if args.tftp_port == PRIVILEGED_TFTP_PORT and not args.no_tftp:
        logging.info(
            "TFTP port %s requires Administrator/root on most systems; "
            "use --tftp-port 6969 for an unprivileged port.",
            PRIVILEGED_TFTP_PORT,
        )

    sim = SkinnySimulator(
        host=args.host,
        port=args.port,
        dn_start=args.dn_start,
        server_name=args.name,
        tftp=not args.no_tftp,
        tftp_port=args.tftp_port,
        advertise_host=args.advertise_host,
        tftp_root=args.tftp_root,
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
