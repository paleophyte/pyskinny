from ui.cli import CLI, CLIPhone, load_cli_spec
from ui.cli_handlers import FUNCTIONS as CLI_FUNCS
from utils.client import write_json_to_file
from utils.logs import addLoggingLevel
import logging
import os, sys, threading
import argparse
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application.current import get_app
from prompt_toolkit.patch_stdout import patch_stdout
import inspect
from prompt_toolkit.application.current import get_app_or_none
import asyncio
try:
    # PTK v3: async run_in_terminal -> returns coroutine
    from prompt_toolkit.application import run_in_terminal as ptk_run_in_terminal
except Exception:  # PTK v2 fallback (sync)
    from prompt_toolkit.shortcuts import run_in_terminal as ptk_run_in_terminal  # type: ignore
from contextlib import contextmanager


_PTK_IMMEDIATE = threading.local()
_PTK_IMMEDIATE.active = False

@contextmanager
def ptk_immediate_logs():
    prev = getattr(_PTK_IMMEDIATE, "active", False)
    _PTK_IMMEDIATE.active = True
    try:
        yield
    finally:
        _PTK_IMMEDIATE.active = prev


MESSAGE_LOG_LEVEL = logging.WARNING - 5
addLoggingLevel('MESSAGE', MESSAGE_LOG_LEVEL)
def message(self, msg, *args, **kws):
    # Yes, logger takes its '*args' as 'args'.
    self._log(MESSAGE_LOG_LEVEL, msg, args, **kws)
logging.Logger.message = message


def run_cli_repl(shell):
    """
    shell = CLI(ctx_or_client, spec, handlers, log_callable)
    """
    def keep_running():
        stop_ev = getattr(getattr(shell, "client", None), "stop_event", None)
        return not (stop_ev and stop_ev.is_set())

    try:
        # Keep the prompt string in one place so we can both display and redraw it.
        prompt_str = "phone# "

        kb = KeyBindings()

        @kb.add('?', eager=True)
        def _(event):
            """
            On '?':
            - Print the current prompt + buffer + '?' on its own line
            - Print contextual help below it
            - Redraw the prompt with the original buffer text (without '?')
            """
            buf = event.current_buffer
            text_before = buf.document.text_before_cursor

            # Build the help query your parser expects.
            # If the user typed a space before '?', treat as subcommand help.
            query = (text_before + '?') if not (text_before and text_before[-1].isspace()) \
                    else (text_before + ' ?')

            def do_help():
                # 1) Echo the line the user "typed": prompt + text + '?'
                sys.stdout.write(f"{prompt_str}{text_before}?")
                sys.stdout.write("\n")

                # 2) Print the help results
                with ptk_immediate_logs():
                    shell.exec_line(query)

                # 3) Ensure a clean blank line after help (optional)
                sys.stdout.write("\n")
                sys.stdout.flush()

            # Print above the prompt, then prompt_toolkit will redraw with original buffer unchanged.
            run_in_terminal_safe(do_help)

            # Do NOT modify buf.text — we want it to stay as `text_before` (e.g., "sh").

        # --- TAB completion binding ---
        @kb.add('tab', eager=True)
        def _(event):
            """
            Tab completion rules:
            - If exactly 1 candidate: complete fully + add a trailing space.
            - If >1 candidates: extend to longest common prefix. If no extension,
              beep and just re-echo the current line on its own row.
            - If 0 candidates: beep.
            """
            app = get_app()
            buf = event.current_buffer
            text_before = buf.document.text_before_cursor

            # Tokenize preserving last partial token. We don’t want shell.exec_line parsing here.
            stripped = text_before.rstrip()
            ends_with_space = (len(text_before) > 0 and text_before[-1].isspace())

            tokens = stripped.split() if stripped else []
            # if there is a trailing space, we’re starting a new token
            if ends_with_space:
                tokens = tokens + [""]

            # Ask CLI for candidates (Option A). Fallback to no-op if missing.
            if hasattr(shell, "candidates_for"):
                cands = shell.candidates_for(tokens)
            else:
                cands = []

            def bell():
                try:
                    app.bell()
                except Exception:
                    # Very old PTK: write \a
                    sys.stdout.write("\a"); sys.stdout.flush()

            # No candidates
            if not cands:
                bell()
                return

            # Current partial (last token)
            partial = tokens[-1] if tokens else ""

            # Single match → complete fully + space
            if len(cands) == 1:
                full = cands[0]
                # replace the partial in the buffer
                if partial:
                    buf.delete_before_cursor(count=len(partial))
                buf.insert_text(full + " ")
                return

            # Multiple matches → extend to longest common prefix
            # Compute LCP safely
            common = os.path.commonprefix(cands)
            if common and len(common) > len(partial):
                # Extend to the common prefix (no trailing space yet)
                if partial:
                    buf.delete_before_cursor(count=len(partial))
                buf.insert_text(common)
                return

            # Still ambiguous and no extension possible → beep + echo current line
            bell()

            def echo_line():
                sys.stdout.write(f"{prompt_str}{text_before}")
                sys.stdout.write("\n")
                sys.stdout.flush()

            run_in_terminal_safe(echo_line)

            # Do not alter buffer; user keeps typing.

        session = PromptSession(key_bindings=kb)
        shell.log("Press '?' for help. Type 'exit' to quit.")

        while keep_running():
            try:
                # line = session.prompt(prompt_str)
                with patch_stdout():
                    line = session.prompt(prompt_str)
            except (EOFError, KeyboardInterrupt):
                break

            s = (line or "").strip()
            if s in ("q", "Q", "exit"):
                break
            shell.exec_line(s)

    except Exception:
        shell.log("Type '?' and press enter for help. Type 'exit' to quit.")
        while keep_running():
            try:
                line = input("phone# ")
            except (EOFError, KeyboardInterrupt):
                break
            s = (line or "").strip()
            if s in ("q", "Q", "exit"):
                break
            shell.exec_line(s)


