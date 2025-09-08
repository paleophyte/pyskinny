import argparse
import curses
import time
import threading

from client import SCCPClient
from state import PhoneState
from messages.generic import handle_keypad_press


def _maybe_load_config():
    """Return a dict or None using config.load_config() if present."""
    try:
        from config import load_config  # type: ignore
    except Exception:
        return None
    try:
        return load_config()
    except Exception:
        return None


def build_state_from_args(args) -> PhoneState:
    # Prefer a project-specific loader if available (lets you keep your existing config).
    cfg = None
    if args.config:
        cfg = _maybe_load_config()

    if cfg:
        # Try common keys used across the project; fall back if missing.
        server = cfg.get("server") or cfg.get("cucm_host") or cfg.get("host") or args.server
        mac = cfg.get("device_name") or cfg.get("mac") or args.mac
        model = cfg.get("model") or cfg.get("phone_model") or args.model or "Cisco 7970"
    else:
        server = args.server
        mac = args.mac
        model = args.model or "Cisco 7970"

    if not server or not mac:
        raise SystemExit("Missing required connection details. Provide --server and --mac (or use --config).")

    # Construct a minimal state; your PhoneState likely accepts these kwargs.
    return PhoneState(server=server, mac=mac, model=model)


class ConsoleApp:
    def __init__(self, client: SCCPClient, line_instance: int = 1):
        self.client = client
        self.line = line_instance
        self.stop_event = threading.Event()
        self.ui_lock = threading.Lock()
        self.softkey_labels = []

    def _refresh_softkeys(self):
        # Build a stable order of softkey labels to map to F1..F12.
        tmpl = getattr(self.client.state, "softkey_template", {}) or {}
        # Keep original order if dict is ordered; otherwise sort by key for stability.
        try:
            items = list(tmpl.items())
        except Exception:
            items = []
        if items and hasattr(tmpl, "keys"):
            ordered = [v.get("label", f"Key{k}") for k, v in items]
        else:
            ordered = []
        # De-dup while preserving order.
        seen = set()
        labels = []
        for lab in ordered:
            if lab and lab not in seen:
                labels.append(lab)
                seen.add(lab)
            if len(labels) >= 12:
                break
        self.softkey_labels = labels

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(100)  # 100ms UI tick

        # Start SCCP
        self.client.start()
        self._refresh_softkeys()

        try:
            last_draw = 0
            while not self.stop_event.is_set():
                now = time.time()
                if now - last_draw > 0.1:
                    self.draw(stdscr)
                    last_draw = now

                try:
                    ch = stdscr.get_wch()
                except curses.error:
                    ch = None

                if ch is None:
                    continue

                # Quit
                if ch in ("q", "Q"):
                    self.stop_event.set()
                    break

                # Digits (DTMF)
                if isinstance(ch, str) and ch in "0123456789*#":
                    if handle_keypad_press:
                        try:
                            # messages.generic expects a "digit code". If it supports raw chars,
                            # it will handle it; otherwise we try to coerce common mapping.
                            d = ch
                            if ch == "*":
                                d = 10
                            elif ch == "#":
                                d = 11
                            elif ch.isdigit():
                                d = int(ch)
                            handle_keypad_press(self.client, self.line, d)
                        except Exception:
                            pass  # no-op on failure so UI stays responsive
                    continue

                # Volume (example: +/- keys)
                if ch in ("+", "="):
                    try:
                        vol = float(getattr(self.client.state, "tone_volume", 0.0)) + 1.0
                        self.client.handle_volume_change(vol)
                    except Exception:
                        pass
                    continue
                if ch in ("-", "_"):
                    try:
                        vol = float(getattr(self.client.state, "tone_volume", 0.0)) - 1.0
                        self.client.handle_volume_change(vol)
                    except Exception:
                        pass
                    continue

                # Softkeys bound to function keys F1..F12
                if isinstance(ch, int) and curses.KEY_F1 <= ch <= curses.KEY_F12:
                    idx = ch - curses.KEY_F1
                    if 0 <= idx < len(self.softkey_labels):
                        label = self.softkey_labels[idx]
                        try:
                            self.client.press_softkey(label, line=self.line, call_ref=0)
                        except Exception:
                            pass
                    continue

                # Beep test
                if ch in ("b", "B"):
                    try:
                        self.client.play_beep()
                    except Exception:
                        pass
                    continue

                # Force refresh softkeys
                if ch in ("r", "R"):
                    self._refresh_softkeys()
                    continue

        finally:
            try:
                self.client.stop()
            except Exception:
                pass
            curses.endwin()

    def draw(self, stdscr):
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        # Header
        dn = getattr(self.client.state, "device_name", "Unknown")
        model = getattr(self.client.state, "model", "")
        server = getattr(self.client.state, "server", "")
        header = f"{dn}  |  {model}  |  CUCM: {server}"
        stdscr.addstr(0, 1, header[: max(1, w - 2)])

        # Prompt / status
        prompt = getattr(self.client.state, "prompt", None) or getattr(self.client.state, "current_prompt", "") or ""
        stdscr.addstr(2, 2, f"Prompt: {prompt}"[: max(1, w - 4)])

        # Active call summary (best-effort; depends on your PhoneState fields)
        try:
            active = bool(getattr(self.client.state, "active_call", False))
            active_line = getattr(self.client.state, "active_call_line_instance", None)
            calls = getattr(self.client.state, "calls", {}) or {}
            call_info = calls.get(str(active_line), {}) if active_line else {}
            remote = call_info.get("remote_name") or call_info.get("called_party") or ""
            call_ref = call_info.get("call_reference", "")
            stdscr.addstr(4, 2, f"Call: {'ACTIVE' if active else '—'}   Line: {active_line or '-'}   Ref: {call_ref or '-'}")
            stdscr.addstr(5, 2, f"Remote: {remote}"[: max(1, w - 4)])
        except Exception:
            pass

        # Softkeys (F1..F12)
        self._refresh_softkeys()
        stdscr.addstr(7, 2, "Softkeys (F1..F12):")
        row = 8
        col = 2
        for i, label in enumerate(self.softkey_labels):
            text = f"F{i+1}:{label}   "
            if col + len(text) >= w - 2:
                row += 1
                col = 2
            if row >= h - 3:
                break
            stdscr.addstr(row, col, text)
            col += len(text)

        # Footer / help
        help1 = "Digits: 0-9 * #   Volume: +/-   Beep: b   Refresh softkeys: r   Quit: q"
        stdscr.addstr(h - 2, 1, help1[: max(1, w - 2)])


def main():
    parser = argparse.ArgumentParser(description="Console Soft Phone (curses) using SCCPClient")
    parser.add_argument("--server", help="CallManager/CUCM server address (overrides config)")
    parser.add_argument("--mac", help="Device name or MAC (e.g., SEPABCDEF012345)")
    parser.add_argument("--model", help="Phone model (e.g., Cisco 7970)")
    parser.add_argument("--line", type=int, default=1, help="Line instance to use for keypad/softkeys")
    parser.add_argument("--config", action="store_true", help="Load connection details via config.load_config()")
    args = parser.parse_args()

    state = build_state_from_args(args)
    client = SCCPClient(state)

    app = ConsoleApp(client, line_instance=args.line)
    curses.wrapper(app.run)


if __name__ == "__main__":
    main()
