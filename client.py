import struct
import socket
import threading
import logging
from dispatcher import dispatch_message
from messages.register import send_register_req, send_unregister_req, build_ip_port_message
from messages.keepalive import send_keepalive_req
from state import PhoneState
from utils.tftp import get_device_config_via_tftp
from messages.generic import handle_softkey_press, handle_keypad_press, handle_button_press, TONE_FOLDER, TONE_LOOKUP, send_onhook, send_offhook
from audio_worker import LoopingAudioWorker, NullAudioWorker
import os
import threading
from types import SimpleNamespace
from collections import deque
import time


def _tone_path_from_id(tone_id: int) -> str | None:
    fname = TONE_LOOKUP.get(tone_id)
    return os.path.join(TONE_FOLDER, fname) if fname else None


class SCCPClient:
    def __init__(self, state: PhoneState):
        self.state = state
        self.sock = None
        self.running = False
        self.get_tftp_config = True
        self.logger = logging.getLogger("SCCPClient")
        self.state._prompt_watchers.append(self._on_prompt_changed)
        self._stop_event = threading.Event()
        self._threads = []
        if state.enable_audio:
            self.audio = LoopingAudioWorker(
                samplerate=44100,  # your key_beep.wav was 44.1k in logs
                channels=1,
                blocksize=1024,
                tone_resolver=_tone_path_from_id,
                master_gain_db=state.tone_volume  # optional: treat as master gain
            )
            self.audio.start()
        else:
            self.audio = NullAudioWorker()
        self.events = SimpleNamespace(
            call_ringing=threading.Event(),  # set when Ring-In
            call_connected=threading.Event(),  # set when Connected
            media_started=threading.Event(),  # set on StartMediaTransmission
            call_ended=threading.Event(),   # set when Disconnected
        )
        self.dtmf = SimpleNamespace(
            event=threading.Event(),
            buf=deque(),
            lock=threading.Lock()
        )
        self.state.call_active = False
        self.state.call_connected = False
        self.state.media_active = False
        self._call_epoch = 0
        self.state.last_call_epoch = 0

    def connect(self):
        self.sock = socket.create_connection((self.state.server, self.state.port))
        self.sock.settimeout(1.0)
        self.logger.info(f"({self.state.device_name}) Connected to CUCM; Type={self.state.model}")
        self.running = True
        self._start_threads()

    def _on_prompt_changed(self, old, new):
        self.logger.info(f"({self.state.device_name}) [PROMPT] '{new}'")

    def _start_threads(self):
        t_recv = threading.Thread(target=self._recv_loop, name="pyskinny-recv")
        t_keep = threading.Thread(target=self._keepalive_loop, name="pyskinny-keepalive")
        self._threads = [t_recv, t_keep]
        for t in self._threads:
            t.start()

    def start(self):
        if self.get_tftp_config:
            get_device_config_via_tftp(
                tftp_server=self.state.server,
                device_name=self.state.device_name,
                port=getattr(self.state, "tftp_port", 69),
            )

        self.connect()
        self._send_register()

    def _end_calls_before_unregister(self) -> None:
        attempts = max(3, len(self.state.active_calls_list or []) + 1)
        for _ in range(attempts):
            if not self.state.active_calls_list and not self.state.call_active:
                break
            try:
                self.press_softkey("EndCall")
            except Exception:
                pass
            time.sleep(0.35)

    def stop(self):
        try:
            self._end_calls_before_unregister()
        except Exception:
            pass

        try:
            from messages.phone import _teardown_local_media
            _teardown_local_media(self)
        except Exception:
            pass
        try:
            self.audio.clear_all()
        except Exception:
            pass

        # Unregister while recv/keepalive threads are still running so UnregisterAck is handled.
        self._close_skinny_socket(send_unregister=True)

        self.running = False
        self._stop_event.set()

        for t in self._threads:
            if t.is_alive():
                t.join(timeout=1.5)

        if self.state.is_registered.is_set():
            self.state.is_registered.clear()
        self.state.is_unregistered.set()

        try:
            self.audio.close()
        except Exception:
            pass

    def reregister_from_cm(self, *, hard: bool) -> None:
        """Handle CUCM Reset (hard) or Restart (soft) — TFTP + new RegisterReq."""
        label = "Reset" if hard else "Restart"
        if getattr(self, "_reregister_lock", None) is None:
            self._reregister_lock = threading.Lock()
        if not self._reregister_lock.acquire(blocking=False):
            self.logger.debug(f"({self.state.device_name}) {label} already in progress")
            return

        def worker() -> None:
            try:
                self._perform_cm_reregister(hard=hard, label=label)
            finally:
                self._reregister_lock.release()

        threading.Thread(
            target=worker,
            name=f"pyskinny-cm-{label.lower()}",
            daemon=True,
        ).start()

    def _perform_cm_reregister(self, *, hard: bool, label: str) -> None:
        self.logger.info(f"({self.state.device_name}) CM {label} — re-registering")
        try:
            if self.state.call_active or self.state.active_calls_list:
                try:
                    self.press_softkey("EndCall")
                    time.sleep(0.75)
                except Exception:
                    pass

            try:
                from messages.phone import _teardown_local_media
                _teardown_local_media(self)
            except Exception:
                pass

            self.running = False
            self._stop_event.set()
            self._close_skinny_socket(send_unregister=False)

            for t in list(self._threads):
                if t.is_alive():
                    t.join(timeout=2.0)

            self._stop_event.clear()
            self.state.is_registered.clear()
            self.state.is_unregistered.clear()
            self.state.active_calls_list = []
            self.state.calls.clear()
            self.state.callinfo.clear()
            self.state.selected_softkeys.clear()
            self.state.selected_call_reference = None
            self.state.active_call = False
            self.state.call_active = False
            self.state.call_connected = False
            self.state.media_active = False
            self.events.call_ringing.clear()
            self.events.call_connected.clear()
            self.events.media_started.clear()
            self.events.call_ended.clear()

            if hard:
                time.sleep(1.0)

            if self.get_tftp_config:
                get_device_config_via_tftp(
                    tftp_server=self.state.server,
                    device_name=self.state.device_name,
                    port=getattr(self.state, "tftp_port", 69),
                )

            self.running = True
            self._threads = []
            self.connect()
            self._send_register()
            self.logger.info(f"({self.state.device_name}) CM {label} complete — RegisterReq sent")
        except Exception:
            self.logger.exception(f"({self.state.device_name}) CM {label} failed")
            self.running = False

    def _close_skinny_socket(self, *, send_unregister: bool) -> None:
        sock = self.sock
        if sock:
            try:
                if send_unregister and self.state.is_registered.is_set():
                    self._send_unregister()
                    self.state.is_unregistered.wait(timeout=5.0)
            except Exception:
                pass
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
            self.sock = None

    def _send_unregister(self):
        send_unregister_req(self)

    def _send_register(self):
        msg = send_register_req(self.state)
        self.sock.sendall(msg)
        msg = build_ip_port_message(self.state)
        self.sock.sendall(msg)
        self.logger.info(f"({self.state.device_name}) [SEND] RegisterReq")

    def _keepalive_loop(self):
        self.logger.info(f"({self.state.device_name}) Keepalive Loop Running")
        interval = self.state.keepalive_interval
        while self.running and not self._stop_event.is_set():
            # wait returns True if stop set; exits immediately
            if self._stop_event.wait(timeout=interval):
                break
            try:
                send_keepalive_req(self)
            except Exception:
                # avoid noisy logs during shutdown
                if self.running:
                    self.logger.debug(f"({self.state.device_name}) keepalive send failed", exc_info=True)
                break
        self.logger.info(f"({self.state.device_name}) Keepalive Loop Stopped")

    def handle_volume_change(self, new_db: float):
        self.state.tone_volume = new_db
        self.audio.set_master_gain_db(new_db)

    def play_beep(self):
        if not self.state.enable_audio:
            return
        path = _tone_path_from_id(0)  # your beep tone id
        if path:
            # you can add per-beep gain override: gain_db=self.state.tone_volume
            self.audio.play_wav_once(path, gain_db=0.0)

    def _recv_loop(self):
        try:
            while self.running and not self._stop_event.is_set():
                status, msg_id, data_length, payload = self.read_skinny_message()
                if status == "ok":
                    try:
                        dispatch_message(self, msg_id, payload)
                    except Exception as e:
                        self.logger.error(f"({self.state.device_name}) Unexpected error in dispatch: {e}",
                                          exc_info=True)
                        break
                elif status in ("timeout",):
                    continue  # check flags and loop
                else:  # "closed", "error"
                    break
        finally:
            # Keep this quiet during interpreter shutdown
            try:
                self.logger.info(f"({self.state.device_name}) Shutdown complete")
            except Exception:
                pass

    def read_skinny_message(self):
        # header = sock.recv(12)
        try:
            header = self.sock.recv(12)
        except socket.timeout:
            return "timeout", None, None, None
        except (OSError, ConnectionResetError) as e:
            return "error", None, None, None

        if len(header) < 12:
            return "closed", None, None, None

        data_length, version, msg_id = struct.unpack("<III", header)
        payload_length = data_length - 4  # header includes 4 bytes of length

        payload = b""
        while len(payload) < payload_length:
            try:
                chunk = self.sock.recv(payload_length - len(payload))
            except socket.timeout:
                return "timeout", None, None, None
            except OSError as e:
                return "error", None, None, None

            if not chunk:
                # Connection closed or error
                return "closed", None, None, None
            payload += chunk

        return "ok", msg_id, data_length, payload

    @staticmethod
    def numeric_call_ref(ref) -> int | None:
        """Skinny call refs are numeric; map synthetic keys (cm2-N) via calls dict."""
        if ref is None:
            return None
        if isinstance(ref, int):
            return ref if ref > 0 else None
        s = str(ref).strip()
        if s.isdigit():
            n = int(s)
            return n if n > 0 else None
        return None

    def _call_ref_for_state(self, state: int) -> tuple[int, int] | None:
        """Return (line, ref) for a call in the given Skinny call state."""
        candidates: list[str] = []
        selected = getattr(self.state, "selected_call_reference", None)
        if selected:
            candidates.append(str(selected))
        for key in reversed(self.state.active_calls_list or []):
            sk = str(key)
            if sk not in candidates:
                candidates.append(sk)

        seen: set[str] = set()
        for key in candidates:
            if key in seen:
                continue
            seen.add(key)
            call = self.state.calls.get(key, {})
            if call.get("call_state") != state:
                continue
            line = int(call.get("line_instance") or 1)
            ref = self.numeric_call_ref(key)
            if ref is None:
                ref = self.numeric_call_ref(call.get("call_reference"))
            if ref is not None:
                return line, ref
        return None

    def resolve_call_target(
        self, line=1, call_ref=0, *, softkey_name: str | None = None
    ) -> tuple[int, int]:
        """Resolve line + call reference for softkey/stimulus messages."""
        active_line = line or 1

        if softkey_name == "NewCall":
            return active_line, 0
        if softkey_name == "Resume":
            found = self._call_ref_for_state(8)
            if found:
                return found
        if softkey_name in ("Hold", "EndCall", "Transfer", "Confrn"):
            found = self._call_ref_for_state(5)
            if found:
                return found

        numeric_ref = self.numeric_call_ref(call_ref)

        if numeric_ref is None and call_ref:
            call = self.state.calls.get(str(call_ref), {})
            numeric_ref = self.numeric_call_ref(call.get("call_reference"))

        if numeric_ref is None and self.state.active_call:
            active_line = getattr(self.state, "active_call_line_instance", None) or active_line
            candidates = [
                getattr(self.state, "selected_call_reference", None),
                *(self.state.active_calls_list or []),
            ]
            for sk_meta in (self.state.selected_softkeys or {}).values():
                cref = sk_meta.get("call_reference")
                if cref:
                    candidates.append(cref)
            for candidate in candidates:
                nref = self.numeric_call_ref(candidate)
                if nref is None and candidate is not None:
                    call = self.state.calls.get(str(candidate), {})
                    nref = self.numeric_call_ref(call.get("call_reference"))
                if nref is not None:
                    numeric_ref = nref
                    call = self.state.calls.get(str(candidate), {}) or self.state.calls.get(str(nref), {})
                    if call.get("line_instance"):
                        active_line = int(call["line_instance"])
                    break

        return active_line, numeric_ref or 0

    def press_softkey(self, softkey_name, line=1, call_ref=0):
        key_defs = self.state.softkey_template or {}
        active_line, active_call_ref = self.resolve_call_target(
            line, call_ref, softkey_name=softkey_name
        )
        for v in key_defs.values():
            if v.get("label") == softkey_name:
                if softkey_name == "EndCall":
                    from messages.phone import end_local_call
                    end_local_call(self, source="local-endcall", call_ref=active_call_ref)
                handle_softkey_press(self, active_line, v["event"], active_call_ref)
                return
        self.logger.warning(f"({self.state.device_name}) No such softkey {softkey_name}")

    def _wait_new_call_connected(self, refs_before, timeout: float) -> bool:
        """Wait until a call ref not in *refs_before* reaches Connected (state 5)."""
        import time

        before = {str(r) for r in (refs_before or [])}
        deadline = time.time() + timeout
        while time.time() < deadline:
            for key in self.state.active_calls_list or []:
                sk = str(key)
                if sk in before:
                    continue
                if self.state.calls.get(sk, {}).get("call_state") == 5:
                    return True
            if self.events.call_connected.wait(timeout=0.05):
                for key in self.state.active_calls_list or []:
                    sk = str(key)
                    if sk not in before and self.state.calls.get(sk, {}).get("call_state") == 5:
                        return True
        return False

    def blind_transfer(self, number: str, *, pause: float = 0.3) -> None:
        """Blind transfer active call: Transfer -> dial -> Transfer."""
        import time

        self.press_softkey("Transfer")
        time.sleep(pause)
        for ch in number:
            if ch == "*":
                code = 0x0E
            elif ch == "#":
                code = 0x0F
            elif ch.isdigit():
                code = int(ch)
            else:
                continue
            handle_keypad_press(self, 1, code)
            time.sleep(0.05)
        time.sleep(pause)
        self.press_softkey("Transfer")

    def consulted_transfer(
        self,
        number: str,
        *,
        pause: float = 0.3,
        consult_timeout: float = 30.0,
    ) -> None:
        """Consulted transfer: Transfer -> dial -> wait for answer -> Transfer."""
        import time

        self.events.call_connected.clear()
        refs_before = list(self.state.active_calls_list or [])
        self.press_softkey("Transfer")
        time.sleep(pause)
        for ch in number:
            if ch == "*":
                code = 0x0E
            elif ch == "#":
                code = 0x0F
            elif ch.isdigit():
                code = int(ch)
            else:
                continue
            handle_keypad_press(self, 1, code)
            time.sleep(0.05)
        if not self._wait_new_call_connected(refs_before, consult_timeout):
            self.logger.warning("Consult transfer: consult party did not connect in time")
            return
        time.sleep(pause)
        found = self._call_ref_for_state(5)
        if found:
            _line, ref = found
            self.state.selected_call_reference = str(ref)
        self.press_softkey("Transfer")

    def conference(
        self,
        number: str,
        *,
        pause: float = 0.3,
        consult_timeout: float = 30.0,
    ) -> None:
        """Conference: Confrn -> dial -> wait for answer -> Confrn (all parties stay)."""
        import time

        self.events.call_connected.clear()
        refs_before = list(self.state.active_calls_list or [])
        self.press_softkey("Confrn")
        time.sleep(pause)
        for ch in number:
            if ch == "*":
                code = 0x0E
            elif ch == "#":
                code = 0x0F
            elif ch.isdigit():
                code = int(ch)
            else:
                continue
            handle_keypad_press(self, 1, code)
            time.sleep(0.05)
        if not self._wait_new_call_connected(refs_before, consult_timeout):
            self.logger.warning("Conference: third party did not connect in time")
            return
        time.sleep(pause)
        found = self._call_ref_for_state(5)
        if found:
            _line, ref = found
            self.state.selected_call_reference = str(ref)
        self.press_softkey("Confrn")

    def press_stimulus(self, button_type, instance):
        # Simplified logic. Find the key in the softkey_template, send the event.
        # key_defs = self.state.softkey_template
        # key_found = False
        # for k, v in key_defs.items():
        #     active_call_ref = call_ref
        #     active_line = line
        #     if self.state.active_call and active_call_ref == 0:
        #         active_line = self.state.active_call_line_instance
        #         active_call_ref = int(self.state.calls.get(str(active_line), {}).get("call_reference", "0"))
        #
        #     if v["label"] == softkey_name:
        #         handle_softkey_press(self, active_line, v["event"], active_call_ref)
        #         key_found = True
        handle_button_press(self, button_type, instance)

        if not button_type or not instance:
            self.logger.warning(f"({self.state.device_name}) No such button {button_type}/{instance}")

    def on_hook(self):
        from messages.phone import end_local_call
        end_local_call(self, source="local-onhook")
        send_onhook(self)
        self.state.update_prompt("", 0)

    def off_hook(self):
        send_offhook(self)

    def wait_for_call(self, timeout=None, until="RING"):
        """
        until = "RING" | "CONNECTED" | "MEDIA"
        timeout=None means wait forever (used when macro passes 0)
        """
        # fast path if we already have what we need
        if until == "RING":
            if self.state.call_active:  # already ringing or active
                return True
            ev = self.events.call_ringing
        elif until == "CONNECTED":
            if self.state.call_connected:
                return True
            ev = self.events.call_connected
        elif until == "MEDIA":
            if self.state.media_active:
                return True
            ev = self.events.media_started
        else:
            raise ValueError(f"Unknown wait target: {until}")

        return ev.wait(timeout)

    def _on_digit(self, ch: str):
        if not ch: return
        with self.dtmf.lock:
            self.dtmf.buf.append(ch)
            self.dtmf.event.set()

    def wait_for_digit(self, timeout=None, stop_event: threading.Event | None = None, poll: float = 0.1):
        """
        Return one digit or None on timeout. If stop_event is given, returns None early when set.
        """
        end = None if timeout is None else (time.time() + timeout)
        while True:
            if stop_event is not None and stop_event.is_set():
                return None
            # compute next slice
            slice_to = poll
            if end is not None:
                remain = end - time.time()
                if remain <= 0:
                    return None
                slice_to = min(slice_to, max(0.01, remain))
            # Event wait in small slices
            if self.dtmf.event.wait(slice_to):
                with self.dtmf.lock:
                    if self.dtmf.buf:
                        ch = self.dtmf.buf.popleft()
                        if not self.dtmf.buf:
                            self.dtmf.event.clear()
                        return ch

    def read_digits(self, max_len=1, timeout=10.0, terminators="#", interdigit=2.0,
                    stop_event: threading.Event | None = None):
        s = ""
        deadline = None if timeout is None else (time.time() + timeout)
        while len(s) < max_len:
            if stop_event is not None and stop_event.is_set():
                return s
            # choose slice: interdigit or remaining overall
            slice_to = interdigit if interdigit is not None else (deadline - time.time() if deadline else None)
            ch = self.wait_for_digit(timeout=slice_to, stop_event=stop_event)
            if ch is None:  # slice timed out or stop requested
                if deadline is not None and time.time() >= deadline:
                    break
                if interdigit is not None:
                    break
                continue
            if ch in (terminators or ""):
                break
            s += ch
        return s
