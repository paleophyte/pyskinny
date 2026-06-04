"""Run the mini web UI for Cisco phone HTTP remote control."""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from ui.phone_web import run_server
from utils.logs import configure_logging_from_verbose


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Web UI for 79xx phone HTTP CGI (screenshot + remote control)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default 127.0.0.1; use 0.0.0.0 for LAN access)",
    )
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default 8765)")
    parser.add_argument("--title", default="Phone remote", help="Browser tab title")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args(argv)

    configure_logging_from_verbose(args.verbose)
    logging.getLogger(__name__).info(
        "Open http://%s:%s/ in a browser",
        "127.0.0.1" if args.host == "0.0.0.0" else args.host,
        args.port,
    )

    server = run_server(args.host, args.port, title=args.title, block=False)

    def _stop(*_exc: object) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