def run_in_terminal_safe(fn) -> None:
    """
    Schedule fn() to render above the PTK prompt and then redraw it.
    - Works from any thread.
    - PTK v3: creates/schedules the coroutine on the PTK loop thread (no warnings).
    - PTK v2: runs synchronously.
    - If no app/loop running (startup/shutdown), runs inline.
    """
    app = get_app_or_none()
    if app is None or app.is_done:
        fn()
        return

    loop = getattr(app, "loop", None) or getattr(app, "_loop", None)
    if loop is None or not getattr(loop, "is_running", lambda: False)():
        fn()
        return

    def _on_loop():
        try:
            res = ptk_run_in_terminal(fn)   # v3: coroutine; v2: None (already ran)
            if inspect.isawaitable(res):
                # schedule on this loop (we're already on the PTK thread)
                asyncio.create_task(res)
        except Exception:
            # if anything goes sideways, at least do the print
            try:
                # fn()
                pass
            except Exception:
                pass

    # hop to the PTK loop thread; create/schedule there (critical!)
    loop.call_soon_threadsafe(_on_loop)


class PTKConsoleHandler(logging.Handler):
    def __init__(self, *, formatter, flt=None, level=logging.NOTSET):
        super().__init__(level)
        self.setFormatter(formatter)
        if flt:
            self.addFilter(flt)
        self._closing = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._closing:
            return
        msg = self.format(record)

        # If we’re in “immediate” mode (e.g., rendering help), print directly
        if getattr(_PTK_IMMEDIATE, "active", False):
            print(msg, file=sys.stdout, flush=True)
            return

        # never block; schedule printing above the prompt
        run_in_terminal_safe(lambda: print(msg, file=sys.stdout, flush=True))

    def close(self):
        self._closing = True
        super().close()


def _purge_console_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        # remove any console-like handlers we may have left around
        if h.__class__.__name__ in {"PTKConsoleHandler", "StreamHandler"}:
            root.removeHandler(h)


def configure_logging(log_level, MESSAGE_LOG_LEVEL, PTKConsoleHandler):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # let handlers decide visibility
    _purge_console_handlers()

    class OnlyMessageFilter(logging.Filter):
        def filter(self, rec): return rec.levelno == MESSAGE_LOG_LEVEL

    class NotMessageFilter(logging.Filter):
        def filter(self, rec): return rec.levelno != MESSAGE_LOG_LEVEL

    msg_fmt = logging.Formatter("%(message)s")
    std_fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(name)-22s: %(message)s")

    msg_h = PTKConsoleHandler(formatter=msg_fmt, flt=OnlyMessageFilter(), level=logging.DEBUG)
    std_h = PTKConsoleHandler(formatter=std_fmt, flt=NotMessageFilter(), level=log_level)

    root.addHandler(msg_h)
    root.addHandler(std_h)

    # Debug: list handlers once
    # root.debug("Handlers: %s", [type(h).__name__ for h in root.handlers])


def main():
    parser = argparse.ArgumentParser(description="Cisco-like CLI for SCCPClient")
    parser.add_argument("--cli-spec", default="ui/cli_commands.json", help="Path to CLI spec JSON")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    # logging setup
    verbosity = min(int(args.verbose), 4)
    log_level = [logging.WARNING, MESSAGE_LOG_LEVEL, logging.INFO, logging.DEBUG][verbosity - 1 if verbosity > 0 else 0]
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)-7s] %(name)-22s: %(message)s")

    # ---- replace basicConfig with explicit handlers ----
    root = logging.getLogger()
    logging.getLogger("tftpy").setLevel(logging.WARNING)
    # Let all records through the logger; handlers will filter/format.
    root.setLevel(logging.DEBUG)

    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)

    configure_logging(log_level, MESSAGE_LOG_LEVEL, PTKConsoleHandler)

    spec = load_cli_spec(args.cli_spec)
    ctx = CLIPhone(logging.getLogger("cli_phone"))
    cli_obj = CLI(ctx, spec, CLI_FUNCS, ctx.log)

    try:
        run_cli_repl(cli_obj)
    finally:
        # ensure we tear down the client if connected
        if ctx.state:
            write_json_to_file("logs/client_state.json", ctx.state.to_dict())
        try:
            ctx.disconnect()

            root = logging.getLogger()
            for h in list(root.handlers):
                if isinstance(h, PTKConsoleHandler):
                    h.close()
                    root.removeHandler(h)
            logging.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
