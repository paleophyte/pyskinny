from utils.client import normalize_mac_address
from threading import Event
from messages.generic import get_device_enum, DEVICE_TYPE_MAP
from datetime import datetime
import json
import threading
import time
from config import load_config, resolve_config_path
from datetime import datetime, timezone


class PhoneState:
    def __init__(self, server=None, mac=None, device_name=None, model=None, port=2000, tftp_port=69):
        # Basics for registration
        self.server = server
        self.source_port = 5001
        self.port = port
        self.tftp_port = tftp_port
        if mac is not None:
            self.mac_address = normalize_mac_address(mac)
            self.device_name = "SEP" + self.mac_address
        else:
            self.mac_address = None
            self.device_name = device_name
        self.model = get_device_enum(model)
        self.model_name = DEVICE_TYPE_MAP.get(self.model)
        self.client_ip = None
        self.is_registered = Event()
        self.is_unregistered = Event()
        self.register_reject_reason = None

        # RegisterAck
        self.keepalive_interval = 30
        self.second_keepalive_interval = 30
        self.date_template = None
        self.feature_flags = 0
        self.feature_flag_str = ""

        # TimeDateRes
        self.w_month = None
        self.w_day = None
        self.w_year = None
        self.w_day_of_week = None
        self.w_day_of_week_name = None
        self.w_hour = None
        self.w_minute = None
        self.w_second = None
        self.w_millisecond = None
        self.w_system_time = None
        self.w_system_time_desc = None
        self.initial_time_dt = None
        self.received_at = None

        # ConfigStatRes
        self.line_count = 0
        self.speed_dial_count = 0
        self.instance = 0
        self.user_name = None
        self.server_name = None

        # ButtonTemplateRes
        self.button_offset = 0
        self.button_count = 0
        self.total_button_count = 0
        self.max_button_count = 0
        self.button_template = {}

        # SoftKeyTemplateRes
        self.softkey_offset = 0
        self.softkey_count = 0
        self.total_softkey_count = 0
        self.max_softkey_count = 0
        self.softkey_template = {}

        # DisplayPromptStatus
        self._current_prompt = ""
        self.prompt_details = {}
        self._prompt_lock = threading.Lock()
        self._prompt_restore_thread = None
        self._prompt_watchers = []

        # SoftKeySetRes
        self.softkey_set_offset = 0
        self.softkey_set_count = 0
        self.total_softkey_set_count = 0
        self.max_softkey_set_count = 0
        self.softkey_set_definition = {}
        self.selected_softkey_set = 0

        # ForwardStatRes
        self.active_forward = 0
        self.call_forward = {}

        # SelectSoftKeys
        self.selected_softkeys = {}

        # LineStatRes
        self.lines = {}

        # FeatureStatRes
        self.feature_stat_count = 0

        # SpeedDialStatRes
        self.speed_dials = {}

        # SetRinger
        self.ring_mode = 0
        self.ring_duration = 0
        self.ring_line_instance = None
        self.ring_call_reference = None

        # SetSpeakerMode
        self.speaker_mode = None

        # SetLamp
        self.stimulus = 0
        self.stimulus_name = None
        self.stimulus_instance = 0
        self.lamp_mode = 0

        # CallState
        self.active_call = False
        self.active_call_line_instance = 0
        self.calls = {}
        self.calls_list = []

        # added for softphone
        self.active_calls_list = []
        self.selected_call_reference = None

        # StartTone
        self.enable_audio = True
        self._audio = None
        self._key_beep = None
        self.play_tones = {}
        self.tone_volume = 5.0
        self._active_players = {}
        self.last_volumes = {}

        # CallInfo
        self.callinfo = {}

        # DisplayNotify
        self.display_notify = {}

        # Media
        self.start_media_transmission = {}
        self._rtp_tx = None
        self._rtp_rx = None
        self._rtp_echo_source = None
        self._rtp_recorder = None
        self.rtp_loopback = False
        self.rtp_loopback_monitor = False
        self.rtp_tone = False
        self.rtp_tone_hz = 1000.0
        self.rtp_record = False
        self.rtp_record_dir = "logs/rtp"
        self.rtp_pt_override = None
        self.rtp_stats = False
        self.rtp_stats_interval = 0.0
        self._rtp_stats = None
        self._rtp_stats_monitor = None

        # Key Value storage
        self.kv_dict = {}
        self.call_active = False
        self.call_connected = False
        self.media_active = False

        # Topology
        self.topology = {}
        self.interface = None
        self.interface_mac = None
        self._topology_thread = None
        self._stop_topology_thread = None

    @property
    def current_prompt(self):
        return self._current_prompt

    @current_prompt.setter
    def current_prompt(self, new_value):
        if new_value != self._current_prompt:
            old = self._current_prompt
            self._current_prompt = new_value
            for watcher in self._prompt_watchers:
                watcher(old, new_value)

    def update_prompt(self, text, duration=0, line_instance=None, call_reference=None):
        if line_instance is not None:
            self.prompt_details["line_instance"] = line_instance
        if call_reference is not None:
            self.prompt_details["call_reference"] = call_reference

        with self._prompt_lock:
            old_prompt = self.current_prompt
            self.current_prompt = text

        if duration > 0:
            def restore():
                time.sleep(duration)
                with self._prompt_lock:
                    # Only restore if no newer prompt was set
                    if self.current_prompt == text:
                        self.current_prompt = old_prompt

            # Cancel any previous restore thread if still running
            if self._prompt_restore_thread and self._prompt_restore_thread.is_alive():
                # No cancel mechanism in threads, but we won't wait for it
                pass

            # Start a new restore thread
            self._prompt_restore_thread = threading.Thread(target=restore, daemon=True)
            self._prompt_restore_thread.start()

    def set_call_state(self, call_id, state):
        self.calls[call_id] = state

    def to_dict(self):
        def safe_convert(value):
            if isinstance(value, Event):
                return value.is_set()
            elif isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, dict):
                return {k: safe_convert(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                return [safe_convert(v) for v in value]
            else:
                return value

        return {k: safe_convert(v) for k, v in self.__dict__.items() if not k.startswith('_')}

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)

    def get_current_softkeys(self, keyset_override=None, valid_key_mask=None):
        if self.softkey_set_definition == {} or self.softkey_template == {}:
            return []

        from utils.softkeys import resolve_template_by_index

        keys = []
        if keyset_override is not None:
            sk_set = keyset_override
        else:
            sk_set = self.selected_softkey_set
        sk_def = self.softkey_set_definition.get(str(sk_set), {})
        for pos_str, v in sorted(sk_def.items(), key=lambda item: int(item[0])):
            pos = int(pos_str)
            if valid_key_mask is not None and not (int(valid_key_mask) & (1 << pos)):
                continue
            template_index = int(v.get("template_index", 0) or 0)
            templ_data = resolve_template_by_index(self.softkey_template, template_index)
            label = templ_data.get("label", "") or v.get("template_index_name", "")
            event = templ_data.get("event", template_index)
            if label and label != "Undefined":
                keys.append((label, int(event)))

        return keys

    def _human_elapsed(self, iso_ts_start, iso_ts_end, now=None) -> str:
        """
        < 60s       -> "n seconds"
        60s .. <1h  -> "m:ss"
        >= 1h       -> "h:mm:ss"
        Accepts iso_ts as ISO 8601 string or {"current_time": <iso>}.
        `now` can be None, ISO string, or datetime.
        """
        try:
            # Accept dict input like {"current_time": "..."}
            # if isinstance(iso_ts, dict) and "current_time" in iso_ts:
            #     iso_ts = iso_ts["current_time"]

            # Parse start timestamp
            ts = datetime.fromisoformat(str(iso_ts_start).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # Parse end timestamp
            if iso_ts_end is not None:
                te = datetime.fromisoformat(str(iso_ts_end).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    te = te.replace(tzinfo=timezone.utc)
            else:
                te = None

            # Parse/compute 'now'
            if now is None:
                now_dt = datetime.now(timezone.utc)
            elif isinstance(now, str):
                now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
                if now_dt.tzinfo is None:
                    now_dt = now_dt.replace(tzinfo=timezone.utc)
            elif isinstance(now, datetime):
                now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            else:
                raise TypeError(f"'now' must be None, str, or datetime, not {type(now)}")

            # Elapsed (absolute) seconds as int
            if te is not None:
                total = int((te - ts).total_seconds())
            else:
                total = int((now_dt - ts).total_seconds())

            # total = int((now_dt - ts).total_seconds())
            if total < 0:
                total = -total

            # Split safely as ints
            hours, rem = divmod(total, 3600)
            minutes, seconds = divmod(rem, 60)

            if total < 60:
                return f"{seconds} seconds"
            if hours == 0:
                return f"{minutes}:{seconds:02d}"
            return f"{hours}:{minutes:02d}:{seconds:02d}"

        except Exception as e:
            # Helpful context if something weird sneaks in
            raise RuntimeError(
                f"human_elapsed failed for iso_ts={iso_ts_start!r} (type={type(iso_ts_start).__name__}), "
                f"now={now!r} (type={type(now).__name__})"
            ) from e


def build_state_from_args(args) -> PhoneState:
    cfg_path = resolve_config_path(getattr(args, "config", None))
    cfg = load_config(cfg_path) if cfg_path else None

    if cfg:
        server = cfg.get("server") or getattr(args, "server", None)
        mac = cfg.get("mac") or getattr(args, "mac", None)
        device = cfg.get("device") or getattr(args, "device", None)
        model = cfg.get("model") or getattr(args, "model", None)
    else:
        server = getattr(args, "server", None)
        mac = getattr(args, "mac", None)
        device = getattr(args, "device", None)
        model = getattr(args, "model", None)

    missing = []
    if not server:
        missing.append("--server")
    if not model:
        missing.append("--model")
    if not (mac or device):
        missing.append("--mac or --device")
    if missing:
        raise SystemExit(
            "Missing required connection details: "
            + ", ".join(missing)
            + ". Provide them on the command line or use --config with a complete examples/cli.config."
        )

    return PhoneState(server=server, mac=mac, device_name=device, model=model)


def apply_media_options(state: PhoneState, args, cfg: dict | None) -> None:
    """Apply optional RTP / audio flags from CLI args or config file."""
    if getattr(args, "no_audio", False):
        state.enable_audio = False

    play_mode = getattr(args, "rtp_play_mode", None)
    if cfg and cfg.get("rtp_play_mode"):
        play_mode = cfg["rtp_play_mode"]
    if getattr(args, "rtp_mic", False):
        play_mode = "mic"
    if getattr(args, "rtp_tone", False):
        play_mode = "tone"
    wav_path = getattr(args, "rtp_wav", None) or (cfg.get("rtp_wav") if cfg else None)
    if wav_path:
        play_mode = str(wav_path)
    if play_mode == "loopback":
        state.rtp_loopback = True
    elif play_mode:
        state.kv_dict["audio_play_mode"] = play_mode

    if cfg:
        if cfg.get("rtp_loopback"):
            state.rtp_loopback = True
        if cfg.get("rtp_loopback_monitor"):
            state.rtp_loopback_monitor = True
        if cfg.get("no_audio"):
            state.enable_audio = False
    if getattr(args, "rtp_loopback", False):
        state.rtp_loopback = True
    if getattr(args, "rtp_loopback_monitor", False):
        state.rtp_loopback_monitor = True
    if cfg and cfg.get("rtp_tone"):
        state.rtp_tone = True
    if getattr(args, "rtp_tone", False) and play_mode is None:
        state.rtp_tone = True
    if cfg and cfg.get("rtp_tone_hz") is not None:
        state.rtp_tone_hz = float(cfg["rtp_tone_hz"])
    hz = getattr(args, "rtp_tone_hz", None)
    if hz is not None:
        state.rtp_tone_hz = float(hz)
    if cfg and cfg.get("rtp_record"):
        state.rtp_record = True
    if getattr(args, "rtp_record", False):
        state.rtp_record = True
    if cfg and cfg.get("rtp_record_dir"):
        state.rtp_record_dir = str(cfg["rtp_record_dir"])
    record_dir = getattr(args, "rtp_record_dir", None)
    if record_dir:
        state.rtp_record_dir = str(record_dir)
    pt = getattr(args, "rtp_pt", None)
    if pt is not None:
        state.rtp_pt_override = int(pt)
    elif cfg and cfg.get("rtp_pt") is not None:
        state.rtp_pt_override = int(cfg["rtp_pt"])
    if cfg and cfg.get("rtp_stats"):
        state.rtp_stats = True
    if getattr(args, "rtp_stats", False):
        state.rtp_stats = True
    if cfg and cfg.get("rtp_stats_interval") is not None:
        state.rtp_stats_interval = float(cfg["rtp_stats_interval"])
    interval = getattr(args, "rtp_stats_interval", None)
    if interval is not None:
        state.rtp_stats_interval = float(interval)
    elif getattr(args, "rtp_stats", False) and state.rtp_stats_interval <= 0:
        state.rtp_stats_interval = 5.0

    _apply_ivr_lab_media_defaults(state, args, cfg)


def _media_explicitly_configured(args, cfg) -> bool:
    if getattr(args, "no_audio", False):
        return True
    if cfg and cfg.get("no_audio"):
        return True
    if getattr(args, "rtp_play_mode", None) is not None:
        return True
    if cfg and cfg.get("rtp_play_mode"):
        return True
    for flag in ("rtp_mic", "rtp_tone", "rtp_loopback", "rtp_loopback_monitor", "rtp_wav"):
        if getattr(args, flag, False):
            return True
    if cfg:
        for key in ("rtp_mic", "rtp_tone", "rtp_loopback", "rtp_loopback_monitor", "rtp_wav"):
            if cfg.get(key):
                return True
    return False


def _apply_ivr_lab_media_defaults(state: PhoneState, args, cfg) -> None:
    """
    When audio is on and no RTP flags were given, play received RTP locally (RX monitor).

    TX stays silent unless --rtp-mic / --rtp-tone is set (avoids PortAudio errors on
    headless or mic-less Windows hosts). For sim IVR DTMF loopback use --rtp-mic.
    """
    if not state.enable_audio:
        return
    if _media_explicitly_configured(args, cfg):
        return
    if state.kv_dict.get("audio_play_mode"):
        return
    state.kv_dict["audio_play_mode"] = "silent"
    state.rtp_loopback_monitor = True
