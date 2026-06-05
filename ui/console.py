import curses
import time
import threading
from client import SCCPClient
from messages.generic import handle_keypad_press, handle_button_press, DEVICE_TYPE_MAP
from textwrap import wrap
import logging
from utils.cli_media import init_phone_state_from_args
from utils.client import write_json_to_file


def _fkey_esc_map():
    m = {}
    for n, c in ((1, "P"), (2, "Q"), (3, "R"), (4, "S")):
        fk = getattr(curses, f"KEY_F{n}", None)
        if fk is not None:
            m[f"\x1bO{c}"] = fk
    for n in range(1, 13):
        fk = getattr(curses, f"KEY_F{n}", None)
        if fk is not None:
            m[f"\x1b[{n + 10}~"] = fk
    return m


_FKEY_ESC = _fkey_esc_map()


def _normalize_console_key(ch):
    """Normalize Windows/curses key values to str or KEY_* ints."""
    if ch is None:
        return None
    if isinstance(ch, tuple):
        ch = ch[0] if ch else None
        if ch is None:
            return None
    if isinstance(ch, bytes):
        try:
            ch = ch.decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(ch, int):
        if 32 <= ch <= 126:
            return chr(ch)
        return ch
    if isinstance(ch, str):
        if len(ch) == 1:
            return ch
        if ch in _FKEY_ESC:
            return _FKEY_ESC[ch]
    return ch


