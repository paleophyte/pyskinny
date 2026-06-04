"""Per-phone Skinny session state machine."""

from __future__ import annotations

import logging
import socket
import struct
from typing import TYPE_CHECKING

from simulator import payloads
from simulator.call_hub import CallHub, keypad_to_char
from simulator.protocol import parse_register_req, read_message
from simulator.registry import DeviceRegistry
from simulator.tftp_service import TftpConfigService

if TYPE_CHECKING:
    from simulator.call_hub import SimCall

logger = logging.getLogger(__name__)

MSG_REGISTER_REQ = 0x0001
MSG_IP_PORT = 0x0002
MSG_KEEPALIVE = 0x0000
MSG_ALARM = 0x0020
MSG_CAPABILITIES_RES = 0x0010
MSG_BUTTON_TEMPLATE_REQ = 0x000E
MSG_SOFTKEY_TEMPLATE_REQ = 0x0028
MSG_SOFTKEY_SET_REQ = 0x0025
MSG_CONFIG_STAT_REQ = 0x000C
MSG_LINE_STAT_REQ = 0x000B
MSG_SPEED_DIAL_STAT_REQ = 0x000A
MSG_FORWARD_STAT_REQ = 0x0009
MSG_FEATURE_STAT_REQ = 0x0034
MSG_REGISTER_AVAILABLE_LINES = 0x002D
MSG_TIME_DATE_REQ = 0x000D
MSG_UNREGISTER_REQ = 0x0027
MSG_OFF_HOOK = 0x0006
MSG_ON_HOOK = 0x0007
MSG_KEYPAD = 0x0003
MSG_SOFTKEY = 0x0026
MSG_OPEN_RX_ACK = 0x0022


