from utils.client import normalize_mac_address
from threading import Event
from messages.generic import get_device_enum, DEVICE_TYPE_MAP
from datetime import datetime
import json
import threading
import time
from config import load_config
from datetime import datetime, timezone


class PhoneState:
    def __init__(self, server=None, mac=None, model=None, port=2000):
        # Basics for registration
        self.server = server
        self.port = port
        self.mac_address = normalize_mac_address(mac)
        self.device_name = "SEP" + self.mac_address
        self.model = get_device_enum(model)
        self.model_name = DEVICE_TYPE_MAP.get(self.model)
        self.client_ip = None
        self.is_registered = Event()
        self.is_unregistered = Event()

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

    def get_current_softkeys(self, keyset_override=None):
        if self.softkey_set_definition == {} or self.softkey_template == {}:
            return []

        keys = []
        if keyset_override:
            sk_set = keyset_override
        else:
            sk_set = self.selected_softkey_set
        sk_def = self.softkey_set_definition.get(str(sk_set), {})
        for k, v in sk_def.items():
            template_index_name = v.get("template_index_name", "")
            template_index = v.get("template_index", "")
            template_info_name = v.get("template_info_name", "")
            info_index = v.get("info_index", "")

            templ_data = self.softkey_template.get(str(template_index), {})
            label = templ_data.get("label", "")
            event = templ_data.get("event", "")

            keys.append((label, event))

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
    # Prefer a project-specific loader if available (lets you keep your existing config).
    cfg = None
    if args.config:
        cfg = load_config(args.config)

    if cfg:
        # Try common keys used across the project; fall back if missing.
        server = cfg.get("server") or args.server
        mac = cfg.get("mac") or args.mac
        model = cfg.get("model") or args.model
    else:
        server = args.server
        mac = args.mac
        model = args.model

    if not server or not mac:
        raise SystemExit(
            "Missing required connection details. Provide --model, --server and --mac (or use --config).")

    # Construct a minimal state; your PhoneState likely accepts these kwargs.
    return PhoneState(server=server, mac=mac, model=model)