class ConsoleApp:
    def __init__(self, *, skip_tftp: bool = False, web_host: str | None = None, web_port: int | None = None):
        self.skip_tftp = skip_tftp
        self.web_host = web_host
        self.web_port = web_port
        self._web_server = None
        self.client = None
        self.line = 1
        self.stop_event = threading.Event()
        self.ui_lock = threading.Lock()
        self.softkey_labels = []
        self.make_logging_handler()

        self.action_labels = []
        self.action_bindings = []
        self.action_page = 0
        self.actions_per_page = 8
        self._last_state_dump = 0.0

        # Attach a curses-backed logging handler to the root logger
        self._log_handler = self.make_logging_handler()
        self._log_handler.setLevel(logging.NOTSET)
        logging.getLogger().addHandler(self._log_handler)

        # --- Log pane state ---
        self._log_lock = threading.Lock()
        self._log_raw = []         # list[str] (unwrapped lines)
        self._log_max = 5000       # cap raw lines for memory
        self._log_scroll = 0       # 0 means bottom
        self._log_follow = True    # auto-follow newest lines

        # --- Active calls selection state ---
        self._selected_call_idx = 0
        self._selected_call_ref = None
        self._was_registered = False

    def _poll_registration(self) -> None:
        """Refresh UI when CM Reset/Restart (or reconnect) changes registration."""
        if not self.client or not self.client.state:
            return
        registered = self.client.state.is_registered.is_set()
        if registered == self._was_registered:
            return
        self._was_registered = registered
        if registered:
            self._selected_call_idx = 0
            self._selected_call_ref = None
            self._refresh_actions()
            self.log("Registered with CallManager")
        else:
            self.action_labels = []
            self.action_bindings = []
            self.log("Reconnecting after Reset/Restart…")

    def log(self, text: str):
        """Append a line into the log pane (thread-safe)."""
        if text is None:
            text = ""
        with self._log_lock:
            self._log_raw.append(str(text))
            if len(self._log_raw) > self._log_max:
                # Trim oldest lines
                excess = len(self._log_raw) - self._log_max
                del self._log_raw[:excess]
        if self._log_follow:
            # Stay following the tail
            self._log_scroll = 0

    # Optional: simple helper to connect Python logging to the pane
    def make_logging_handler(self):
        """Return a logging.Handler that writes into this pane."""
        import logging

        class _PaneHandler(logging.Handler):
            def __init__(self, app):
                super().__init__()
                self.app = app

            def emit(self, record):
                try:
                    msg = self.format(record)
                except Exception:
                    msg = record.getMessage()
                self.app.log(msg)

        h = _PaneHandler(self)
        # fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        fmt = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        h.setFormatter(fmt)
        return h

    # def _refresh_softkeys(self):
    #     if not self.client:
    #         return
    #     if not self.client.state:
    #         return
    #
    #     if not self.client.state.is_registered.is_set():
    #         self.client.state.is_registered.wait(timeout=30)
    #
    #         if not self.client.state.is_registered.is_set():
    #             self.client.stop()
    #             self.client.logger.error(f"({self.client.state.device_name}) Phone failed to register in time.")
    #             return
    #
    #     max_keys = 12
    #     # Build a stable order of softkey labels to map to F1..F12.
    #
    #     labels = []
    #     scr = self.client.state.selected_call_reference
    #     scr_call_state = None
    #     if scr:
    #         scr_call_state = self.client.state.selected_softkeys.get(str(scr), {}).get("softkeyset_index", None)
    #     keys = self.client.state.get_current_softkeys(scr_call_state)
    #     # self.client.logger.info(keys)
    #     for lab in keys:
    #         labels.append(lab[0])
    #         if len(labels) >= max_keys:
    #             break
    #     self.softkey_labels = labels

    def _call_in_progress(self) -> bool:
        state = self.client.state if self.client else None
        if not state:
            return False
        return bool(
            getattr(state, "active_call", False)
            or getattr(state, "media_active", False)
            or getattr(state, "active_calls_list", None)
        )

    def _toggle_hook(self):
        if self._call_in_progress():
            self.client.on_hook()
        else:
            self.client.off_hook()

    def _refresh_actions(self):
        if not self.client or not self.client.state:
            return

        if not self.client.state.is_registered.is_set():
            return

        # Prefer softkeys when present.
        softkey_count = int(getattr(self.client.state, "total_softkey_count", 0) or 0)
        softkey_template = getattr(self.client.state, "softkey_template", {}) or {}

        if softkey_count > 0 or softkey_template:
            self._refresh_softkey_actions()
        else:
            self._refresh_button_actions()

    def _ui_softkey_set(self) -> int | None:
        """Prefer the latest numeric-call SelectSoftKeys set during active calls."""
        state = self.client.state
        if not (getattr(state, "active_call", False) or getattr(state, "active_calls_list", None)):
            return state.selected_softkey_set

        best_idx = None
        best_ref = -1
        for key, meta in (state.selected_softkeys or {}).items():
            if not str(key).isdigit():
                continue
            ref = int(key)
            idx = meta.get("softkeyset_index")
            if idx is not None and ref >= best_ref:
                best_ref = ref
                best_idx = idx
        return best_idx if best_idx is not None else state.selected_softkey_set

    def _refresh_softkey_actions(self):
        labels = []
        bindings = []

        keys = self.client.state.get_current_softkeys(self._ui_softkey_set())

        for lab in keys:
            label = lab[0]
            labels.append(label)
            bindings.append({
                "kind": "softkey",
                "label": label,
            })

        self.action_labels = labels
        self.action_bindings = bindings

    def _refresh_button_actions(self):
        button_template = getattr(self.client.state, "button_template", {}) or {}

        actions = []

        for button_pos, button in sorted(
                button_template.items(),
                key=lambda item: int(item[0])
        ):
            button_type = int(button.get("type", 255))
            instance = int(button.get("instance", 0) or 0)
            type_name = button.get("type_name") or f"Type {button_type}"

            # Skip undefined buttons.
            if button_type == 255:
                continue

            label = self._button_label(
                button_pos=button_pos,
                button_type=button_type,
                type_name=type_name,
                instance=instance,
            )

            actions.append({
                "kind": "button",
                "button_pos": int(button_pos),
                "button_type": button_type,
                "instance": instance,
                "label": label,
            })

        total_pages = max(1, (len(actions) + self.actions_per_page - 1) // self.actions_per_page)
        self.action_page = max(0, min(self.action_page, total_pages - 1))

        start = self.action_page * self.actions_per_page
        end = start + self.actions_per_page
        visible = actions[start:end]

        self.action_labels = [a["label"] for a in visible]
        self.action_bindings = visible

    def _button_label(self, button_pos, button_type, type_name, instance):
        if type_name == "Line":
            line = getattr(self.client.state, "lines", {}).get(str(instance), {})
            dn = line.get("line_dir_number")
            return f"Line {instance}" + (f" {dn}" if dn else "")

        if type_name == "Speed Dial":
            sd = getattr(self.client.state, "speed_dials", {}).get(str(instance), {})
            number = sd.get("speed_dial_number") or sd.get("number")
            return f"SD {instance}" + (f" {number}" if number else "")

        return type_name

    def _press_action(self, action):
        kind = action.get("kind")

        if kind == "softkey":
            label = action["label"]
            _, call_ref = self.client.resolve_call_target(self.line, 0)
            if label == "NewCall":
                call_ref = 0
            self.client.press_softkey(label, line=self.line, call_ref=call_ref)
            return

        if kind == "button":
            button_type = action["button_type"]
            instance = action["instance"]

            # Add this method on SCCPClient if you do not already have it.
            self.client.press_stimulus(button_type, instance)
            return

    def _hangup_active_calls(self, *, notify_server: bool = True) -> None:
        if not self.client or not self.client.state:
            return
        if not self._call_in_progress():
            return
        try:
            from messages.phone import end_local_call
            end_local_call(self.client, source="console-hangup")
        except Exception:
            logging.getLogger(__name__).exception("local media teardown failed")
        if notify_server:
            try:
                _, call_ref = self.client.resolve_call_target(self.line, 0)
                self.client.press_softkey("EndCall", line=self.line, call_ref=call_ref)
            except Exception:
                pass
            try:
                self.client.on_hook()
            except Exception:
                pass

    def _handle_log_scrolling_key(self, ch, page_h):
        """Update scroll state based on keypress. Returns True if consumed."""
        if ch in ("{",):  # Page Up
            self._log_follow = False
            self._log_scroll += max(1, page_h - 1)
            return True
        if ch in ("}",):  # Page Down
            if self._log_scroll > 0:
                self._log_scroll = max(0, self._log_scroll - max(1, page_h - 1))
            if self._log_scroll == 0:
                self._log_follow = True
            return True
        if ch in ("[",):
            self._log_follow = False
            self._log_scroll += 1
            return True
        if ch in ("]",):
            if self._log_scroll > 0:
                self._log_scroll -= 1
            if self._log_scroll == 0:
                self._log_follow = True
            return True
        if ch in ("g",):  # go top
            self._log_follow = False
            # We'll clamp to max in draw when we know total lines
            self._log_scroll = 10**9
            return True
        if ch in ("G",):  # go bottom
            self._log_scroll = 0
            self._log_follow = True
            return True
        if ch in ("\x0c",):  # Ctrl-L: clear
            with self._log_lock:
                self._log_raw.clear()
            self._log_scroll = 0
            self._log_follow = True
            return True
        return False

    def _wrap_log_lines(self, width: int):
        with self._log_lock:
            raw = list(self._log_raw)
        wrapped = []
        if width <= 0:
            return wrapped
        for line in raw:
            if not line:
                wrapped.append("")
                continue
            parts = wrap(line, width=width, drop_whitespace=False, replace_whitespace=False)
            wrapped.extend(parts or [""])
        return wrapped

    def run(self, stdscr, args):
        state = init_phone_state_from_args(args)
        self.client = SCCPClient(state)
        self.client.get_tftp_config = not self.skip_tftp

        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.nodelay(True)
        stdscr.timeout(100)  # 100ms UI tick

        # Start SCCP
        self.client.start()
        self._refresh_actions()

        if self.web_port:
            from ui.client_web import start_client_web

            host = self.web_host or "127.0.0.1"
            self._web_server = start_client_web(
                self.client,
                host=host,
                port=self.web_port,
                line=self.line,
                lock=self.ui_lock,
            )
            display = "127.0.0.1" if host == "0.0.0.0" else host
            self.log(f"Web UI http://{display}:{self.web_port}/")

        try:
            last_draw = 0
            while not self.stop_event.is_set():
                try:
                    ch = stdscr.get_wch()
                except curses.error:
                    ch = None

                if ch is not None:
                    if self._handle_input(stdscr, ch):
                        break

                self._poll_registration()

                now = time.time()
                if now - last_draw > 0.1:
                    self.draw(stdscr)
                    last_draw = now

        finally:
            if self._web_server:
                try:
                    self._web_server.shutdown()
                    self._web_server.server_close()
                except Exception:
                    pass
                self._web_server = None
            try:
                self._hangup_active_calls()
                self.client.stop()
            except Exception:
                logging.getLogger(__name__).exception("shutdown failed")
            curses.endwin()

    def _handle_input(self, stdscr, ch) -> bool:
        """Handle one key; return True to exit main loop."""
        ch = _normalize_console_key(ch)
        if ch is None:
            return False

        h, w = stdscr.getmaxyx()
        log_w = max(32, int(w * 0.40))
        log_h = max(5, h - 4)
        if self._handle_log_scrolling_key(ch, log_h):
            return False

        refs, _ = self._active_calls_snapshot()
        if refs:
            if ch == curses.KEY_UP:
                self._selected_call_idx = max(0, self._selected_call_idx - 1)
                self._selected_call_ref = refs[self._selected_call_idx]
                try:
                    setattr(self.client.state, 'selected_call_reference', self._selected_call_ref)
                except Exception:
                    pass
                return False
            if ch == curses.KEY_DOWN:
                self._selected_call_idx = min(len(refs) - 1, self._selected_call_idx + 1)
                self._selected_call_ref = refs[self._selected_call_idx]
                try:
                    setattr(self.client.state, 'selected_call_reference', self._selected_call_ref)
                except Exception:
                    pass
                return False

        if ch in ("q", "Q", ord("q"), ord("Q")):
            self._hangup_active_calls()
            self.stop_event.set()
            return True

        if isinstance(ch, str) and ch in "0123456789*#":
            try:
                d = ch
                if ch == "*":
                    d = 10
                elif ch == "#":
                    d = 11
                elif ch.isdigit():
                    d = int(ch)
                handle_keypad_press(self.client, self.line, d)
            except Exception:
                logging.getLogger(__name__).exception("keypad failed")
            return False

        if ch in ("+", "="):
            try:
                vol = float(getattr(self.client.state, "tone_volume", 0.0)) + 1.0
                self.client.handle_volume_change(vol)
            except Exception:
                pass
            return False
        if ch in ("-", "_"):
            try:
                vol = float(getattr(self.client.state, "tone_volume", 0.0)) - 1.0
                self.client.handle_volume_change(vol)
            except Exception:
                pass
            return False

        if isinstance(ch, int) and curses.KEY_F1 <= ch <= curses.KEY_F12:
            idx = ch - curses.KEY_F1
            has_softkeys = bool(getattr(self.client.state, "total_softkey_count", 0) or 0)

            if not has_softkeys and idx == self.actions_per_page:
                self.action_page = max(0, self.action_page - 1)
                self._refresh_actions()
                return False

            if not has_softkeys and idx == self.actions_per_page + 1:
                self.action_page += 1
                self._refresh_actions()
                return False

            if 0 <= idx < len(self.action_bindings):
                try:
                    self._press_action(self.action_bindings[idx])
                except Exception:
                    logging.getLogger(__name__).exception("softkey/button failed")
            return False

        if ch in ("b", "B"):
            try:
                self.client.play_beep()
            except Exception:
                pass
            return False

        if ch in ("r", "R"):
            self._refresh_actions()
            try:
                write_json_to_file("logs/client_state.json", self.client.state.to_dict())
            except Exception:
                pass
            return False

        if ch in (" ", "\n", "\r", "`", ord(" ")):
            try:
                self._toggle_hook()
            except Exception:
                logging.getLogger(__name__).exception("hook toggle failed")
            return False

        if ch in ("e", "E", ord("e"), ord("E")) and self._call_in_progress():
            try:
                _, call_ref = self.client.resolve_call_target(self.line, 0)
                self.client.press_softkey("EndCall", line=self.line, call_ref=call_ref)
            except Exception:
                logging.getLogger(__name__).exception("EndCall failed")
            return False

        if ch in ("h", "H"):
            try:
                self._toggle_hold()
            except Exception:
                logging.getLogger(__name__).exception("hold toggle failed")
            return False

        return False

    def draw(self, stdscr):
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        # Layout: left info + softkeys | right log pane
        log_w = max(32, int(w * 0.40))
        left_w = w - log_w - 1  # -1 for divider

        # Header
        dn = getattr(self.client.state, "device_name", "Unknown")
        # model = getattr(self.client.state, "model", "")
        model = DEVICE_TYPE_MAP.get(self.client.state.model)
        server = getattr(self.client.state, "server", "")
        reg = "Registered" if self.client.state.is_registered.is_set() else "Reconnecting…"
        header = f"{dn}  |  {model}  |  CUCM: {server}  |  {reg}"
        stdscr.addstr(0, 1, header[: max(1, left_w - 2)])

        # Prompt / status (left area only)
        prompt = getattr(self.client.state, "prompt", None) or getattr(self.client.state, "current_prompt", "") or ""
        stdscr.addstr(2, 2, f"Prompt: {prompt}"[: max(1, left_w - 4)])

        # Active call summary
        try:
            active = bool(getattr(self.client.state, "active_call", False))
            active_line = getattr(self.client.state, "active_call_line_instance", None)
            calls = getattr(self.client.state, "calls", {}) or {}
            call_info = calls.get(str(active_line), {}) if active_line else {}
            remote = call_info.get("remote_name") or call_info.get("called_party") or ""
            call_ref = call_info.get("call_reference", "")
            stdscr.addstr(4, 2, f"Call: {'ACTIVE' if active else '—'}   Line: {active_line or '-'}   Ref: {call_ref or '-'}"[:left_w-4])
            stdscr.addstr(5, 2, f"Remote: {remote}"[: max(1, left_w - 4)])
        except Exception:
            pass

        # Active Calls panel (left area)
        refs, details = self._active_calls_snapshot()
        self._sync_selected_to_refs(refs)
        left_pos = 70
        stdscr.addstr(0, left_pos, "[ Active Calls ]"[: left_w - 4], curses.A_BOLD)
        row = 1
        for idx, ref in enumerate(refs[: max(0, h - row - 6)]):
            info = details.get(str(ref), {}) or {}
            state_name = info.get("call_state_name") or "-"
            remote = info.get("remote_name") or info.get("called_party") or ""
            dur = ""
            try:
                human_elapsed = getattr(self.client.state, "_human_elapsed", None)
            except Exception:
                human_elapsed = None
            if human_elapsed and info.get("call_started"):
                try:
                    dur = human_elapsed(info.get("call_started"), info.get("call_ended"))
                except Exception:
                    dur = 0 #self._human_elapsed_local(info.get("call_started"), info.get("call_ended"))
            elif info.get("call_started"):
                dur = 0 # self._human_elapsed_local(info.get("call_started"), info.get("call_ended"))
            # held = " HELD" if info.get("held") else ""
            # line_txt = f"{ref}  [{state_name}{held}]  {remote}  {dur}"
            line_txt = f"{ref}  [{state_name}]  {remote}  {dur}"
            attr = curses.A_REVERSE if idx == self._selected_call_idx else curses.A_NORMAL
            stdscr.addstr(row, left_pos, " " * (left_w - 4))
            stdscr.addstr(row, left_pos, line_txt[: max(1, left_w - 4)], attr)
            row += 1

        softkeys_row = max(row + 1, 7)
        # Softkeys (F1..F12)
        # self._refresh_softkeys()
        # stdscr.addstr(softkeys_row, 2, "Softkeys (F1..F12):"[: left_w - 4])
        self._refresh_actions()

        has_softkeys = bool(getattr(self.client.state, "total_softkey_count", 0) or 0)
        if has_softkeys:
            title = "Softkeys (F1..F12):"
        else:
            # title = f"Buttons (F1..F8, F9/F10 page) page {self.action_page + 1}:"
            title = f"Buttons (F1..F{self.actions_per_page}, F{self.actions_per_page+1}/F{self.actions_per_page+2} page) page {self.action_page + 1}:"

        stdscr.addstr(softkeys_row, 2, title[: left_w - 4])

        row = softkeys_row + 1
        col = 2
        # for i, label in enumerate(self.softkey_labels):
        for i, label in enumerate(self.action_labels):
            text = f"F{i+1}:{label}   "
            if col + len(text) >= left_w - 2:
                row += 1
                col = 2
            if row >= h - 3:
                break
            stdscr.addstr(row, col, text[: max(1, left_w - col - 2)])
            col += len(text)

        # Divider
        for y in range(0, h):
            stdscr.addch(y, left_w, curses.ACS_VLINE)

        # Log pane box
        log_x = left_w + 1
        title = "[ Logs ]"
        # Top border/title
        stdscr.addstr(0, log_x + 1, title[: max(1, log_w - 4)], curses.A_BOLD)
        # Compute visible area
        pane_y0 = 1
        pane_y1 = h - 2  # leave room for footer
        pane_h = max(1, pane_y1 - pane_y0 + 1)
        pane_w = log_w - 2  # margins

        # Wrap and determine slice based on scroll
        wrapped = self._wrap_log_lines(pane_w)
        total = len(wrapped)
        # Clamp scroll if needed (e.g., after clear)
        if self._log_scroll < 0:
            self._log_scroll = 0
        if self._log_scroll > max(0, total - pane_h):
            self._log_scroll = max(0, total - pane_h)

        start = max(0, total - pane_h - self._log_scroll)
        end = min(total, start + pane_h)
        visible = wrapped[start:end]

        # Draw the log text
        for i, line in enumerate(visible):
            y = pane_y0 + i
            stdscr.addstr(y, log_x + 1, " " * pane_w)  # clear line region
            stdscr.addstr(y, log_x + 1, line[:pane_w])

        # Footer / help
        # help1 = "Digits: 0-9 * #   Vol: +/-   Beep: b   Refresh: r   Quit: q   [/]/{/}/g/G: scroll logs   Ctrl-L: clear logs"
        help1 = (
            "Digits: 0-9 * #   Hook: Space   EndCall: F1/e   Hold: h   Vol: +/-   "
            "Beep: b   Refresh: r   Quit: q"
        )
        help2 = (
            "[]{}gG: scroll logs   Ctrl-L: clear logs"
        )
        stdscr.addstr(h - 3, 1, help1[: max(1, w - 2)])
        stdscr.addstr(h - 2, 1, help2[: max(1, w - 2)])

    def _active_calls_snapshot(self):
        state = getattr(self.client, 'state', None)
        if not state:
            return [], {}
        refs = list(getattr(state, 'active_calls_list', []) or [])
        refs = [str(r) for r in refs]
        details = dict(getattr(state, 'calls', {}) or {})
        return refs, details

    def _current_call_key(self):
        refs = list(self.client.state.active_calls_list or [])
        if self.client.state.selected_call_reference:
            return str(self.client.state.selected_call_reference)
        if refs:
            return str(refs[0])
        return None

    def _find_button_by_type_name(self, type_name):
        template = getattr(self.client.state, "button_template", {}) or {}

        for _, button in sorted(template.items(), key=lambda item: int(item[0])):
            if button.get("type_name") == type_name:
                return int(button.get("type", 0)), int(button.get("instance", 1) or 1)

        return None, None


    def _toggle_hold(self):
        key = self._current_call_key()
        if not key:
            return

        call = self.client.state.calls.get(key, {})
        if call.get("call_state") == 8 or call.get("call_state_name") == "Hold":
            self.client.press_softkey("Resume")
        else:
            self.client.press_softkey("Hold")

    def _sync_selected_to_refs(self, refs):
        if not refs:
            self._selected_call_idx = 0
            self._selected_call_ref = None
        else:
            if self._selected_call_ref not in refs:
                self._selected_call_idx = min(self._selected_call_idx, max(0, len(refs)-1))
                self._selected_call_ref = refs[self._selected_call_idx]
        try:
            if self.client and self.client.state is not None:
                setattr(self.client.state, 'selected_call_reference', self._selected_call_ref)
        except Exception:
            pass
