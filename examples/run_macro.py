import argparse
import logging
import os
import sys
import threading

from client import SCCPClient
from ui.macro_cli import parse_macro_script, run_macro
from utils.cli_media import add_connection_cli_args, add_media_cli_args, init_phone_state_from_args
from utils.cli_web import add_web_cli_args, start_client_web_from_args, stop_client_web
from utils.client import write_json_to_file
from utils.logs import add_logging_cli_args, configure_logging_from_verbose, ensure_message_log_level


class GracefulExit:
    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop_event.set()
        return False


def preprocess_macro_text(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def load_macro_text(macro_arg: str | None, macro_file: str | None) -> str:
    if macro_file:
        path = os.path.expanduser(macro_file)
        with open(path, "r", encoding="utf-8") as f:
            return preprocess_macro_text(f.read())
    if macro_arg and macro_arg.startswith("@"):
        path = os.path.expanduser(macro_arg[1:])
        with open(path, "r", encoding="utf-8") as f:
            return preprocess_macro_text(f.read())
    return macro_arg or ""


def main():
    stop_event = threading.Event()
    parser = argparse.ArgumentParser(description="Macro CLI for SCCPClient")
    add_connection_cli_args(parser)
    add_media_cli_args(parser)
    add_web_cli_args(parser)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--macro", help="Macro script string, or @path to a .ivr file")
    group.add_argument("--macro-file", help="Path to a .macro file")

    add_logging_cli_args(parser)

    args = parser.parse_args()
    if not args.config and not (args.server and args.model and (args.mac or args.device)):
        parser.error("Provide --config or explicit --server, --model, and --mac/--device")

    macro_text = load_macro_text(args.macro, args.macro_file)
    log_level = configure_logging_from_verbose(args.verbose, log_file=args.log_file)
    ensure_message_log_level()
    logging.getLogger(__name__).debug("Log level set to: %s", logging.getLevelName(log_level))

    state = init_phone_state_from_args(args)
    client = SCCPClient(state=state)
    ui_lock = threading.Lock()
    web_server = None

    try:
        with GracefulExit(stop_event):
            client.start()

            client.logger.info(f"({client.state.device_name}) Waiting for phone to register...")
            state.is_registered.wait(timeout=30)

            if not state.is_registered.is_set():
                client.logger.error(f"({client.state.device_name}) Phone failed to register in time.")
                return

            web_server = start_client_web_from_args(client, args, lock=ui_lock)

            instructions, labels = parse_macro_script(macro_text)
            run_macro(client, instructions, labels, stop_event)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_client_web(web_server)
        try:
            client.stop()
            write_json_to_file("logs/client_state.json", client.state.to_dict())
        except Exception as e:
            print("Exception occurred:", e)


if __name__ == "__main__":
    main()
