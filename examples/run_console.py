import argparse
from ui.console import ConsoleApp
import curses
import logging
from utils.logs import configure_logging_from_verbose
from utils.client import write_json_to_file


def main():
    parser = argparse.ArgumentParser(description="Console Soft Phone (curses) using SCCPClient")
    parser.add_argument("--server", help="CallManager/CUCM server address (overrides config)")
    device_group = parser.add_mutually_exclusive_group()
    device_group.add_argument("--mac", help="MAC address (e.g., ABCDEF012345)")
    device_group.add_argument("--device", help="Full SCCP device name (e.g., SEPABCDEF012345)")
    parser.add_argument("--model", help="Phone model (e.g., Cisco 7970)")
    parser.add_argument("--line", type=int, default=1, help="Line instance to use for keypad/softkeys")
    parser.add_argument("--config", action="store_true", help="Load connection details from examples/cli.config")
    parser.add_argument("--skip_tftp", action="store_true", help="Skip TFTP file download")
    parser.add_argument(
        "--rtp-loopback",
        action="store_true",
        help="Echo received RTP back to the remote party (for media troubleshooting)",
    )
    parser.add_argument(
        "--rtp-loopback-monitor",
        action="store_true",
        help="With --rtp-loopback, also play received RTP on the local speaker",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase output verbosity (-v = warning, -vv = message, -vvv = info, -vvvv = debug)")
    args = parser.parse_args()

    log_level = configure_logging_from_verbose(args.verbose)
    logging.getLogger(__name__).debug("Log level set to: %s", logging.getLevelName(log_level))

    app = ConsoleApp(skip_tftp=args.skip_tftp)

    # Silence stdout logging once curses UI is up (leave handlers added by ConsoleApp)
    root = logging.getLogger()
    for h in list(root.handlers):
        if type(h).__name__ == "StreamHandler":
            root.removeHandler(h)

    curses.wrapper(app.run, args)

    if app.client and app.client.state:
        write_json_to_file("logs/client_state.json", app.client.state.to_dict())


if __name__ == "__main__":
    main()
