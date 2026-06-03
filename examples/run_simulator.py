"""
Run a minimal Skinny CallManager simulator.

Phones / pyskinny clients can register without a real CUCM:

  # Terminal 1
  python -m examples.run_simulator

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
from utils.logs import configure_logging_from_verbose


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal Skinny (SCCP) CallManager simulator")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: all interfaces)")
    parser.add_argument("--port", type=int, default=2000, help="Skinny TCP port (default: 2000)")
    parser.add_argument("--dn-start", type=int, default=1000, help="First auto-assigned DN (default: 1000)")
    parser.add_argument("--name", default="SkinnySim", help="Server name sent in ConfigStatRes")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    configure_logging_from_verbose(args.verbose)

    sim = SkinnySimulator(
        host=args.host,
        port=args.port,
        dn_start=args.dn_start,
        server_name=args.name,
    )

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
