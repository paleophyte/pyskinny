import argparse
from ui.console import ConsoleApp
import curses
import logging
from utils.cli_media import add_connection_cli_args, add_media_cli_args
from utils.logs import add_logging_cli_args, configure_logging_from_verbose
from utils.client import write_json_to_file


def main():
    parser = argparse.ArgumentParser(description="Console Soft Phone (curses) using SCCPClient")
    add_connection_cli_args(parser)
    parser.add_argument("--line", type=int, default=1, help="Line instance to use for keypad/softkeys")
    parser.add_argument("--skip_tftp", action="store_true", help="Skip TFTP file download")
    parser.add_argument(
        "--web-port",
        type=int,
        default=None,
        metavar="PORT",
        help="Serve browser remote control for this console client (default port 8766 if set alone)",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="Bind address for --web-port (use 0.0.0.0 for LAN access in the lab)",
    )
    add_media_cli_args(parser)
    add_logging_cli_args(parser)
    args = parser.parse_args()

    log_level = configure_logging_from_verbose(args.verbose, log_file=args.log_file)
    log = logging.getLogger(__name__)
    log.debug("Log level set to: %s", logging.getLevelName(log_level))
    if args.log_file:
        log.info("Also logging to %s", args.log_file)

    app = ConsoleApp(
        skip_tftp=args.skip_tftp,
        web_host=args.web_host if args.web_port else None,
        web_port=args.web_port,
    )

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
