import struct
import socket
import threading
import logging
from dispatcher import dispatch_message
from messages.register import send_register_req, send_unregister_req
from messages.keepalive import send_keepalive_req
from state import PhoneState
from utils.tftp import get_device_config_via_tftp
from messages.generic import handle_softkey_press, TONE_FOLDER, TONE_LOOKUP
from audio_worker import LoopingAudioWorker
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
        self.logger = logging.getLogger("SCCPClient")
        self.state._prompt_watchers.append(self._on_prompt_changed)
        self._stop_event = threading.Event()
        self._threads = []
        self.audio = LoopingAudioWorker(
            samplerate=44100,  # your key_beep.wav was 44.1k in logs
            channels=1,
            blocksize=1024,
            tone_resolver=_tone_path_from_id,
            master_gain_db=state.tone_volume  # optional: treat as master gain
        )
        self.audio.start()
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
        cfg = get_device_config_via_tftp(tftp_server=self.state.server, device_name=self.state.device_name)

        self.connect()
        self._send_register()

    def stop(self):
        self._send_unregister()
        self.state.is_unregistered.wait(timeout=10)

        if not self.state.is_registered.is_set():
            self.logger.error(f"({self.state.device_name}) Phone failed to unregister in time. Terminating thread.")
            return

        # signal loops to exit
        self.running = False
        self._stop_event.set()

        # unblock recv() immediately
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

        # stop any playing audio
        self.audio.close()

        # join threads (short timeout to avoid hangs)
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=2.0)

    def _send_unregister(self):
        send_unregister_req(self)

    def _send_register(self):
        msg = send_register_req(self.state)
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

    def press_softkey(self, softkey_name, line=1, call_ref=0):
        # Simplified logic. Find the key in the softkey_template, send the event.
        key_defs = self.state.softkey_template
        key_found = False
        for k, v in key_defs.items():
            active_call_ref = call_ref
            active_line = line
            if self.state.active_call and active_call_ref == 0:
                active_line = self.state.active_call_line_instance
                active_call_ref = int(self.state.calls.get(str(active_line), {}).get("call_reference", "0"))

            if v["label"] == softkey_name:
                handle_softkey_press(self, active_line, v["event"], active_call_ref)
                key_found = True

        if not key_found:
            self.logger.warning(f"({self.state.device_name}) No such softkey {softkey_name}")

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

    # def wait_for_digit(self, timeout=None):
    #     """Return one digit ('0'-'9','*','#') or None on timeout."""
    #     end = None if timeout is None else (time.time() + timeout)
    #     while True:
    #         with self.dtmf.lock:
    #             if self.dtmf.buf:
    #                 ch = self.dtmf.buf.popleft()
    #                 if not self.dtmf.buf:
    #                     self.dtmf.event.clear()
    #                 return ch
    #         if timeout is None:
    #             self.dtmf.event.wait()
    #         else:
    #             remaining = end - time.time()
    #             if remaining <= 0:
    #                 return None
    #             self.dtmf.event.wait(remaining)
    #
    # def read_digits(self, max_len=1, timeout=10.0, terminators="#", interdigit=2.0):
    #     """
    #     Read up to max_len digits, waiting up to timeout seconds overall,
    #     with interdigit max wait per digit and optional terminators ('#' by default).
    #     """
    #     s = ""
    #     deadline = None if timeout is None else (time.time() + timeout)
    #     while len(s) < max_len:
    #         wait = None
    #         if deadline is not None:
    #             wait = max(0.0, deadline - time.time())
    #             if interdigit is not None:
    #                 wait = min(wait, interdigit)
    #         ch = self.wait_for_digit(wait)
    #         if ch is None:
    #             break
    #         if ch in terminators:
    #             break
    #         s += ch
    #     return s

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