class SkinnySession:
    def __init__(
        self,
        conn: socket.socket,
        addr: tuple,
        registry: DeviceRegistry,
        server_name: str,
        hub: CallHub,
        tftp: TftpConfigService | None = None,
    ):
        self.conn = conn
        self.addr = addr
        self.registry = registry
        self.server_name = server_name
        self.hub = hub
        self.tftp = tftp
        self.device_name = ""
        self.directory_number = ""
        self.station_ip = ""
        self.source_port = 5001
        self._registered = False
        self._lines = 1
        self.device_type = 0
        self._legacy_phone = False
        self._template_profile = "modern"
        self.active_call: SimCall | None = None
        self.awaiting_media_ack = False

    def run(self) -> None:
        try:
            while True:
                msg = read_message(self.conn)
                if msg is None:
                    break
                msg_id, payload = msg
                if not self._handle(msg_id, payload):
                    break
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            logger.debug("Session %s closed: %s", self.device_name or self.addr, exc)
        finally:
            self.hub.unregister_session(self)
            try:
                self.conn.close()
            except OSError:
                pass
            if self.device_name:
                logger.info(
                    "Device %s (%s) disconnected",
                    self.device_name,
                    self.directory_number or "?",
                )

    def send(self, packet: bytes) -> None:
        if len(packet) >= 12:
            from utils.skinny_messages import get_message_name
            from utils.logs import log_skinny_wire

            _mid = struct.unpack("<III", packet[:12])[2]
            log_skinny_wire(
                logger,
                self.device_name or self.addr[0],
                "SEND",
                _mid,
                get_message_name(_mid),
                len(packet),
            )
        self.conn.sendall(packet)

    def send_many(self, packets: list[bytes]) -> None:
        for packet in packets:
            self.send(packet)

    def _handle(self, msg_id: int, payload: bytes) -> bool:
        from utils.skinny_messages import get_message_name
        from utils.logs import log_skinny_wire

        log_skinny_wire(
            logger,
            self.device_name or self.addr[0],
            "RECV",
            msg_id,
            get_message_name(msg_id),
            len(payload),
        )
        if msg_id == MSG_REGISTER_REQ:
            return self._on_register(payload)
        if msg_id == MSG_IP_PORT:
            if len(payload) >= 4:
                self.source_port = struct.unpack("<I", payload[:4])[0]
            return True
        if msg_id == MSG_KEEPALIVE:
            if self._registered:
                self.send(payloads.keepalive_ack())
            return True
        if msg_id == MSG_ALARM:
            logger.debug("Alarm from %s (pre-register=%s)", self.addr, not self.device_name)
            return True
        if msg_id == MSG_UNREGISTER_REQ:
            self.hub.end_call(source=self)
            self.send(payloads.unregister_ack(0))
            return False
        if not self.device_name:
            if msg_id in (MSG_ALARM, MSG_LINE_STAT_REQ, MSG_SPEED_DIAL_STAT_REQ):
                return True
            logger.debug("Ignoring msg 0x%04X before registration from %s", msg_id, self.addr)
            return True

        if msg_id == MSG_CAPABILITIES_RES:
            return True
        if msg_id == MSG_BUTTON_TEMPLATE_REQ:
            self.send(
                payloads.button_template_res(
                    legacy=self._template_profile == "legacy7912",
                    cm2=self._template_profile == "cm2",
                )
            )
            return True
        if msg_id == MSG_SOFTKEY_TEMPLATE_REQ:
            if self._template_profile == "cm2":
                logger.debug("(%s) CM2 button phone — no SoftKeyTemplateRes", self.device_name)
                return True
            self.send(payloads.softkey_template_res(legacy=self._legacy_phone))
            return True
        if msg_id == MSG_SOFTKEY_SET_REQ:
            if self._template_profile == "cm2":
                logger.debug("(%s) CM2 button phone — no SoftKeySetRes", self.device_name)
                return True
            self.send(payloads.softkey_set_res(legacy=self._legacy_phone))
            if self._legacy_phone:
                self.send(payloads.legacy_select_softkeys_idle())
                self.send(payloads.legacy_display_prompt_idle())
            return True
        if msg_id == MSG_CONFIG_STAT_REQ:
            self.send(
                payloads.config_stat_res(
                    self.device_name,
                    self.server_name,
                    lines=self._lines,
                    speed_dials=0,
                )
            )
            return True
        if msg_id == MSG_LINE_STAT_REQ:
            line = self._read_u32(payload, default=1)
            self.send(payloads.line_stat_res(line, self.directory_number))
            return True
        if msg_id == MSG_FEATURE_STAT_REQ:
            self.send(payloads.feature_stat_res(legacy=self._legacy_phone))
            return True
        if msg_id == MSG_FORWARD_STAT_REQ:
            line = self._read_u32(payload, default=1)
            self.send(payloads.forward_stat_res(line))
            return True
        if msg_id == MSG_SPEED_DIAL_STAT_REQ:
            sd = self._read_u32(payload, default=1)
            self.send(payloads.speed_dial_stat_res(sd))
            return True
        if msg_id == MSG_REGISTER_AVAILABLE_LINES:
            if len(payload) >= 4:
                self._lines = max(1, self._read_u32(payload))
            return True
        if msg_id == MSG_TIME_DATE_REQ:
            if not self._registered:
                self._finish_registration()
            else:
                logger.debug("(%s) TimeDateReq", self.device_name)
                self.send(payloads.time_date_res())
            return True

        if msg_id == MSG_OFF_HOOK:
            logger.info("(%s) OffHook", self.device_name)
            return self._on_off_hook()
        if msg_id == MSG_ON_HOOK:
            logger.info("(%s) OnHook — ending call", self.device_name)
            self.hub.end_call(source=self)
            return True
        if msg_id == MSG_KEYPAD:
            return self._on_keypad(payload)
        if msg_id == MSG_SOFTKEY:
            return self._on_softkey(payload)
        if msg_id == MSG_OPEN_RX_ACK:
            logger.debug(
                "(%s) OpenReceiveChannelAck (%d bytes)",
                self.device_name,
                len(payload),
            )
            self.hub.on_media_ack(self, payload)
            return True

        logger.debug(
            "(%s) unhandled client msg 0x%04X (%d bytes)",
            self.device_name,
            msg_id,
            len(payload),
        )
        return True

    def _on_register(self, payload: bytes) -> bool:
        info = parse_register_req(payload)
        self.device_name = info.device_name
        self.station_ip = info.station_ip
        self.device_type = info.device_type
        self._template_profile = payloads.phone_template_profile(info.device_type)
        self._legacy_phone = self._template_profile == "legacy7912"
        self.directory_number = self.registry.assign(self.device_name)
        if self.tftp:
            self.tftp.write_device_config(self.device_name, self.directory_number)
        logger.info(
            "Register %s from %s -> DN %s (type=0x%x, ip=%s, %s)",
            self.device_name,
            self.addr[0],
            self.directory_number,
            info.device_type,
            info.station_ip,
            "legacy" if self._legacy_phone else self._template_profile,
        )
        self.send(payloads.register_ack())
        self.send(payloads.capabilities_req())
        return True

    def _finish_registration(self) -> None:
        self.send(payloads.time_date_res())
        if self._legacy_phone:
            self.send(payloads.legacy_display_prompt_ready())
            self.send(payloads.legacy_select_softkeys_idle())
        else:
            self.send(payloads.display_prompt_status("Ready"))
            self.send(payloads.select_soft_keys(softkey_set_index=0))
        self._registered = True
        self.hub.register_session(self)
        logger.info(
            "(%s) registration complete — DN %s",
            self.device_name,
            self.directory_number,
        )

    def _on_off_hook(self) -> bool:
        if self.active_call and self.active_call.state == "ringing" and self is self.active_call.callee:
            self.hub.answer(self)
            return True
        if self.active_call is None:
            self._start_outbound()
        return True

    def _on_softkey(self, payload: bytes) -> bool:
        if len(payload) < 12:
            return True
        softkey_id, line, call_ref = struct.unpack("<III", payload[:12])
        logger.info(
            "(%s) SoftKeyEvent id=%s line=%s ref=%s",
            self.device_name,
            softkey_id,
            line,
            call_ref,
        )
        if softkey_id == payloads.SK_NEWCALL:
            self._start_outbound(line=line or 1, call_ref_hint=call_ref)
        elif softkey_id == payloads.SK_ANSWER:
            self.hub.answer(self)
        elif softkey_id == payloads.SK_HOLD:
            self.hub.hold(self)
        elif softkey_id == payloads.SK_RESUME:
            self.hub.resume(self)
        elif softkey_id == payloads.SK_TRANSFER:
            self.hub.on_transfer_softkey(self)
        elif softkey_id == payloads.SK_CONFRN:
            self.hub.on_conference_softkey(self, line=line, call_ref=call_ref)
        elif softkey_id == payloads.SK_ENDCALL:
            self.hub.end_call(source=self)
        return True

    def _start_outbound(self, *, line: int = 1, call_ref_hint: int | None = None) -> None:
        if self.active_call is not None and self.active_call.state != "held":
            return
        try:
            call = self.hub.begin_outbound(
                self, line=line, call_ref_hint=call_ref_hint
            )
        except RuntimeError:
            return
        line = call.line
        ref = call.call_ref
        if self._legacy_phone:
            packets = self._legacy_outbound_packets(line, ref)
            tone = payloads.TONE_DIAL
            legacy_tone = True
        else:
            tone = payloads.TONE_DIAL
            legacy_tone = False
            packets = [
                payloads.call_state(payloads.CALL_STATE_OFFHOOK, line, ref),
                payloads.activate_call_plane(line),
                payloads.call_state(payloads.CALL_STATE_PROCEED, line, ref),
                payloads.stop_tone(line, ref),
                payloads.start_tone(tone, line, ref, legacy=False, direction=2),
                payloads.select_soft_keys(line, ref, softkey_set_index=4),
                payloads.display_prompt_status("", line, ref),
            ]
        logger.info(
            "(%s) outbound dial ref=%s tone=%s (0x%x) legacy=%s",
            self.device_name,
            ref,
            tone,
            tone,
            legacy_tone,
        )
        self.send_many(packets)

    def _legacy_outbound_packets(self, line: int, ref: int) -> list[bytes]:
        """7912 sequence matched to CUCM cm_cap.pcapng (New Call with dial tone)."""
        return [
            payloads.set_ringer(1, 1, line=0, call_ref=0),
            payloads.set_speaker_mode(1),
            payloads.set_lamp(stimulus=9, instance=line, lamp_mode=2),
            payloads.call_state(payloads.CALL_STATE_OFFHOOK, line, ref),
            payloads.select_soft_keys(line, ref, softkey_set_index=4),
            payloads.legacy_display_prompt_dial(line, ref),
            payloads.activate_call_plane(line),
            payloads.start_tone(payloads.TONE_DIAL, line, ref, legacy=False, direction=0),
        ]

    def _on_keypad(self, payload: bytes) -> bool:
        if len(payload) < 4:
            return True
        kp_button = struct.unpack("<I", payload[:4])[0]
        ch = keypad_to_char(kp_button)
        if ch:
            self.hub.on_digit(self, ch)
        return True

    @staticmethod
    def _read_u32(payload: bytes, default: int = 0) -> int:
        if len(payload) < 4:
            return default
        return struct.unpack("<I", payload[:4])[0]

    def disconnect(self) -> None:
        """Force-close the Skinny TCP session (phone should re-register)."""
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass
