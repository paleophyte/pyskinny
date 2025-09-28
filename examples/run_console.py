import argparse
from ui.console import ConsoleApp
import curses
import logging
from utils.logs import addLoggingLevel
from utils.client import write_json_to_file


MESSAGE_LOG_LEVEL = logging.WARNING - 5
addLoggingLevel('MESSAGE', MESSAGE_LOG_LEVEL)
def message(self, msg, *args, **kws):
    # Yes, logger takes its '*args' as 'args'.
    self._log(MESSAGE_LOG_LEVEL, msg, args, **kws)
logging.Logger.message = message


def enable_logging(args):
    verbosity = min(int(args.verbose), 4)
    log_level = [logging.WARNING, MESSAGE_LOG_LEVEL, logging.INFO, logging.DEBUG][verbosity - 1 if verbosity > 0 else 0]

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] %(name)-22s: %(message)s"
    )
    logging.getLogger("tftpy").setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.debug(f"Log level set to: {logging.getLevelName(log_level)}")


def main():
    parser = argparse.ArgumentParser(description="Console Soft Phone (curses) using SCCPClient")
    parser.add_argument("--server", help="CallManager/CUCM server address (overrides config)")
    parser.add_argument("--mac", help="Device name or MAC (e.g., SEPABCDEF012345)")
    parser.add_argument("--model", help="Phone model (e.g., Cisco 7970)")
    parser.add_argument("--line", type=int, default=1, help="Line instance to use for keypad/softkeys")
    parser.add_argument("--config", action="store_true", help="Load connection details from config file. Default=examples/cli.config")
    parser.add_argument("--skip_tftp", action="store_true", help="Skip TFTP File Download")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase output verbosity (-v = warning, -vv = message, -vvv = info, -vvvv = debug)")
    args = parser.parse_args()

    enable_logging(args)

    app = ConsoleApp()

    # Silence stdout logging once curses UI is up (leave handlers added by ConsoleApp)
    root = logging.getLogger()
    for h in list(root.handlers):
        # Keep any non-StreamHandler (e.g., FileHandler) and the curses handler
        if type(h).__name__ == "StreamHandler":
            root.removeHandler(h)

    # if args.skip_tftp:
    #     logging.debug("Skip TFTP File Download")
    app.get_tftp_config = False

    curses.wrapper(app.run, args)

    if app.client.state:
        write_json_to_file("logs/client_state.json", app.client.state.to_dict())


if __name__ == "__main__":
    main()
