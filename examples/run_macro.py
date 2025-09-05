import argparse
import json
from ui.macro_cli import parse_macro_script, run_macro
from client import SCCPClient
from config import load_config
from state import PhoneState
from utils.client import write_json_to_file
from utils.logs import addLoggingLevel
import logging
import os, sys, time, threading, signal
import re


LABEL_LINE = re.compile(r'^\s*([A-Za-z_][\w\-]*)\s*:\s*$')


MESSAGE_LOG_LEVEL = logging.WARNING - 5
addLoggingLevel('MESSAGE', MESSAGE_LOG_LEVEL)
def message(self, msg, *args, **kws):
    # Yes, logger takes its '*args' as 'args'.
    self._log(MESSAGE_LOG_LEVEL, msg, args, **kws)
logging.Logger.message = message


class GracefulExit:
    """Context manager: sets up signal handlers and a background key watcher.
       Press Esc or 'q' (or send SIGINT/SIGTERM) to set stop_event."""
    def __init__(self, stop_event: threading.Event, keys=(b'\x1b', b'q', b'Q')):
        self.stop_event = stop_event
        self.keys = keys
        self._thr = None
        self._tty_state = None

    # --- signals ---
    def _on_signal(self, signum, frame):
        # Idempotent
        self.stop_event.set()
        print(f"\n[GracefulExit] received signal {signum} → stopping...", flush=True)

    # --- key watcher ---
    def _run_windows(self):
        import msvcrt
        while not self.stop_event.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in self.keys:
                    self.stop_event.set()
                    break
            time.sleep(0.05)

    def _run_posix(self):
        import termios, tty, select
        fd = sys.stdin.fileno()
        if not sys.stdin.isatty():
            # No TTY (e.g., piping output) — skip key watching
            return
        old = termios.tcgetattr(fd)
        self._tty_state = (fd, old)
        try:
            tty.setcbreak(fd)  # non-blocking single-char reads
            while not self.stop_event.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if r:
                    ch = sys.stdin.read(1).encode("utf-8", errors="ignore")
                    if ch in self.keys:
                        self.stop_event.set()
                        break
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass

    def __enter__(self):
        # signals
        signal.signal(signal.SIGINT, self._on_signal)
        try:
            signal.signal(signal.SIGTERM, self._on_signal)
        except Exception:
            pass  # not available on some platforms

        # background key thread
        self._thr = threading.Thread(
            target=self._run_windows if os.name == "nt" else self._run_posix,
            name="GracefulExitKeyWatcher",
            daemon=True
        )
        self._thr.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop_event.set()
        # thread is daemon; will exit on process end
        # TTY state restored in _run_posix finally-block


def preprocess_macro_text(text: str) -> str:
    """
    Turn a multi-line MACRO script into a comma-separated macro string:
      - supports labels:  NAME:
      - strips blank lines and comments (#... or //...)
      - keeps each non-label line as-is
    """
    tokens = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#') or line.startswith('//'):
            continue
        # allow simple inline comments after ' #' or ' //'
        for marker in (' //', ' #'):
            idx = line.find(marker)
            if idx != -1:
                line = line[:idx].rstrip()
        if not line:
            continue
        m = LABEL_LINE.match(line)
        if m:
            tokens.append(f"{m.group(1)}:")
        else:
            tokens.append(line)
    # parse_macro_script already handles commas; we join with commas here
    return ','.join(tokens)

def load_macro_text(macro_arg: str | None, macro_file: str | None) -> str:
    """
    Returns macro text suitable for parse_macro_script().
    - If macro_file is given, read and preprocess it.
    - If macro_arg starts with '@', treat the rest as a file path.
    - Otherwise, return macro_arg as-is (one-liner).
    """
    if macro_file:
        path = os.path.expanduser(macro_file)
        with open(path, 'r', encoding='utf-8') as f:
            return preprocess_macro_text(f.read())
    if macro_arg and macro_arg.startswith('@'):
        path = os.path.expanduser(macro_arg[1:])
        with open(path, 'r', encoding='utf-8') as f:
            return preprocess_macro_text(f.read())
    return macro_arg or ""


def main():
    stop_event = threading.Event()
    parser = argparse.ArgumentParser(description="Macro CLI for SCCPClient")
    parser.add_argument("--server", required=True, help="CallManager/CUCM server address")
    parser.add_argument("--mac", required=True, help="MAC address of the phone")
    parser.add_argument("--model", required=True, help="Phone model")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--macro", help="Macro script string, or @path to a .ivr file")
    group.add_argument("--macro-file", help="Path to a .macro file")

    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase output verbosity (-v = warning, -vv = message, -vvv = info, -vvvv = debug)")

    args = parser.parse_args()
    server = args.server
    mac = args.mac
    model = args.model
    macro_text = load_macro_text(args.macro, args.macro_file)
    verbosity = min(int(args.verbose), 4)
    log_level = [logging.WARNING, MESSAGE_LOG_LEVEL, logging.INFO, logging.DEBUG][verbosity - 1 if verbosity > 0 else 0]

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] %(name)-22s: %(message)s"
    )
    logging.getLogger("tftpy").setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.debug(f"Log level set to: {logging.getLevelName(log_level)}")

    state = PhoneState(server=server, mac=mac, model=model)
    client = SCCPClient(state=state)

    try:
        with GracefulExit(stop_event):
            client.start()

            client.logger.info(f"({client.state.device_name}) Waiting for phone to register...")
            state.is_registered.wait(timeout=30)

            if not state.is_registered.is_set():
                client.logger.error(f"({client.state.device_name}) Phone failed to register in time.")
                return

            instructions, labels = parse_macro_script(macro_text)
            run_macro(client, instructions, labels, stop_event)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        # graceful teardown
        try:
            client.stop()
            write_json_to_file("logs/client_state.json", client.state.to_dict())
        except Exception as e:
            print("Exception occurred:", e)


if __name__ == "__main__":
    main()
