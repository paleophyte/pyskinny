"""Simulator-side RTP endpoints (tone / loopback / bridge) — no SCCP client required."""

from __future__ import annotations

import logging
import struct
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from audio_worker import EchoSource, RTPReceiver, RTPSender, wire_rtp_loopback
from simulator import payloads
from utils.media_codecs import DEFAULT_SKINNY_COMPRESSION, resolve_rtp_payload_type

if TYPE_CHECKING:
    from simulator.call_hub import SimCall
    from simulator.session import SkinnySession

logger = logging.getLogger(__name__)


def _ip_to_le_int(ip: str) -> int:
    return struct.unpack("<I", socket.inet_aton(ip))[0]


@dataclass
class _PartyLeg:
    session: SkinnySession
    phone_port: int
    rx: RTPReceiver
    tx: RTPSender | None = None
    echo: EchoSource | None = None


@dataclass
class SimMediaSession:
    call_ref: int
    legs: list[_PartyLeg] = field(default_factory=list)


class SimMediaHub:
    """
    CM-side RTP stub: bind UDP on the simulator host and participate in calls.

    Modes:
      - tone: send test tone to each party; StartMedia points phones at sim RX
      - loopback: echo each party's RTP back to that same party
      - bridge: forward A->B and B->A (sim replaces direct phone-to-phone RTP)
    """

    VALID_MODES = frozenset({"off", "tone", "loopback", "bridge"})

    def __init__(
        self,
        mode: str = "off",
        *,
        advertise_ip: str = "127.0.0.1",
        tone_hz: float = 1000.0,
        compression_type: int = DEFAULT_SKINNY_COMPRESSION,
        loopback_delay_ms: float = 1500.0,
        loopback_gain_db: float = 12.0,
        loopback_preamble_sec: float = 2.0,
    ):
        self.mode = mode if mode in self.VALID_MODES else "off"
        self.advertise_ip = advertise_ip
        self.tone_hz = tone_hz
        self.compression_type = compression_type
        self.loopback_delay_ms = loopback_delay_ms
        self.loopback_gain_db = loopback_gain_db
        self.loopback_preamble_sec = loopback_preamble_sec
        self._sessions: dict[int, SimMediaSession] = {}

    def set_advertise_ip(self, ip: str) -> None:
        if ip:
            self.advertise_ip = ip

    def start_call(self, call: SimCall) -> bool:
        """Return True if this hub handled StartMedia (caller should skip P2P)."""
        if self.mode == "off":
            return False

        parties: list[SkinnySession] = [call.caller]
        if call.callee:
            parties.append(call.callee)

        if len(parties) < 1:
            return False

        for p in parties:
            if id(p) not in call.media_ports:
                logger.warning("SimMediaHub: missing media port for %s", p.device_name)
                return False

        pt, spec, _ = resolve_rtp_payload_type(self.compression_type)
        if not spec.encode_supported:
            logger.warning("SimMediaHub: codec %s not supported; using PT 0", spec.name)
            pt = 0

        sim_session = SimMediaSession(call_ref=call.call_ref)
        sim_ip_int = _ip_to_le_int(self.advertise_ip)

        for party in parties:
            rx = RTPReceiver(worker=None, bind_ip="0.0.0.0", port=0, log=logger)
            rx.start()
            phone_port = call.media_ports[id(party)]
            phone_ip = party.station_ip

            tx = RTPSender(
                phone_ip,
                phone_port,
                ptime_ms=20,
                payload_type=pt,
                log=logger,
            )
            tx.start()

            leg = _PartyLeg(session=party, phone_port=phone_port, rx=rx, tx=tx)
            sim_session.legs.append(leg)

            party.send(
                payloads.start_media_transmission(
                    call.call_ref,
                    sim_ip_int,
                    rx.port,
                    precedence_value=0,
                )
            )

            if call.ivr:
                self._start_ivr_tx(call, leg, tx, rx)
            elif self.mode == "tone":
                tx.send_tone(self.tone_hz)
            elif self.mode == "loopback":
                echo = EchoSource(
                    8000,
                    delay_ms=self.loopback_delay_ms,
                    gain_db=self.loopback_gain_db,
                )
                leg.echo = echo
                if self.loopback_preamble_sec > 0:
                    tx.send_tone_then_echo(
                        echo,
                        tone_hz=self.tone_hz,
                        preamble_sec=self.loopback_preamble_sec,
                        tone_gain_db=-6.0,
                    )

                    def _arm_rx(
                        rx=rx,
                        echo=echo,
                        ref=call.call_ref,
                        delay=self.loopback_preamble_sec,
                    ) -> None:
                        time.sleep(delay)
                        try:
                            rx.attach_echo(echo)
                            logger.info(
                                "SimMediaHub loopback RX armed ref=%s (after %.1fs tone)",
                                ref,
                                delay,
                            )
                        except Exception:
                            logger.exception(
                                "SimMediaHub loopback RX arm failed ref=%s",
                                ref,
                            )

                    threading.Thread(
                        target=_arm_rx,
                        name=f"sim-rx-{call.call_ref}",
                        daemon=True,
                    ).start()
                else:
                    rx.attach_echo(echo)
                    tx.send_echo(echo)
            # bridge wiring happens after all legs exist

        if self.mode == "bridge" and len(sim_session.legs) == 2:
            a, b = sim_session.legs
            a_to_b = EchoSource(8000)
            b_to_a = EchoSource(8000)
            a.rx.attach_echo(a_to_b)
            b.rx.attach_echo(b_to_a)
            a.tx.send_echo(b_to_a)
            b.tx.send_echo(a_to_b)
            a.echo = a_to_b
            b.echo = b_to_a

        self._sessions[call.call_ref] = sim_session
        logger.info(
            "SimMediaHub %s active ref=%s advertise=%s legs=%s",
            self.mode,
            call.call_ref,
            self.advertise_ip,
            [(leg.session.device_name, leg.rx.port, leg.phone_port) for leg in sim_session.legs],
        )
        return True

    def start_conference(self, call: SimCall) -> bool:
        """Three-party conference bridge (requires bridge or loopback mode)."""
        if self.mode not in ("bridge", "loopback", "tone"):
            return False
        parties = [p for p in (call.caller, call.callee, call.third_party) if p]
        if len(parties) < 3:
            return False
        for party in parties:
            if id(party) not in call.media_ports:
                return False

        pt, spec, _ = resolve_rtp_payload_type(self.compression_type)
        if not spec.encode_supported:
            pt = 0

        sim_session = SimMediaSession(call_ref=call.call_ref)
        sim_ip_int = _ip_to_le_int(self.advertise_ip)

        for party in parties:
            rx = RTPReceiver(worker=None, bind_ip="0.0.0.0", port=0, log=logger)
            rx.start()
            phone_port = call.media_ports[id(party)]
            tx = RTPSender(
                party.station_ip,
                phone_port,
                ptime_ms=20,
                payload_type=pt,
                log=logger,
            )
            tx.start()
            sim_session.legs.append(
                _PartyLeg(session=party, phone_port=phone_port, rx=rx, tx=tx)
            )
            party.send(
                payloads.start_media_transmission(
                    call.call_ref,
                    sim_ip_int,
                    rx.port,
                    precedence_value=0,
                )
            )
            if self.mode == "tone":
                tx.send_tone(self.tone_hz)

        if self.mode == "bridge" and len(sim_session.legs) == 3:
            for i, leg_i in enumerate(sim_session.legs):
                for j, leg_j in enumerate(sim_session.legs):
                    if i == j:
                        continue
                    echo = EchoSource(8000)
                    leg_i.rx.attach_echo(echo)
                    leg_j.tx.send_echo(echo)

        self._sessions[call.call_ref] = sim_session
        logger.info(
            "SimMediaHub conference ref=%s legs=%s",
            call.call_ref,
            [leg.session.device_name for leg in sim_session.legs],
        )
        return True

    def _start_ivr_tx(self, call: SimCall, leg: _PartyLeg, tx: RTPSender, rx: RTPReceiver) -> None:
        """IVR calls: silence until macro PLAY; menu script drives RTP."""
        tx.send_silence()
        logger.debug("SimMediaHub IVR ref=%s TX idle (macro controls PLAY)", call.call_ref)

    def set_loopback(self, call_ref: int) -> bool:
        sim_session = self._sessions.get(call_ref)
        if not sim_session:
            return False
        for leg in sim_session.legs:
            leg.rx.detach_echo()
            echo = leg.echo or EchoSource(
                8000,
                delay_ms=self.loopback_delay_ms,
                gain_db=self.loopback_gain_db,
            )
            leg.echo = echo
            leg.rx.attach_echo(echo)
            if leg.tx:
                leg.tx.send_echo(echo)
        logger.info("SimMediaHub loopback active ref=%s (IVR menu)", call_ref)
        return True

    def set_tone(self, call_ref: int) -> bool:
        sim_session = self._sessions.get(call_ref)
        if not sim_session:
            return False
        for leg in sim_session.legs:
            leg.rx.detach_echo()
            if leg.tx:
                leg.tx.send_tone(self.tone_hz)
        logger.info("SimMediaHub tone active ref=%s (IVR menu)", call_ref)
        return True

    def play_wav(self, call_ref: int, path: str, *, gain_db: float = -3.0) -> bool:
        sim_session = self._sessions.get(call_ref)
        if not sim_session:
            return False
        for leg in sim_session.legs:
            if leg.tx:
                leg.tx.send_wav(path, loop=False, gain_db=gain_db)
        return True

    def stop_playback(self, call_ref: int) -> bool:
        """Cut off prompt/tone RTP immediately (IVR barge-in)."""
        sim_session = self._sessions.get(call_ref)
        if not sim_session:
            return False
        for leg in sim_session.legs:
            if leg.tx:
                leg.tx.send_silence()
        return True

    def stop_call(self, call_ref: int) -> None:
        sim_session = self._sessions.pop(call_ref, None)
        if not sim_session:
            return
        for leg in sim_session.legs:
            leg.rx.detach_echo()
            leg.rx.stop()
            if leg.tx:
                leg.tx.stop()
        logger.info("SimMediaHub stopped ref=%s", call_ref)

    def stop_all(self) -> None:
        for ref in list(self._sessions):
            self.stop_call(ref)
