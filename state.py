from utils.client import normalize_mac_address
from threading import Event
from messages.generic import get_device_enum
from datetime import datetime
import json
import threading
import time


class PhoneState:
    def __init__(self, server=None, mac=None, model=None, port=2000):
        # Basics for registration
        self.server = server
        self.port = port
        self.mac_address = normalize_mac_address(mac)
        self.device_name = "SEP" + self.mac_address
        self.model = get_device_enum(model)
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
