"""Inter-phone call routing for the Skinny simulator."""

from __future__ import annotations

import logging
import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from simulator import payloads
from simulator.ivr_menu import IvrMenu
from simulator.media_hub import SimMediaHub

if TYPE_CHECKING:
    from simulator.session import SkinnySession

logger = logging.getLogger(__name__)


def keypad_to_char(code: int) -> str | None:
    if 0 <= code <= 9:
        return str(code)
    if 0x30 <= code <= 0x39:
        return chr(code)
    if code == 0x0E:
        return "*"
    if code == 0x0F:
        return "#"
    return None


def ip_to_le_int(ip: str) -> int:
    return struct.unpack("<I", socket.inet_aton(ip))[0]


IVR_DEVICE_NAME = "SIMIVR"
IVR_DISPLAY_NAME = "Sim-IVR"


@dataclass
class SimCall:
    call_ref: int
    caller: SkinnySession
    callee: SkinnySession | None = None
    line: int = 1
    dialed: str = ""
    state: str = "idle"
    ivr: bool = False
    media_ports: dict = field(default_factory=dict)
    ivr_menu_active: bool = False


class CallHub:
    """Routes calls between registered simulator sessions by DN."""

    def __init__(self, *, media_hub: SimMediaHub | None = None, ivr_dn: str | None = None):
        self._lock = threading.Lock()
        self._by_device: dict[str, SkinnySession] = {}
        self._by_dn: dict[str, SkinnySession] = {}
        self._calls: dict[int, SimCall] = {}
        self._next_call_ref = 16777216
        self.auto_answer_devices: set[str] = set()
        self.media_hub = media_hub
        self.ivr_dn = str(ivr_dn) if ivr_dn else None
        self.ivr_menu = IvrMenu() if self.ivr_dn else None

    def register_session(self, session: SkinnySession) -> None:
        with self._lock:
            self._by_device[session.device_name] = session
            if session.directory_number:
                self._by_dn[session.directory_number] = session

    def unregister_session(self, session: SkinnySession) -> None:
        with self._lock:
            self._by_device.pop(session.device_name, None)
            if session.directory_number:
                self._by_dn.pop(session.directory_number, None)
            for call_ref, call in list(self._calls.items()):
                if session in (call.caller, call.callee):
                    self.end_call(call_ref, source=session)

    def set_auto_answer(self, mac_or_sep: str) -> None:
        """Enable auto-answer for one device (* = all registered phones)."""
        name = mac_or_sep.upper()
        if name == "*":
            self.auto_answer_devices.add("*")
            return
        if not name.startswith("SEP"):
            from utils.client import normalize_mac_address

            name = "SEP" + normalize_mac_address(name)
        self.auto_answer_devices.add(name)

    def session_for_dn(self, dn: str) -> SkinnySession | None:
        with self._lock:
            return self._by_dn.get(str(dn))

    def should_auto_answer(self, session: SkinnySession) -> bool:
        return "*" in self.auto_answer_devices or session.device_name in self.auto_answer_devices

    def _alloc_call_ref(self) -> int:
        ref = self._next_call_ref
        self._next_call_ref += 1
        return ref

    def begin_outbound(
        self,
        caller: SkinnySession,
        *,
        line: int = 1,
        call_ref_hint: int | None = None,
    ) -> SimCall:
        with self._lock:
            if caller.active_call is not None:
                raise RuntimeError(f"{caller.device_name} already in a call")
            if call_ref_hint is not None and call_ref_hint > 0:
                call_ref = call_ref_hint
            else:
                call_ref = self._alloc_call_ref()
            call = SimCall(call_ref=call_ref, caller=caller, state="dialing", line=max(1, line))
            self._calls[call_ref] = call
            caller.active_call = call
            return call

    def on_digit(self, caller: SkinnySession, digit: str) -> None:
        call = caller.active_call
        if not call:
            return

        if call.ivr and call.state == "connected" and call.ivr_menu_active and self.ivr_menu:
            self.ivr_menu.on_keypad(call, digit, self)
            return

        if call.state != "dialing":
            return

        if digit == "#":
            self._try_complete_dial(call)
            return

        call.dialed += digit
        caller.send(
            payloads.dialed_number(call.dialed, line=call.line, call_ref=call.call_ref)
        )
        self._try_complete_dial(call)

    def _try_complete_dial(self, call: SimCall) -> None:
        if self.ivr_dn and call.dialed == self.ivr_dn:
            self._start_ivr_call(call)
            return

        callee = self.session_for_dn(call.dialed)
        if not callee or callee is call.caller:
            return
        if callee.active_call is not None:
            logger.info("Call to busy DN %s ignored", call.dialed)
            return

        call.callee = callee
        call.state = "ringing"
        callee.active_call = call

        caller_name = call.caller.device_name
        callee_name = callee.device_name
        caller_dn = call.caller.directory_number
        callee_dn = callee.directory_number

        logger.info(
            "Ringing %s (%s) <- %s (%s) ref=%s",
            callee_name,
            callee_dn,
            caller_name,
            caller_dn,
            call.call_ref,
        )

        call.caller.send_many([
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_RINGOUT, call.line, call.call_ref),
            payloads.call_info(
                caller_name, caller_dn, callee_name, callee_dn,
                line=call.line, call_ref=call.call_ref, call_type=2,
            ),
            payloads.display_prompt_status("Ring Out", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=8),
        ])

        ring_common = [
            payloads.call_state(payloads.CALL_STATE_RINGIN, call.line, call.call_ref),
        ]
        if callee._legacy_phone:
            call.callee.send_many(
                ring_common
                + [
                    payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=3),
                    payloads.legacy_display_text(caller_dn, call.line, call.call_ref),
                    payloads.display_pri_notify(caller_dn),
                ]
                + [
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=call.line, call_ref=call.call_ref, call_type=1,
                    ),
                ]
                + self._legacy_ring_in_tail(call)
            )
        else:
            call.callee.send_many(
                ring_common
                + [
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=call.line, call_ref=call.call_ref, call_type=1,
                    ),
                    payloads.start_tone(payloads.TONE_RING, call.line, call.call_ref),
                    payloads.display_prompt_status("Ring In", call.line, call.call_ref),
                    payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=3),
                ]
            )

        if self.should_auto_answer(callee):
            threading.Thread(
                target=self._auto_answer_after_delay,
                args=(callee,),
                name=f"auto-answer-{callee.device_name}",
                daemon=True,
            ).start()

    def _start_ivr_call(self, call: SimCall) -> None:
        assert self.ivr_dn is not None
        call.ivr = True
        call.state = "ringing"

        caller = call.caller
        caller_name = caller.device_name
        caller_dn = caller.directory_number

        logger.info(
            "IVR ring %s <- %s (%s) ref=%s",
            self.ivr_dn,
            caller_name,
            caller_dn,
            call.call_ref,
        )

        call.caller.send_many([
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_RINGOUT, call.line, call.call_ref),
            payloads.call_info(
                caller_name, caller_dn, IVR_DEVICE_NAME, self.ivr_dn,
                line=call.line, call_ref=call.call_ref, call_type=2,
            ),
            payloads.display_prompt_status("Ring Out", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=8),
        ])

        threading.Thread(
            target=self._auto_connect_ivr,
            args=(call,),
            name=f"ivr-answer-{call.call_ref}",
            daemon=True,
        ).start()

    def _auto_connect_ivr(self, call: SimCall) -> None:
        import time

        time.sleep(0.25)
        with self._lock:
            if call.call_ref not in self._calls:
                return
        self._connect_ivr(call)

    def _connect_ivr(self, call: SimCall) -> None:
        assert self.ivr_dn is not None
        with self._lock:
            if call.call_ref not in self._calls:
                return
        call.state = "connected"
        caller = call.caller
        caller_name = caller.device_name
        caller_dn = caller.directory_number

        logger.info("IVR connect ref=%s %s -> %s", call.call_ref, caller_dn, self.ivr_dn)

        caller.send_many(
            self._ivr_caller_connect_packets(
                call,
                caller_name=caller_name,
                caller_dn=caller_dn,
                legacy=caller._legacy_phone,
            )
        )
        caller.awaiting_media_ack = True

    @staticmethod
    def _ivr_caller_connect_packets(
        call: SimCall,
        *,
        caller_name: str,
        caller_dn: str,
        legacy: bool,
    ) -> list[bytes]:
        """Outbound caller connected to virtual IVR — EndCall-only softkeys."""
        line, ref = call.line, call.call_ref
        ivr_dn = call.dialed or ""
        common_tail = [
            payloads.open_receive_channel(ref),
            payloads.select_soft_keys(line, ref, softkey_set_index=4),
        ]
        if legacy:
            return [
                payloads.stop_tone(line, ref),
                payloads.call_state(payloads.CALL_STATE_CONNECTED, line, ref),
                payloads.select_soft_keys(line, ref, softkey_set_index=4),
                payloads.legacy_display_text(ivr_dn, line, ref),
                payloads.call_info(
                    caller_name, caller_dn, IVR_DEVICE_NAME, ivr_dn,
                    line=line, call_ref=ref, call_type=2,
                ),
                *common_tail,
            ]
        return [
            payloads.stop_tone(line, ref),
            payloads.call_state(payloads.CALL_STATE_CONNECTED, line, ref),
            payloads.call_info(
                caller_name, caller_dn, IVR_DEVICE_NAME, ivr_dn,
                line=line, call_ref=ref, call_type=2,
            ),
            payloads.display_prompt_status("Connected", line, ref),
            payloads.select_soft_keys(line, ref, softkey_set_index=4),
            *common_tail,
        ]

    @staticmethod
    def _legacy_ring_in_tail(call: SimCall) -> list[bytes]:
        line, ref = call.line, call.call_ref
        sk = payloads.select_soft_keys(line, ref, softkey_set_index=3)
        return [
            payloads.set_lamp(stimulus=9, instance=line, lamp_mode=5),
            payloads.set_ringer(2, 1, line, ref),
            sk,
        ]

    @staticmethod
    def _legacy_callee_connect_packets(
        call: SimCall,
        *,
        caller_name: str,
        caller_dn: str,
        callee_name: str,
        callee_dn: str,
    ) -> list[bytes]:
        """7912 answer/off-hook path from cm_call_from_pyskinny_to_7912.pcapng frames 141-153."""
        line, ref = call.line, call.call_ref
        return [
            payloads.set_ringer(1, 1, 0, 0),
            payloads.set_speaker_mode(1),
            payloads.set_lamp(stimulus=9, instance=line, lamp_mode=2),
            payloads.call_state(payloads.CALL_STATE_OFFHOOK, line, ref),
            payloads.activate_call_plane(line),
            payloads.set_ringer(1, 1, line, ref),
            payloads.stop_tone(line, ref),
            payloads.open_receive_channel(ref),
            payloads.stop_tone(line, ref),
            payloads.call_state(payloads.CALL_STATE_CONNECTED, line, ref),
            payloads.select_soft_keys(line, ref, softkey_set_index=1, valid_key_mask=0xFFFFFDFF),
            payloads.legacy_display_text(caller_dn, line, ref),
            payloads.call_info(
                caller_name, caller_dn, callee_name, callee_dn,
                line=line, call_ref=ref, call_type=1,
            ),
        ]

    @staticmethod
    def _modern_connect_packets(
        call: SimCall,
        party: SkinnySession,
        *,
        caller_name: str,
        caller_dn: str,
        callee_name: str,
        callee_dn: str,
    ) -> list[bytes]:
        return [
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_CONNECTED, call.line, call.call_ref),
            payloads.call_info(
                caller_name, caller_dn, callee_name, callee_dn,
                line=call.line, call_ref=call.call_ref,
                call_type=2 if party is call.caller else 1,
            ),
            payloads.display_prompt_status("Connected", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=1),
            payloads.open_receive_channel(call.call_ref),
        ]

    def _auto_answer_after_delay(self, session: SkinnySession) -> None:
        import time

        time.sleep(0.25)
        self.answer(session)

    def answer(self, session: SkinnySession) -> None:
        call = session.active_call
        if not call or call.state != "ringing":
            return
        if session is not call.callee:
            return
        self._connect(call)

    def _connect(self, call: SimCall) -> None:
        assert call.callee is not None
        call.state = "connected"
        caller = call.caller
        callee = call.callee
        caller_name = caller.device_name
        callee_name = callee.device_name
        caller_dn = caller.directory_number
        callee_dn = callee.directory_number

        logger.info("Connect call ref=%s %s <-> %s", call.call_ref, caller_dn, callee_dn)

        for party in (caller, callee):
            if party._legacy_phone and party is callee:
                party.send_many(
                    self._legacy_callee_connect_packets(
                        call,
                        caller_name=caller_name,
                        caller_dn=caller_dn,
                        callee_name=callee_name,
                        callee_dn=callee_dn,
                    )
                )
            else:
                party.send_many(
                    self._modern_connect_packets(
                        call,
                        party,
                        caller_name=caller_name,
                        caller_dn=caller_dn,
                        callee_name=callee_name,
                        callee_dn=callee_dn,
                    )
                )
            party.awaiting_media_ack = True

    def hold(self, session: SkinnySession) -> None:
        call = session.active_call
        if not call or call.state != "connected" or call.callee is None:
            return
        call.state = "held"
        logger.info("Hold call ref=%s by %s", call.call_ref, session.device_name)
        self._notify_hold(call, holder=session)

    def resume(self, session: SkinnySession) -> None:
        call = session.active_call
        if not call or call.state != "held" or call.callee is None:
            return
        call.state = "connected"
        call.media_ports.clear()
        logger.info("Resume call ref=%s by %s", call.call_ref, session.device_name)
        self._notify_resumed(call)

    def _notify_hold(self, call: SimCall, *, holder: SkinnySession) -> None:
        assert call.callee is not None
        remote = call.callee if holder is call.caller else call.caller
        caller_name = call.caller.device_name
        callee_name = call.callee.device_name
        caller_dn = call.caller.directory_number
        callee_dn = call.callee.directory_number

        holder.send_many([
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_HOLD, call.line, call.call_ref),
            payloads.call_info(
                caller_name, caller_dn, callee_name, callee_dn,
                line=call.line, call_ref=call.call_ref,
                call_type=2 if holder is call.caller else 1,
            ),
            payloads.start_tone(payloads.TONE_HOLD, call.line, call.call_ref),
            payloads.display_prompt_status("On Hold", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=2),
        ])

        remote.send_many([
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_HOLD, call.line, call.call_ref),
            payloads.call_info(
                caller_name, caller_dn, callee_name, callee_dn,
                line=call.line, call_ref=call.call_ref,
                call_type=2 if remote is call.caller else 1,
            ),
            payloads.start_tone(payloads.TONE_REMOTE_HOLD, call.line, call.call_ref),
            payloads.display_prompt_status("Remote Hold", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=2),
        ])

    def _notify_resumed(self, call: SimCall) -> None:
        assert call.callee is not None
        caller = call.caller
        callee = call.callee
        caller_name = caller.device_name
        callee_name = callee.device_name
        caller_dn = caller.directory_number
        callee_dn = callee.directory_number

        for party in (caller, callee):
            party.awaiting_media_ack = False
            party.send_many([
                payloads.stop_tone(call.line, call.call_ref),
                payloads.call_state(payloads.CALL_STATE_CONNECTED, call.line, call.call_ref),
                payloads.call_info(
                    caller_name, caller_dn, callee_name, callee_dn,
                    line=call.line, call_ref=call.call_ref,
                    call_type=2 if party is caller else 1,
                ),
                payloads.display_prompt_status("Connected", call.line, call.call_ref),
                payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=1),
                payloads.open_receive_channel(call.call_ref),
            ])
            party.awaiting_media_ack = True

    def on_media_ack(self, session: SkinnySession, payload: bytes) -> None:
        call = session.active_call
        if not call or call.state != "connected":
            return
        if len(payload) < 12:
            logger.debug(
                "(%s) OpenReceiveChannelAck too short (%d bytes)",
                session.device_name,
                len(payload),
            )
            return

        port = struct.unpack("<I", payload[8:12])[0]
        call.media_ports[id(session)] = port
        session.awaiting_media_ack = False

        if call.ivr:
            if session is not call.caller:
                return
            if self.media_hub and self.media_hub.start_call(call):
                call.ivr_menu_active = True
                logger.info(
                    "IVR media started ref=%s via SimMediaHub (%s)",
                    call.call_ref,
                    self.media_hub.mode,
                )
                if self.ivr_menu:
                    self.ivr_menu.on_media_started(call, self)
            else:
                logger.warning(
                    "IVR call ref=%s connected but no SimMediaHub (--rtp-sim-peer or --ivr-dn enables tone)",
                    call.call_ref,
                )
            return

        if call.callee is None:
            return
        if id(call.caller) not in call.media_ports or id(call.callee) not in call.media_ports:
            return

        caller_ip = ip_to_le_int(call.caller.station_ip)
        callee_ip = ip_to_le_int(call.callee.station_ip)
        caller_port = call.media_ports[id(call.caller)]
        callee_port = call.media_ports[id(call.callee)]

        if self.media_hub and self.media_hub.start_call(call):
            logger.info(
                "Media started ref=%s via SimMediaHub (%s)",
                call.call_ref,
                self.media_hub.mode,
            )
            return

        call.caller.send(
            payloads.start_media_transmission(call.call_ref, callee_ip, callee_port)
        )
        call.callee.send(
            payloads.start_media_transmission(call.call_ref, caller_ip, caller_port)
        )
        logger.info(
            "Media started ref=%s (%s:%s <-> %s:%s)",
            call.call_ref,
            call.caller.station_ip,
            caller_port,
            call.callee.station_ip,
            callee_port,
        )

    def end_call(self, call_ref: int | None = None, *, source: SkinnySession | None = None) -> None:
        with self._lock:
            if call_ref is None and source and source.active_call:
                call_ref = source.active_call.call_ref
            if call_ref is None:
                return
            call = self._calls.pop(call_ref, None)
            if not call:
                return

            call.state = "ended"
            parties = [call.caller]
            if call.callee:
                parties.append(call.callee)

            if self.media_hub:
                self.media_hub.stop_call(call.call_ref)

            for party in parties:
                if call.media_ports:
                    party.send(payloads.stop_media_transmission(call.call_ref))
                    party.send(payloads.close_receive_channel(call.call_ref))
                party.active_call = None
                party.awaiting_media_ack = False
                if party._legacy_phone:
                    party.send_many([
                        payloads.stop_tone(call.line, call.call_ref),
                        payloads.set_lamp(stimulus=9, instance=call.line, lamp_mode=1),
                        payloads.clear_prompt_status(call.line, call.call_ref),
                        payloads.call_state(payloads.CALL_STATE_ONHOOK, call.line, call.call_ref),
                        payloads.legacy_select_softkeys_onhook(),
                        payloads.time_date_res(),
                        payloads.set_speaker_mode(0),
                    ])
                else:
                    party.send_many([
                        payloads.stop_tone(call.line, call.call_ref),
                        payloads.call_state(payloads.CALL_STATE_ONHOOK, call.line, call.call_ref),
                        payloads.display_prompt_status("Ready", call.line, 0),
                        payloads.select_soft_keys(call.line, 0, softkey_set_index=0),
                    ])

            logger.info("Call ended ref=%s", call.call_ref)
            if call.ivr and self.ivr_menu:
                self.ivr_menu.on_call_ended(call_ref)
