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


def char_to_keypad_code(ch: str) -> int | None:
    if len(ch) == 1 and ch.isdigit():
        return int(ch)
    if ch == "*":
        return 0x0E
    if ch == "#":
        return 0x0F
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
    transfer_active: bool = False
    transfer_initiator: SkinnySession | None = None
    transfer_digits: str = ""
    transfer_consult_ref: int | None = None
    transfer_primary_ref: int | None = None
    conference: bool = False
    third_party: SkinnySession | None = None
    conference_active: bool = False
    conference_initiator: SkinnySession | None = None
    conference_digits: str = ""
    conference_consult_ref: int | None = None
    conference_primary_ref: int | None = None
    held_by: SkinnySession | None = None


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
            held_call: SimCall | None = None
            if caller.active_call is not None:
                if caller.active_call.state != "held":
                    raise RuntimeError(f"{caller.device_name} already in a call")
                held_call = caller.active_call
            if call_ref_hint is not None and call_ref_hint > 0:
                call_ref = call_ref_hint
            else:
                call_ref = self._alloc_call_ref()
            call = SimCall(call_ref=call_ref, caller=caller, state="dialing", line=max(1, line))
            self._calls[call_ref] = call
            caller.active_call = call
            if held_call and self.media_hub:
                self.media_hub.stop_call(held_call.call_ref)
            return call

    def on_digit(self, caller: SkinnySession, digit: str) -> None:
        call = caller.active_call
        if not call:
            return

        if call.ivr and call.state == "connected" and call.ivr_menu_active and self.ivr_menu:
            self.ivr_menu.on_keypad(call, digit, self)
            return

        if call.transfer_active:
            if caller is not call.transfer_initiator:
                return
            if digit == "#":
                consult = self._consult_for_primary(call)
                if consult and consult.state == "connected":
                    self._complete_consulted_transfer(call, consult, caller)
                else:
                    self._complete_blind_transfer(call)
                return
            call.transfer_digits += digit
            caller.send(
                payloads.dialed_number(
                    call.transfer_digits, line=call.line, call_ref=call.call_ref
                )
            )
            self._try_complete_transfer_dial(call)
            return

        if call.conference_active:
            if caller is not call.conference_initiator:
                return
            if digit == "#":
                consult = self._conference_consult_for_primary(call)
                if consult and consult.state == "connected":
                    self._complete_conference(call, consult, caller)
                else:
                    self._abort_conference(call)
                return
            call.conference_digits += digit
            caller.send(
                payloads.dialed_number(
                    call.conference_digits, line=call.line, call_ref=call.call_ref
                )
            )
            self._try_complete_conference_dial(call)
            return

        if call.state == "connected" and not (call.ivr and call.ivr_menu_active):
            code = char_to_keypad_code(digit)
            if code is None:
                return
            targets: list[SkinnySession] = []
            if caller is call.caller and call.callee:
                targets.append(call.callee)
            elif caller is call.callee and call.caller:
                targets.append(call.caller)
            targets.append(caller)
            seen: set[int] = set()
            for party in targets:
                pid = id(party)
                if pid in seen:
                    continue
                seen.add(pid)
                party.send(payloads.keypad_button(code, call.line, call.call_ref))
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
        call.held_by = session
        logger.info("Hold call ref=%s by %s", call.call_ref, session.device_name)
        self._notify_hold(call, holder=session)

    def resume(self, session: SkinnySession) -> None:
        call = session.active_call
        if not call or call.state != "held" or call.callee is None:
            return
        call.state = "connected"
        call.held_by = None
        call.media_ports.clear()
        logger.info("Resume call ref=%s by %s", call.call_ref, session.device_name)
        self._notify_resumed(call)

    def _cancel_consult_leg(self, primary: SimCall, consult: SimCall) -> None:
        line, ref = consult.line, consult.call_ref
        if self.media_hub:
            self.media_hub.stop_call(ref)
        if consult.media_ports:
            for party in (consult.caller, consult.callee):
                if party is None:
                    continue
                party.send(payloads.stop_media_transmission(ref))
                party.send(payloads.close_receive_channel(ref))
            consult.media_ports.clear()
        for party in (consult.caller, consult.callee):
            if party is None:
                continue
            if party.active_call is consult:
                party.active_call = primary if party in (primary.caller, primary.callee) else None
            party.send(payloads.stop_tone(line, ref))
            party.send(payloads.call_state(payloads.CALL_STATE_ONHOOK, line, ref))
        self._calls.pop(consult.call_ref, None)
        if primary.transfer_consult_ref == consult.call_ref:
            primary.transfer_consult_ref = None
        if primary.conference_consult_ref == consult.call_ref:
            primary.conference_consult_ref = None
        consult.state = "ended"

    def on_conference_softkey(
        self,
        session: SkinnySession,
        *,
        line: int = 1,
        call_ref: int = 0,
    ) -> None:
        call = session.active_call
        if call_ref and call_ref in self._calls:
            hinted = self._calls[call_ref]
            if hinted.caller is session or hinted.callee is session or hinted.third_party is session:
                call = hinted
        if not call:
            return

        if call.conference_primary_ref:
            primary = self._calls.get(call.conference_primary_ref)
            if primary and call.state == "connected":
                self._complete_conference(primary, call, session)
            elif (
                primary
                and primary.conference_active
                and session is primary.conference_initiator
            ):
                self._abort_conference(primary)
            return

        if not call.ivr and call.conference_active:
            if session is call.conference_initiator:
                consult = self._conference_consult_for_primary(call)
                if consult and consult.state == "connected":
                    self._complete_conference(call, consult, session)
                else:
                    self._abort_conference(call)
            return

        if call.state != "connected" or call.ivr or call.conference:
            return
        self._begin_conference(call, session)

    def _conference_consult_for_primary(self, primary: SimCall) -> SimCall | None:
        ref = primary.conference_consult_ref
        if ref is None:
            return None
        return self._calls.get(ref)

    def _try_complete_conference_dial(self, call: SimCall) -> None:
        if not call.conference_active or not call.conference_initiator:
            return
        if call.conference_consult_ref is not None:
            return
        dn = call.conference_digits.strip()
        if not dn:
            return
        target = self.session_for_dn(dn)
        if not target or target is call.conference_initiator:
            return
        if target.active_call is not None:
            return
        self._start_consult_leg(
            call,
            target,
            mode="conference",
        )

    def _begin_conference(self, call: SimCall, initiator: SkinnySession) -> None:
        call.conference_active = True
        call.conference_initiator = initiator
        call.conference_digits = ""
        other = call.callee if initiator is call.caller else call.caller
        logger.info(
            "Conference begin ref=%s by %s (other=%s)",
            call.call_ref,
            initiator.device_name,
            other.device_name if other else "?",
        )
        initiator.send_many([
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_TRANSFER, call.line, call.call_ref),
            payloads.start_tone(
                payloads.TONE_DIAL, call.line, call.call_ref, legacy=initiator._legacy_phone
            ),
            payloads.display_prompt_status("Conference", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=1),
        ])
        if other:
            other.send_many([
                payloads.start_tone(
                    payloads.TONE_REMOTE_HOLD, call.line, call.call_ref, legacy=other._legacy_phone
                ),
                payloads.display_prompt_status("Remote Hold", call.line, call.call_ref),
            ])

    def _abort_conference(self, call: SimCall) -> None:
        consult = self._conference_consult_for_primary(call)
        holder = call.held_by or call.conference_initiator or call.caller
        if consult:
            self._cancel_consult_leg(call, consult)
        call.conference_active = False
        call.conference_initiator = None
        call.conference_digits = ""
        logger.info("Conference cancelled ref=%s", call.call_ref)
        if call.state == "held" and holder:
            self.resume(holder)

    def _complete_conference(
        self,
        primary: SimCall,
        consult: SimCall,
        initiator: SkinnySession,
    ) -> None:
        if consult.callee is None:
            return
        held = primary.callee if initiator is primary.caller else primary.caller
        new_party = consult.callee
        if held is None or held is initiator or new_party is initiator:
            return

        line, ref = primary.line, primary.call_ref
        logger.info(
            "Conference complete ref=%s %s + %s + %s",
            ref,
            initiator.device_name,
            held.device_name,
            new_party.device_name,
        )

        if self.media_hub:
            self.media_hub.stop_call(ref)
            self.media_hub.stop_call(consult.call_ref)

        for leg in (primary, consult):
            if not leg.media_ports:
                continue
            for party in (leg.caller, leg.callee):
                if party is None:
                    continue
                party.send(payloads.stop_media_transmission(leg.call_ref))
                party.send(payloads.close_receive_channel(leg.call_ref))
            leg.media_ports.clear()

        self._calls.pop(consult.call_ref, None)
        consult.state = "ended"

        primary.conference_active = False
        primary.conference_initiator = None
        primary.conference_digits = ""
        primary.conference_consult_ref = None
        primary.conference = True
        primary.third_party = new_party
        primary.state = "connected"
        primary.held_by = None
        primary.media_ports.clear()

        if initiator is primary.caller:
            primary.callee = held
        else:
            primary.caller = held

        for party in (initiator, held, new_party):
            party.active_call = primary

        line_c, ref_c = consult.line, consult.call_ref
        for party in (initiator, new_party):
            party.send(payloads.stop_tone(line_c, ref_c))
            party.send(
                payloads.call_state(payloads.CALL_STATE_ONHOOK, line_c, ref_c)
            )

        self._notify_conference_connected(primary)

    def _notify_conference_connected(self, call: SimCall) -> None:
        parties = [call.caller, call.callee, call.third_party]
        parties = [p for p in parties if p is not None]
        caller = call.caller
        callee = call.callee
        third = call.third_party
        caller_name = caller.device_name
        callee_name = callee.device_name if callee else ""
        third_name = third.device_name if third else ""
        caller_dn = caller.directory_number
        callee_dn = callee.directory_number if callee else ""
        third_dn = third.directory_number if third else ""
        line, ref = call.line, call.call_ref

        for party in parties:
            remote_dn = third_dn if party in (caller, callee) else caller_dn
            if party is third:
                remote_dn = caller_dn
            party.awaiting_media_ack = False
            party.send_many([
                payloads.stop_tone(line, ref),
                payloads.call_state(payloads.CALL_STATE_CONNECTED, line, ref),
                payloads.call_info(
                    caller_name, caller_dn, callee_name or third_name, remote_dn,
                    line=line, call_ref=ref,
                    call_type=2 if party is caller else 1,
                ),
                payloads.display_prompt_status("Conference", line, ref),
                payloads.select_soft_keys(line, ref, softkey_set_index=1),
                payloads.open_receive_channel(ref),
            ])
            party.awaiting_media_ack = True

    def on_transfer_softkey(self, session: SkinnySession) -> None:
        call = session.active_call
        if not call:
            return

        if call.transfer_primary_ref:
            primary = self._calls.get(call.transfer_primary_ref)
            if primary and call.state == "connected":
                self._complete_consulted_transfer(primary, call, session)
            elif (
                primary
                and primary.transfer_active
                and session is primary.transfer_initiator
            ):
                self._complete_blind_transfer(primary)
            return

        if not call.ivr and call.transfer_active:
            if session is call.transfer_initiator:
                consult = self._consult_for_primary(call)
                if consult and consult.state == "connected":
                    self._complete_consulted_transfer(call, consult, session)
                else:
                    self._complete_blind_transfer(call)
            return

        if call.state != "connected" or call.ivr:
            return
        self._begin_transfer(call, session)

    def _consult_for_primary(self, primary: SimCall) -> SimCall | None:
        ref = primary.transfer_consult_ref
        if ref is None:
            return None
        return self._calls.get(ref)

    def _try_complete_transfer_dial(self, call: SimCall) -> None:
        if not call.transfer_active or not call.transfer_initiator:
            return
        if call.transfer_consult_ref is not None:
            return
        dn = call.transfer_digits.strip()
        if not dn:
            return
        target = self.session_for_dn(dn)
        if not target or target is call.transfer_initiator:
            return
        if target.active_call is not None:
            return
        self._start_consult_leg(call, target, mode="transfer")

    def _start_consult_leg(
        self,
        primary: SimCall,
        target: SkinnySession,
        *,
        mode: str = "transfer",
    ) -> None:
        if mode == "conference":
            initiator = primary.conference_initiator
            dn = primary.conference_digits.strip()
            primary_ref_attr = "conference_consult_ref"
            consult_primary_attr = "conference_primary_ref"
            log_label = "Conference consult"
        else:
            initiator = primary.transfer_initiator
            dn = primary.transfer_digits.strip()
            primary_ref_attr = "transfer_consult_ref"
            consult_primary_attr = "transfer_primary_ref"
            log_label = "Consult transfer"

        if initiator is None:
            return
        other = primary.callee if initiator is primary.caller else primary.caller

        logger.info(
            "%s dial ref=%s by %s -> DN %s (held=%s)",
            log_label,
            primary.call_ref,
            initiator.device_name,
            dn,
            other.device_name if other else "?",
        )

        if primary.state != "held":
            primary.state = "held"
            primary.held_by = initiator
            self._notify_hold(primary, holder=initiator)

        try:
            consult = self.begin_outbound(initiator, line=primary.line)
        except RuntimeError:
            logger.warning("%s: could not start outbound for %s", log_label, initiator.device_name)
            return

        consult.dialed = dn
        setattr(consult, consult_primary_attr, primary.call_ref)
        setattr(primary, primary_ref_attr, consult.call_ref)

        consult.callee = target
        consult.state = "ringing"
        target.active_call = consult

        caller_name = initiator.device_name
        callee_name = target.device_name
        caller_dn = initiator.directory_number
        callee_dn = target.directory_number
        line, ref = consult.line, consult.call_ref

        consult.caller.send_many([
            payloads.stop_tone(line, ref),
            payloads.call_state(payloads.CALL_STATE_RINGOUT, line, ref),
            payloads.call_info(
                caller_name, caller_dn, callee_name, callee_dn,
                line=line, call_ref=ref, call_type=2,
            ),
            payloads.display_prompt_status("Ring Out", line, ref),
            payloads.select_soft_keys(line, ref, softkey_set_index=8),
        ])

        ring_common = [payloads.call_state(payloads.CALL_STATE_RINGIN, line, ref)]
        if target._legacy_phone:
            target.send_many(
                ring_common
                + [
                    payloads.select_soft_keys(line, ref, softkey_set_index=3),
                    payloads.legacy_display_text(caller_dn, line, ref),
                    payloads.display_pri_notify(caller_dn),
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=line, call_ref=ref, call_type=1,
                    ),
                ]
                + self._legacy_ring_in_tail(consult)
            )
        else:
            target.send_many(
                ring_common
                + [
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=line, call_ref=ref, call_type=1,
                    ),
                    payloads.start_tone(payloads.TONE_RING, line, ref),
                    payloads.display_prompt_status("Ring In", line, ref),
                    payloads.select_soft_keys(line, ref, softkey_set_index=3),
                ]
            )

        if self.should_auto_answer(target):
            threading.Thread(
                target=self._auto_answer_after_delay,
                args=(target,),
                name=f"auto-answer-{target.device_name}",
                daemon=True,
            ).start()

    def _begin_transfer(self, call: SimCall, initiator: SkinnySession) -> None:
        call.transfer_active = True
        call.transfer_initiator = initiator
        call.transfer_digits = ""
        other = call.callee if initiator is call.caller else call.caller
        logger.info(
            "Transfer begin ref=%s by %s (other=%s)",
            call.call_ref,
            initiator.device_name,
            other.device_name if other else "?",
        )
        initiator.send_many([
            payloads.stop_tone(call.line, call.call_ref),
            payloads.call_state(payloads.CALL_STATE_TRANSFER, call.line, call.call_ref),
            payloads.start_tone(
                payloads.TONE_DIAL, call.line, call.call_ref, legacy=initiator._legacy_phone
            ),
            payloads.display_prompt_status("Transfer to", call.line, call.call_ref),
            payloads.select_soft_keys(call.line, call.call_ref, softkey_set_index=1),
        ])
        if other:
            other.send_many([
                payloads.start_tone(
                    payloads.TONE_REMOTE_HOLD, call.line, call.call_ref, legacy=other._legacy_phone
                ),
                payloads.display_prompt_status("Remote Hold", call.line, call.call_ref),
            ])

    def _complete_blind_transfer(self, call: SimCall) -> None:
        if not call.transfer_active or not call.transfer_initiator:
            return
        target_dn = call.transfer_digits.strip()
        if not target_dn:
            logger.info("Blind transfer cancelled ref=%s (no digits)", call.call_ref)
            call.transfer_active = False
            call.transfer_initiator = None
            call.transfer_digits = ""
            return
        initiator = call.transfer_initiator
        remaining = call.callee if initiator is call.caller else call.caller
        if remaining is None:
            return
        consult = self._consult_for_primary(call)
        if consult:
            self._cancel_consult_leg(call, consult)
        logger.info(
            "Blind transfer complete ref=%s %s -> DN %s (remaining=%s)",
            call.call_ref,
            initiator.device_name,
            target_dn,
            remaining.device_name,
        )
        call.transfer_active = False
        call.transfer_initiator = None
        call.transfer_digits = ""
        self._execute_blind_transfer(call, initiator, remaining, target_dn)

    def _execute_blind_transfer(
        self,
        call: SimCall,
        initiator: SkinnySession,
        remaining: SkinnySession,
        target_dn: str,
    ) -> None:
        line, ref = call.line, call.call_ref

        if self.media_hub:
            self.media_hub.stop_call(ref)

        if call.media_ports:
            for party in (initiator, remaining):
                party.send(payloads.stop_media_transmission(ref))
                party.send(payloads.close_receive_channel(ref))
            call.media_ports.clear()

        self._send_party_on_hook(initiator, line, ref)

        call.caller = remaining
        call.callee = None
        call.dialed = target_dn
        call.state = "dialing"
        call.ivr = False
        call.ivr_menu_active = False
        remaining.active_call = call

        remaining.send_many([
            payloads.stop_tone(line, ref),
            payloads.call_state(payloads.CALL_STATE_OFFHOOK, line, ref),
            payloads.activate_call_plane(line),
            payloads.call_state(payloads.CALL_STATE_PROCEED, line, ref),
            payloads.start_tone(
                payloads.TONE_DIAL, line, ref, legacy=remaining._legacy_phone, direction=2
            ),
            payloads.display_prompt_status("Transfer", line, ref),
            payloads.select_soft_keys(line, ref, softkey_set_index=8),
        ])
        self._try_complete_dial(call)

    def _complete_consulted_transfer(
        self,
        primary: SimCall,
        consult: SimCall,
        initiator: SkinnySession,
    ) -> None:
        if consult.callee is None:
            return
        remaining = primary.callee if initiator is primary.caller else primary.caller
        target = consult.callee
        if remaining is None or remaining is initiator or target is initiator:
            return

        line, ref = primary.line, primary.call_ref
        logger.info(
            "Consult transfer complete ref=%s %s -> %s (remaining=%s)",
            ref,
            initiator.device_name,
            target.directory_number,
            remaining.device_name,
        )

        if self.media_hub:
            self.media_hub.stop_call(ref)
            self.media_hub.stop_call(consult.call_ref)

        for leg in (primary, consult):
            if not leg.media_ports:
                continue
            for party in (leg.caller, leg.callee):
                if party is None:
                    continue
                party.send(payloads.stop_media_transmission(leg.call_ref))
                party.send(payloads.close_receive_channel(leg.call_ref))
            leg.media_ports.clear()

        self._send_party_on_hook(initiator, consult.line, consult.call_ref)
        if consult.call_ref != ref:
            initiator.active_call = None
            initiator.awaiting_media_ack = False
            initiator.send(payloads.stop_tone(line, ref))
            initiator.send(
                payloads.call_state(payloads.CALL_STATE_ONHOOK, line, ref)
            )

        self._calls.pop(consult.call_ref, None)
        consult.state = "ended"
        if target.active_call is consult:
            target.active_call = None

        primary.transfer_active = False
        primary.transfer_initiator = None
        primary.transfer_digits = ""
        primary.transfer_consult_ref = None
        primary.caller = remaining
        primary.callee = target
        primary.state = "connected"
        primary.ivr = False
        primary.ivr_menu_active = False
        primary.dialed = target.directory_number or ""
        primary.held_by = None
        primary.media_ports.clear()

        remaining.active_call = primary
        target.active_call = primary

        caller_name = remaining.device_name
        callee_name = target.device_name
        caller_dn = remaining.directory_number
        callee_dn = target.directory_number

        for party in (remaining, target):
            if party._legacy_phone and party is target:
                party.send_many(
                    self._legacy_callee_connect_packets(
                        primary,
                        caller_name=caller_name,
                        caller_dn=caller_dn,
                        callee_name=callee_name,
                        callee_dn=callee_dn,
                    )
                )
            else:
                party.send_many(
                    self._modern_connect_packets(
                        primary,
                        party,
                        caller_name=caller_name,
                        caller_dn=caller_dn,
                        callee_name=callee_name,
                        callee_dn=callee_dn,
                    )
                )
            party.awaiting_media_ack = True

    def _send_party_on_hook(self, party: SkinnySession, line: int, call_ref: int) -> None:
        party.active_call = None
        party.awaiting_media_ack = False
        if party._legacy_phone:
            party.send_many([
                payloads.stop_tone(line, call_ref),
                payloads.set_lamp(stimulus=9, instance=line, lamp_mode=1),
                payloads.clear_prompt_status(line, call_ref),
                payloads.call_state(payloads.CALL_STATE_ONHOOK, line, call_ref),
                payloads.legacy_select_softkeys_onhook(),
                payloads.display_prompt_status("Ready", line, 0),
            ])
        else:
            party.send_many([
                payloads.stop_tone(line, call_ref),
                payloads.call_state(payloads.CALL_STATE_ONHOOK, line, call_ref),
                payloads.display_prompt_status("Ready", line, 0),
                payloads.select_soft_keys(line, 0, softkey_set_index=0),
            ])

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

        if call.conference and call.third_party:
            parties = [p for p in (call.caller, call.callee, call.third_party) if p]
            if not all(id(p) in call.media_ports for p in parties):
                return
            if self.media_hub and self.media_hub.start_conference(call):
                logger.info(
                    "Conference media started ref=%s via SimMediaHub (%s)",
                    call.call_ref,
                    self.media_hub.mode,
                )
                return
            caller_ip = ip_to_le_int(call.caller.station_ip)
            for party in (call.callee, call.third_party):
                if party is None:
                    continue
                peer_ip = ip_to_le_int(party.station_ip)
                peer_port = call.media_ports[id(party)]
                call.caller.send(
                    payloads.start_media_transmission(call.call_ref, peer_ip, peer_port)
                )
                party.send(
                    payloads.start_media_transmission(
                        call.call_ref, caller_ip, call.media_ports[id(call.caller)]
                    )
                )
            logger.info(
                "Conference media started ref=%s (hub %s -> %s, %s)",
                call.call_ref,
                call.caller.device_name,
                call.callee.device_name if call.callee else "?",
                call.third_party.device_name if call.third_party else "?",
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

    def _other_calls_for_party(
        self, party: SkinnySession, *, exclude_ref: int | None = None
    ) -> list[SimCall]:
        calls: list[SimCall] = []
        for ref, call in self._calls.items():
            if exclude_ref is not None and ref == exclude_ref:
                continue
            if party not in (call.caller, call.callee, call.third_party):
                continue
            if call.state in ("held", "connected", "ringing", "dialing"):
                calls.append(call)
        return calls

    def _pick_focus_call(self, calls: list[SimCall]) -> SimCall | None:
        if not calls:
            return None
        order = {"held": 0, "connected": 1, "ringing": 2, "dialing": 3}
        return sorted(calls, key=lambda c: (order.get(c.state, 9), -c.call_ref))[0]

    def _send_party_idle(self, party: SkinnySession, line: int, ended_ref: int) -> None:
        party.awaiting_media_ack = False
        if party._legacy_phone:
            party.send_many([
                payloads.stop_tone(line, ended_ref),
                payloads.set_lamp(stimulus=9, instance=line, lamp_mode=1),
                payloads.clear_prompt_status(line, ended_ref),
                payloads.call_state(payloads.CALL_STATE_ONHOOK, line, ended_ref),
                payloads.legacy_select_softkeys_onhook(),
                payloads.time_date_res(),
                payloads.set_speaker_mode(0),
            ])
        else:
            party.send_many([
                payloads.stop_tone(line, ended_ref),
                payloads.call_state(payloads.CALL_STATE_ONHOOK, line, ended_ref),
                payloads.display_prompt_status("Ready", line, 0),
                payloads.select_soft_keys(line, 0, softkey_set_index=0),
            ])

    def _send_party_focus(self, party: SkinnySession, call: SimCall) -> None:
        caller = call.caller
        callee = call.callee
        caller_name = caller.device_name
        callee_name = callee.device_name if callee else ""
        caller_dn = caller.directory_number
        callee_dn = callee.directory_number if callee else ""
        line, ref = call.line, call.call_ref

        if call.state == "held":
            holder = call.held_by or caller
            if party is holder:
                party.send_many([
                    payloads.stop_tone(line, ref),
                    payloads.call_state(payloads.CALL_STATE_HOLD, line, ref),
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=line, call_ref=ref,
                        call_type=2 if holder is caller else 1,
                    ),
                    payloads.start_tone(payloads.TONE_HOLD, line, ref),
                    payloads.display_prompt_status("On Hold", line, ref),
                    payloads.select_soft_keys(line, ref, softkey_set_index=2),
                ])
            else:
                party.send_many([
                    payloads.stop_tone(line, ref),
                    payloads.call_state(payloads.CALL_STATE_HOLD, line, ref),
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=line, call_ref=ref,
                        call_type=2 if party is caller else 1,
                    ),
                    payloads.start_tone(payloads.TONE_REMOTE_HOLD, line, ref),
                    payloads.display_prompt_status("Remote Hold", line, ref),
                    payloads.select_soft_keys(line, ref, softkey_set_index=2),
                ])
            return

        if call.state == "connected" and callee is not None:
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
            return

        if call.state == "ringing" and callee is not None:
            if party is callee:
                if callee._legacy_phone:
                    party.send_many([
                        payloads.call_state(payloads.CALL_STATE_RINGIN, line, ref),
                        payloads.select_soft_keys(line, ref, softkey_set_index=3),
                        payloads.legacy_display_text(caller_dn, line, ref),
                        payloads.display_pri_notify(caller_dn),
                        payloads.call_info(
                            caller_name, caller_dn, callee_name, callee_dn,
                            line=line, call_ref=ref, call_type=1,
                        ),
                    ] + self._legacy_ring_in_tail(call))
                else:
                    party.send_many([
                        payloads.call_state(payloads.CALL_STATE_RINGIN, line, ref),
                        payloads.call_info(
                            caller_name, caller_dn, callee_name, callee_dn,
                            line=line, call_ref=ref, call_type=1,
                        ),
                        payloads.start_tone(payloads.TONE_RING, line, ref),
                        payloads.display_prompt_status("Ring In", line, ref),
                        payloads.select_soft_keys(line, ref, softkey_set_index=3),
                    ])
            elif party is caller:
                party.send_many([
                    payloads.stop_tone(line, ref),
                    payloads.call_state(payloads.CALL_STATE_RINGOUT, line, ref),
                    payloads.call_info(
                        caller_name, caller_dn, callee_name, callee_dn,
                        line=line, call_ref=ref, call_type=2,
                    ),
                    payloads.display_prompt_status("Ring Out", line, ref),
                    payloads.select_soft_keys(line, ref, softkey_set_index=8),
                ])

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
            if call.third_party:
                parties.append(call.third_party)

            if self.media_hub:
                self.media_hub.stop_call(call.call_ref)

            seen: set[int] = set()
            for party in parties:
                pid = id(party)
                if pid in seen:
                    continue
                seen.add(pid)

                if call.media_ports:
                    party.send(payloads.stop_media_transmission(call.call_ref))
                    party.send(payloads.close_receive_channel(call.call_ref))
                if party.active_call and party.active_call.call_ref == call_ref:
                    party.active_call = None

                party.send(payloads.stop_tone(call.line, call.call_ref))
                party.send(
                    payloads.call_state(
                        payloads.CALL_STATE_ONHOOK, call.line, call.call_ref
                    )
                )

                remaining = self._other_calls_for_party(party)
                focus = self._pick_focus_call(remaining)
                if focus is None:
                    party.awaiting_media_ack = False
                    if party._legacy_phone:
                        party.send_many([
                            payloads.set_lamp(stimulus=9, instance=call.line, lamp_mode=1),
                            payloads.clear_prompt_status(call.line, call.call_ref),
                            payloads.legacy_select_softkeys_onhook(),
                            payloads.time_date_res(),
                            payloads.set_speaker_mode(0),
                        ])
                    else:
                        party.send_many([
                            payloads.display_prompt_status("Ready", call.line, 0),
                            payloads.select_soft_keys(call.line, 0, softkey_set_index=0),
                        ])
                else:
                    party.active_call = focus
                    self._send_party_focus(party, focus)

            logger.info("Call ended ref=%s", call.call_ref)
            if call.ivr and self.ivr_menu:
                self.ivr_menu.on_call_ended(call_ref)

    def _normalize_device(self, device: str) -> str:
        name = device.upper()
        if not name.startswith("SEP"):
            from utils.client import normalize_mac_address

            name = "SEP" + normalize_mac_address(name)
        return name

    def session_for_device(self, device: str) -> SkinnySession | None:
        name = self._normalize_device(device)
        with self._lock:
            return self._by_device.get(name)

    def snapshot_sessions(self) -> list[dict]:
        with self._lock:
            rows = []
            for device, session in sorted(self._by_device.items()):
                call = session.active_call
                rows.append(
                    {
                        "device": device,
                        "dn": session.directory_number or "",
                        "ip": session.addr[0],
                        "port": session.addr[1],
                        "legacy": session._legacy_phone,
                        "in_call": call is not None,
                        "call_state": call.state if call else "idle",
                        "call_ref": call.call_ref if call else None,
                    }
                )
            return rows

    def _device_admin_action(self, device: str, *, reset: bool) -> bool:
        session = self.session_for_device(device)
        if not session:
            return False
        if session.active_call:
            self.end_call(source=session)
        action = "Reset" if reset else "Restart"
        session.send(payloads.reset_device() if reset else payloads.restart_device())
        logger.info(
            "Admin %s %s (%s) -> Skinny %s",
            action,
            session.device_name,
            session.directory_number or "?",
            "0x0029" if reset else "0x0030",
        )
        return True

    def reset_device(self, device: str) -> bool:
        """Hard reset — like CUCM Reset (re-DHCP/TFTP/re-register on real phones)."""
        return self._device_admin_action(device, reset=True)

    def restart_device(self, device: str) -> bool:
        """Soft restart — like CUCM Restart (re-register; faster than reset)."""
        return self._device_admin_action(device, reset=False)

    def end_call_for_device(self, device: str) -> bool:
        session = self.session_for_device(device)
        if not session or not session.active_call:
            return False
        self.end_call(source=session)
        return True
