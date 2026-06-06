import struct
import time
from dispatcher import register_handler
from messages.generic import STIMULUS_NAMES, TONE_NAMES, TONE_OUTPUT_DIRECTION_NAMES, CALL_TYPE_NAMES, CALL_STAT_STATE_NAMES, clean_bytes, send_skinny_message, Buf
from utils.call_management import (
    CALL_STATE_NAMES,
    apply_call_state_from_skinny,
    apply_line_lamp_state,
    infer_resumed_on_media_start,
    mark_call_ended,
    mark_call_connected,
    mark_call_ringing,
    next_synthetic_call_reference,
    resolve_active_call_key,
    update_call_state,
)
from utils.client import get_local_ip, ip_to_int, _keypad_code_to_char
from audio_worker import RTPReceiver, RTPSender, wire_rtp_loopback, socket
from utils.rtp_record import RTPRecorder, rtp_record_base_path
from utils.media_codecs import codec_label, lookup_skinny_compression, resolve_rtp_payload_type
from utils.rtp_stats import RTPStats, RTPStatsMonitor
import logging
logger = logging.getLogger(__name__)


def _truthy(val) -> bool:
    return str(val).lower() in ("1", "true", "yes", "on")


def _rtp_pt_override(client) -> int | None:
    kv = client.state.kv_dict.get("rtp_pt")
    if kv is not None:
        try:
            return int(kv)
        except (TypeError, ValueError):
            pass
    override = getattr(client.state, "rtp_pt_override", None)
    return int(override) if override is not None else None


def _resolve_tx_payload_type(client, compression_type: int) -> tuple[int, bool]:
    pt, spec, used_fallback = resolve_rtp_payload_type(
        compression_type,
        override_pt=_rtp_pt_override(client),
    )
    if _rtp_pt_override(client) is not None:
        return pt, False
    if lookup_skinny_compression(compression_type) is not None:
        if not spec.encode_supported:
            logger.debug(
                "Skinny compression_type=%s (%s): TX silence (RX uses RTP PT from wire)",
                compression_type,
                spec.name,
            )
        return pt, spec.encode_supported
    logger.warning(
        "Skinny compression_type=%s (%s) unregistered -> RTP PT=%s%s",
        compression_type,
        codec_label(compression_type),
        pt,
        " (fallback)" if used_fallback else "",
    )
    return pt, False


def _rtp_loopback_enabled(client) -> bool:
    kv = client.state.kv_dict.get("rtp_loopback")
    if kv is not None:
        return _truthy(kv)
    return bool(getattr(client.state, "rtp_loopback", False))


def _rtp_loopback_monitor(client) -> bool:
    kv = client.state.kv_dict.get("rtp_loopback_monitor")
    if kv is not None:
        return _truthy(kv)
    return bool(getattr(client.state, "rtp_loopback_monitor", False))


def _rtp_record_enabled(client) -> bool:
    kv = client.state.kv_dict.get("rtp_record")
    if kv is not None:
        return _truthy(kv)
    return bool(getattr(client.state, "rtp_record", False))


def _rtp_tone_hz(client) -> float:
    kv = client.state.kv_dict.get("rtp_tone_hz")
    if kv is not None:
        try:
            return float(kv)
        except (TypeError, ValueError):
            pass
    return float(getattr(client.state, "rtp_tone_hz", 1000.0))


def _effective_play_mode(client) -> str:
    kv = client.state.kv_dict.get("audio_play_mode")
    if kv is not None:
        return str(kv)
    if getattr(client.state, "rtp_tone", False):
        return "tone"
    return "silent"


def _start_rtp_recorder(client, call_ref: int) -> RTPRecorder | None:
    if not _rtp_record_enabled(client):
        return None
    existing = getattr(client.state, "_rtp_recorder", None)
    if existing is not None and not existing.closed:
        return existing
    base = rtp_record_base_path(client.state, call_ref)
    rec = RTPRecorder(base, sr=8000, log=client.logger)
    client.state._rtp_recorder = rec
    client.logger.info("[RTP record] started base=%s", base)
    return rec


def _stop_rtp_recorder(client) -> None:
    rec = getattr(client.state, "_rtp_recorder", None)
    if rec is None:
        return
    rec.close()
    client.state._rtp_recorder = None


def _attach_recorder_to_media(client, call_ref: int) -> None:
    rec = _start_rtp_recorder(client, call_ref)
    if rec is None:
        return
    rx = client.state._rtp_rx
    tx = client.state._rtp_tx
    if rx is not None:
        rx.attach_recorder(rec)
    if tx is not None:
        tx.attach_recorder(rec)


def _rtp_stats_enabled(client) -> bool:
    kv = client.state.kv_dict.get("rtp_stats")
    if kv is not None:
        return _truthy(kv)
    return bool(getattr(client.state, "rtp_stats", False))


def _ensure_rtp_stats(client) -> RTPStats | None:
    if not _rtp_stats_enabled(client):
        return None
    stats = getattr(client.state, "_rtp_stats", None)
    if stats is None:
        stats = RTPStats()
        client.state._rtp_stats = stats
    return stats


def _attach_stats_to_media(client) -> None:
    stats = _ensure_rtp_stats(client)
    if stats is None:
        return
    rx = client.state._rtp_rx
    tx = client.state._rtp_tx
    if rx is not None:
        rx.attach_stats(stats)
    if tx is not None:
        tx.attach_stats(stats)


def _start_rtp_stats_monitor(client) -> None:
    stats = getattr(client.state, "_rtp_stats", None)
    if stats is None:
        return
    interval = float(getattr(client.state, "rtp_stats_interval", 0.0) or 0.0)
    if interval <= 0:
        return
    mon = getattr(client.state, "_rtp_stats_monitor", None)
    if mon is not None:
        return
    mon = RTPStatsMonitor(stats, client.logger, interval=interval)
    mon.start()
    client.state._rtp_stats_monitor = mon


def _stop_rtp_stats_monitor(client, *, final_log: bool = True) -> None:
    mon = getattr(client.state, "_rtp_stats_monitor", None)
    if mon is not None:
        mon.stop()
        client.state._rtp_stats_monitor = None
    stats = getattr(client.state, "_rtp_stats", None)
    if final_log and stats is not None and _rtp_stats_enabled(client):
        client.logger.info("[RTP stats] %s", stats.summary())
    client.state._rtp_stats = None


def _teardown_local_media(client) -> None:
    """Stop client RTP legs when the call ends without explicit StopMedia."""
    tx = getattr(client.state, "_rtp_tx", None)
    if tx is not None:
        tx.stop()
        client.state._rtp_tx = None
    rx = getattr(client.state, "_rtp_rx", None)
    if rx is not None:
        rx.detach_echo()
        rx.stop()
        client.state._rtp_rx = None
    client.state._rtp_echo_source = None
    _stop_rtp_recorder(client)
    _stop_rtp_stats_monitor(client)
    client.state.media_active = False
    client.events.media_started.clear()


def _rtp_play_worker(client):
    if not client.state.enable_audio:
        return None
    if _rtp_loopback_enabled(client) and not _rtp_loopback_monitor(client):
        return None
    return client.audio


def _configure_rtp_sender(client, tx: RTPSender) -> None:
    if _rtp_loopback_enabled(client):
        rx = client.state._rtp_rx
        if rx is None:
            logger.warning("rtp_loopback enabled but OpenReceiveChannel/RTP RX not ready yet")
            tx.send_silence()
            return
        client.state._rtp_echo_source = wire_rtp_loopback(rx, tx, sr=tx.sr)
        logger.info("[RTP] loopback echo enabled -> %s:%s", tx.addr[0], tx.addr[1])
        return

    play_mode = _effective_play_mode(client)
    if play_mode in ["silent", "silence"]:
        logger.debug("RTP Sending mode: Silence")
        tx.send_silence()
    elif play_mode in ["mic", "microphone"]:
        logger.debug("RTP Sending mode: Microphone")
        tx.send_microphone()
    elif play_mode in ["tone", "test-tone", "testtone"]:
        hz = _rtp_tone_hz(client)
        logger.info("RTP Sending mode: test tone %.0f Hz", hz)
        tx.send_tone(hz)
    else:
        logger.debug("RTP Sending mode: File %s", play_mode)
        tx.send_wav(play_mode, loop=True)


@register_handler(0x0085, "SetRinger")
def parse_set_ringer(client, payload):
    buf = Buf(payload)
    ring_mode = buf.read_u32()
    ring_duration = buf.read_u32(0)                       # Missing in CallManager 3.1
    line_instance = buf.read_u32(0)                       # Missing in CallManager 3.1
    call_reference = buf.read_u32(0)                      # Missing in CallManager 3.1

    # ring_mode, ring_duration, line_instance, call_reference = struct.unpack("<IIII", payload)

    client.state.ring_mode = ring_mode
    client.state.ring_duration = ring_duration
    client.state.ring_line_instance = line_instance
    client.state.ring_call_reference = call_reference

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # logger.info(f"[RECV] SetRinger ringMode: {ring_mode}, ringDuration: {ring_duration}, lineInstance: {line_instance}, callReference: {call_reference}")
    logger.info(f"[RECV] SetRinger")

    if ring_mode:
        ref = call_reference or getattr(client.state, "selected_call_reference", None)
        if not ref and client.state.active_calls_list:
            ref = client.state.active_calls_list[-1]
        if ref:
            existing = client.state.calls.get(str(ref), {})
            # CM often sends SetRinger while connected (e.g. stop ring); do not regress state.
            if existing.get("call_state") in (5, 8):
                return
            mark_call_ringing(
                client,
                ref,
                line_instance or 1,
                source="SetRinger",
            )


@register_handler(0x0088, "SetSpeakerMode")
def parse_set_speaker_mode(client, payload):
    speaker_mode = struct.unpack("<I", payload)[0]

    client.state.speaker_mode = speaker_mode
    # logging.info(f"[RECV] SetSpeakerMode speakerMode: {speaker_mode}")
    logger.info(f"[RECV] SetSpeakerMode")


@register_handler(0x0086, "SetLamp")
def parse_set_lamp(client, payload):
    stimulus, stimulus_instance, lamp_mode = struct.unpack("<III", payload)
    stimulus_name = STIMULUS_NAMES.get(stimulus, "UNKNOWN")

    client.state.stimulus = stimulus
    client.state.stimulus_name = stimulus_name
    client.state.stimulus_instance = stimulus_instance
    client.state.lamp_mode = lamp_mode
    if not hasattr(client.state, "line_lamps") or client.state.line_lamps is None:
        client.state.line_lamps = {}
    if stimulus == 9:
        client.state.line_lamps[str(stimulus_instance)] = lamp_mode
        apply_line_lamp_state(client, stimulus_instance, lamp_mode, source="SetLamp")

    # logging.info(f"[RECV] SetLamp stimulus: {stimulus_name} ({stimulus}), stimulusInstance: {stimulus_instance}, lampMode: {lamp_mode}")
    logger.info(f"[RECV] SetLamp")


@register_handler(0x0111, "CallState")
def parse_call_state(client, payload):
    buf = Buf(payload)

    call_state = buf.read_u32()
    line_instance = buf.read_u32()
    call_reference = buf.read_u32()
    privacy = buf.read_u32(0) if buf.remaining() >= 4 else 0
    precedence_level = buf.read_u32(0) if buf.remaining() >= 4 else 0
    precedence_domain = buf.read_u32(0) if buf.remaining() >= 4 else 0

    key = apply_call_state_from_skinny(
        client,
        call_state,
        call_reference,
        line_instance,
        source="CallState",
    )

    call = client.state.calls.get(key)
    if call:
        call["privacy"] = privacy
        call["precedence_level"] = precedence_level
        call["precedence_domain"] = precedence_domain

    if call_state in (0, 2) and not client.state.active_calls_list:
        _teardown_local_media(client)

    logger.info(
        f"[RECV] CallState "
        f"state={CALL_STATE_NAMES.get(call_state, 'UNKNOWN')} "
        f"line={line_instance} ref={call_reference}"
    )


@register_handler(0x0116, "ActivateCallPlane")
def parse_activate_callplane(client, payload):
    line_instance = struct.unpack("<I", payload)[0]

    client.state.active_call = True
    client.state.active_call_line_instance = line_instance

    # logger.info(f"[RECV] ActivateCallPlane lineInstance: {line_instance}")
    logger.info(f"[RECV] ActivateCallPlane")


def end_local_call(client, source: str = "local", *, call_ref: int | None = None) -> None:
    """Stop local RTP/tone immediately; update call state without waiting for CM."""
    _teardown_local_media(client)
    if client.state.enable_audio:
        client.audio.clear_tone(1)
    if call_ref is None:
        _, call_ref = client.resolve_call_target(softkey_name="EndCall")
    mark_call_ended(client, call_ref if call_ref else None, source=source)


@register_handler(0x0082, "StartTone")
def parse_start_tone(client, payload):
    buf = Buf(payload)
    tone = buf.read_u32()
    tone_output_direction = buf.read_u32(0)                      # Missing in CallManager 3.1
    line_instance = buf.read_u32(0)                              # Missing in CallManager 3.1
    call_reference = buf.read_u32(0)                             # Missing in CallManager 3.1

    # tone, tone_output_direction, line_instance, call_reference = struct.unpack("<IIII", payload)
    tone_name = TONE_NAMES.get(tone, "UNKNOWN")
    tone_output_direction_name = TONE_OUTPUT_DIRECTION_NAMES.get(tone_output_direction, "UNKNOWN")

    client.state.play_tones = {"tone": tone, "tone_name": tone_name, "tone_output_direction": tone_output_direction, "tone_output_direction_name": tone_output_direction_name, "call_reference": call_reference, "line_instance": line_instance}
    if client.state.enable_audio:
        client.audio.set_tone(line_instance, tone, gain_db=client.state.tone_volume)

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # logger.info(f"[RECV] StartTone tone: {tone_name} ({tone}), toneOutputDirection: {tone_output_direction_name} ({tone_output_direction}), lineInstance: {line_instance}, callReference: {call_reference}")
    logger.info(f"[RECV] StartTone")


@register_handler(0x0083, "StopTone")
def parse_stop_tone(client, payload):
    buf = Buf(payload)
    line_instance = buf.read_u32(0)                       # Missing in CallManager 3.1
    call_reference = buf.read_u32(0)                      # Missing in CallManager 3.1

    # line_instance, call_reference = struct.unpack("<II", payload)

    client.state.play_tones = {}
    client.audio.clear_tone(line_instance)

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log, override_message_name="StartTone")

    # logger.info(f"[RECV] StopTone lineInstance: {line_instance}, callReference: {call_reference}")
    logger.info(f"[RECV] StopTone")


@register_handler(0x008F, "CallInfo")
def parse_call_info(client, payload):
    buf = Buf(payload)

    calling_party_name = buf.read_cstring(40, "")
    calling_party = buf.read_cstring(24, "")
    called_party_name = buf.read_cstring(40, "")
    called_party = buf.read_cstring(24, "")

    line_instance = 0
    call_reference = 0
    call_type = 0

    original_called_party_name = ""
    original_called_party = ""
    last_redirecting_party_name = ""
    last_redirecting_party = ""
    original_cpdn_redirect_reason = 0
    last_redirecting_reason = 0
    cgpn_voicemail_box = ""
    cdpn_voicemail_box = ""
    original_cdpn_voicemail_box = ""
    last_redirecting_voicemail_box = ""
    call_instance = 0
    call_security_status = 0
    party_pi_restriction_bits = 0

    # CM 3.x/4.x+ extended CallInfo fields.
    if buf.remaining() >= 12:
        line_instance = buf.read_u32()
        call_reference = buf.read_u32()
        call_type = buf.read_u32()

    if buf.remaining() >= 40:
        original_called_party_name = buf.read_cstring(40, "")

    if buf.remaining() >= 24:
        original_called_party = buf.read_cstring(24, "")

    if buf.remaining() >= 40:
        last_redirecting_party_name = buf.read_cstring(40, "")

    if buf.remaining() >= 24:
        last_redirecting_party = buf.read_cstring(24, "")

    if buf.remaining() >= 8:
        original_cpdn_redirect_reason = buf.read_u32()
        last_redirecting_reason = buf.read_u32()

    if buf.remaining() >= 24:
        cgpn_voicemail_box = buf.read_cstring(24, "")

    if buf.remaining() >= 24:
        cdpn_voicemail_box = buf.read_cstring(24, "")

    if buf.remaining() >= 24:
        original_cdpn_voicemail_box = buf.read_cstring(24, "")

    if buf.remaining() >= 24:
        last_redirecting_voicemail_box = buf.read_cstring(24, "")

    if buf.remaining() >= 12:
        call_instance = buf.read_u32()
        call_security_status = buf.read_u32()
        party_pi_restriction_bits = buf.read_u32()

    call_type_name = CALL_TYPE_NAMES.get(call_type, "UNKNOWN")
    binary_flags = format(party_pi_restriction_bits, "032b")

    # CM2 CallInfo has no call_reference field, so use selected/active ref if available.
    if not call_reference:
        active_refs = list(client.state.active_calls_list or [])

        if active_refs:
            call_reference = active_refs[-1]
        else:
            call_reference = next_synthetic_call_reference(client)

    key = str(call_reference)

    client.state.callinfo[key] = {
        "calling_party_name": calling_party_name,
        "calling_party": calling_party,
        "called_party_name": called_party_name,
        "called_party": called_party,
        "line_instance": line_instance,
        "call_reference": call_reference,
        "call_type": call_type,
        "call_type_name": call_type_name,
        "original_called_party_name": original_called_party_name,
        "original_called_party": original_called_party,
        "last_redirecting_party_name": last_redirecting_party_name,
        "last_redirecting_party": last_redirecting_party,
        "original_cpdn_redirect_reason": original_cpdn_redirect_reason,
        "last_redirecting_reason": last_redirecting_reason,
        "cgpn_voice_mail_box": cgpn_voicemail_box,
        "cdpn_voice_mail_box": cdpn_voicemail_box,
        "original_cdpn_voice_mail_box": original_cdpn_voicemail_box,
        "last_redirecting_voice_mail_box": last_redirecting_voicemail_box,
        "call_instance": call_instance,
        "call_security_status": call_security_status,
        "party_pi_restriction_bits": binary_flags,
    }

    if key not in client.state.calls_list:
        client.state.calls_list.append(key)

    remote_name = calling_party_name or called_party_name
    remote_number = calling_party or called_party

    existing = client.state.calls.get(key, {})
    existing_state = existing.get("call_state")
    if existing_state in (5, 8):
        call_state = existing_state
        call_state_name = existing.get("call_state_name") or CALL_STATE_NAMES.get(call_state, "UNKNOWN")
    elif call_type == 1:
        call_state, call_state_name = 4, "RingIn"
    elif call_type == 2:
        call_state, call_state_name = 3, "RingOut"
    else:
        # CM2 CallInfo omits callType; infer direction from local directory numbers.
        local_dns = {
            (row.get("line_dir_number") or "").strip()
            for row in client.state.lines.values()
        }
        cp = (calling_party or "").strip()
        cdp = (called_party or "").strip()
        if cdp in local_dns:
            call_state, call_state_name = 4, "RingIn"
        elif cp in local_dns:
            call_state, call_state_name = 3, "RingOut"
        else:
            call_state, call_state_name = 3, "CallInfo"

    key = update_call_state(
        client,
        call_reference=call_reference,
        line_instance=line_instance or 1,
        call_state=call_state,
        call_state_name=call_state_name,
        source="CallInfo",
        calling_party_name=calling_party_name,
        calling_party=calling_party,
        called_party_name=called_party_name,
        called_party=called_party,
        remote_name=remote_name,
        remote_number=remote_number,
    )

    if key not in client.state.active_calls_list:
        client.state.active_calls_list.append(key)

    client.state.active_call = True
    client.state.call_active = True
    client.events.call_ended.clear()

    if call_state == 4:
        mark_call_ringing(
            client,
            call_reference,
            line_instance or 1,
            call_state=4,
            source="CallInfo",
        )
    elif call_state == 3 and call_state_name == "RingOut":
        client.state.selected_call_reference = key

    # # Track call lifecycle
    # call_state_name = "RingIn"
    # handle_call_state(line_instance, call_reference, call_state_name, shared_state)
    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # logger.info(f"[RECV] CallInfo callingPartyName: {calling_party_name}, callingParty: {calling_party}, calledPartyName: {called_party_name}, calledParty: {called_party}, lineInstance: {line_instance}, callReference: {call_reference}, callType: {call_type_name} ({call_type}), originalCalledPartyName: {original_called_party_name}, originalCalledParty: {original_called_party}, lastRedirectingPartyName: {last_redirecting_party_name}, lastRedirectingParty: {last_redirecting_party}, originalCpdnRedirectReason: {original_cpdn_redirect_reason}, lastRedirectingReason: {last_redirecting_reason}, cgpnVoiceMailBox: {cgpn_voicemail_box}, cpdnVoiceMailBox: {cdpn_voicemail_box}, originalCdpnVoiceMailBox: {original_cdpn_voicemail_box}, lastRedirectingVoiceMailBox: {last_redirecting_voicemail_box}, callInstance: {call_instance}, callSecurityStatus: {call_security_status}, partyPIRestrictionBits: {binary_flags}")

    logger.info(
        f"[RECV] CallInfo "
        f"from={calling_party_name!r} <{calling_party}> "
        f"to={called_party_name!r} <{called_party}> "
        f"ref={call_reference}"
    )


@register_handler(0x011D, "DialedNumber")
def parse_dialed_number(client, payload):
    dialed_number_bytes = payload[:24]                                                       # 24 bytes
    line_instance, call_reference = struct.unpack("<II", payload[24:])

    dialed_number = dialed_number_bytes.decode("ascii", errors="ignore").rstrip('\x00')

    client.state.dialed_number = {"line_instance": line_instance, "dialed_number": dialed_number, "call_reference": call_reference}

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # logger.info(f"[RECV] DialedNumber dialedNumber: {dialed_number}, lineInstance: {line_instance}, callReference: {call_reference}")
    logger.info(f"[RECV] DialedNumber")


@register_handler(0x008A, "StartMediaTransmission")
def parse_start_media_transmission(client, payload):
    buf = Buf(payload)

    conference_id = buf.read_u32(0)
    pass_through_party_id = buf.read_u32(0)
    remote_ip_addr = buf.read_u32(0)
    remote_port_number = buf.read_u32(0)
    milli_second_packet_size = buf.read_u32(20)
    compression_type = buf.read_u32(0)
    precedence_value = buf.read_u32(0)
    ss_value = buf.read_u32(0)
    max_frames_per_packet = buf.read_u16(0)
    padding = buf.read_u16(0)

    # Present in later CM versions, missing in CM 2.01.
    g723_bitrate = buf.read_u32(0) if buf.remaining() >= 4 else 0
    call_reference = buf.read_u32(0) if buf.remaining() >= 4 else 0
    algorithm_id = buf.read_u32(0) if buf.remaining() >= 4 else 0
    key_len = buf.read_u16(0) if buf.remaining() >= 2 else 0
    salt_len = buf.read_u16(0) if buf.remaining() >= 2 else 0

    key_bytes = buf.read_bytes(16) if buf.remaining() >= 16 else b""
    salt_bytes = buf.read_bytes(16) if buf.remaining() >= 16 else b""

    key = clean_bytes(key_bytes)
    salt = clean_bytes(salt_bytes)
    # logger.info(f"[RECV] StartMediaTransmission conferenceId: {conference_id}, passThroughPartyId: {pass_through_party_id}, remoteIpAddr: {remote_ip_addr}, remotePortNumber: {remote_port_number}, milliSecondPacketSize: {milli_second_packet_size}, compressionType: {compression_type}, precedenceValue: {precedence_value}, ssValue: {ss_value}, maxFramesPerPacket: {max_frames_per_packet}, padding: {padding}, g723Bitrate: {g723_bitrate}, callReference: {call_reference}, algorithmId: {algorithm_id}, keyLen: {key_len}, saltLen: {salt_len}, key: {key}, salt: {salt}")

    key, call = resolve_active_call_key(client, call_reference)
    if key:
        call_reference = call.get("call_reference") or key
    elif not call_reference:
        call_reference = (
            getattr(client.state, "selected_call_reference", None)
            or getattr(client.state, "active_call_reference", None)
            or (client.state.active_calls_list[-1] if client.state.active_calls_list else 0)
        )

    client.state.media_active = True
    client.events.media_started.set()

    if call_reference:
        line_inst = int(call.get("line_instance") or getattr(client.state, "active_call_line_instance", None) or 1)
        infer_resumed_on_media_start(
            client,
            call_reference=call_reference,
            source="StartMediaTransmission",
        )
        mark_call_connected(
            client,
            call_reference=call_reference,
            line_instance=line_inst,
            source="StartMediaTransmission",
        )

    client.state.start_media_transmission[str(call_reference)] = {
        "conferenceId": conference_id,
        "passThroughPartyId": pass_through_party_id,
        "remoteIpAddr": remote_ip_addr,
        "remotePortNumber": remote_port_number,
        "milliSecondPacketSize": milli_second_packet_size,
        "compressionType": compression_type,
        "precedenceValue": precedence_value,
        "ssValue": ss_value,
        "maxFramesPerPacket": max_frames_per_packet,
        "padding": padding,
        "g723Bitrate": g723_bitrate,
        "callReference": call_reference,
        "algorithmId": algorithm_id,
        "keyLen": key_len,
        "saltLen": salt_len,
        "key": key,
        "salt": salt,
    }

    # # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=None, log=log, override_message_data=trace_data)

    # send_open_receive_channel_ack(sock, {"passThroughPartyId": pass_through_party_id, "callReference": call_reference}, shared_state=shared_state, log=log)

    # remote_ip = socket.inet_ntoa(struct.pack("!I", remote_ip_addr))
    # remote_ip = socket.inet_ntoa(struct.pack("<I", remote_ip_addr))
    # sender = RTPAudioSender(remote_ip, remote_port_number)
    # client.state["rtp_sender"] = sender
    # client.state["rtp_remote_ip"] = remote_ip
    # client.state["rtp_remote_port"] = remote_port_number
    # sender.start()

    remote_ip = socket.inet_ntoa(struct.pack("<I", remote_ip_addr))
    ptime = milli_second_packet_size or 20
    pt, tx_supported = _resolve_tx_payload_type(client, compression_type)

    tx = RTPSender(
        remote_ip,
        remote_port_number,
        ptime_ms=ptime,
        payload_type=pt,
        log=client.logger,
    )
    tx.start()
    if tx_supported:
        _configure_rtp_sender(client, tx)
    else:
        logger.warning("RTP TX left on silence (codec not supported for encoding)")

    client.state._rtp_tx = tx
    _attach_recorder_to_media(client, call_reference)
    _attach_stats_to_media(client)
    _start_rtp_stats_monitor(client)

    mark_call_connected(
        client,
        call_reference=call_reference,
        line_instance=getattr(client.state, "active_call_line_instance", 1) or 1,
        source="StartMediaTransmission",
    )

    logger.info(
        f"[RECV] StartMediaTransmission "
        f"remote={remote_ip}:{remote_port_number} "
        f"ptime={ptime} codec={compression_type} ({codec_label(compression_type)}) "
        f"rtp_pt={pt} call_ref={call_reference}"
    )


@register_handler(0x008B, "StopMediaTransmission")
def parse_stop_media_transmission(client, payload):
    buf = Buf(payload)

    conference_id = buf.read_u32(0)
    pass_through_party_id = buf.read_u32(0) if buf.remaining() >= 4 else 0
    call_reference = buf.read_u32(0) if buf.remaining() >= 4 else 0

    tx = client.state._rtp_tx or None
    if tx:
        tx.stop()
    client.state._rtp_tx = None
    rx = client.state._rtp_rx or None
    if rx:
        rx.detach_echo()
    client.state._rtp_echo_source = None
    _stop_rtp_recorder(client)
    _stop_rtp_stats_monitor(client)

    client.state.media_active = False
    client.events.media_started.clear()

    # sender = client.state.get("rtp_sender")
    # if sender:
    #     sender.stop()
    #     client.state["rtp_sender"] = None

    # trace_data = {
    #     "conferenceId": conference_id,
    #     "passThroughPartyId": pass_through_party_id,
    #     "callReference": call_reference,
    # }

    # # Track call lifecycle
    # call_state_name = "Hold"
    # handle_call_state(conference_id, call_reference, call_state_name, shared_state)
    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=None, log=log, override_message_data=trace_data)

    # logger.info(f"[RECV] StopMediaTransmission conferenceId: {conference_id}, passThroughPartyId: {pass_through_party_id}, callReference: {call_reference}")

    # mark_call_ended(
    #     client,
    #     call_reference=call_reference or None,
    #     source="StopMediaTransmission",
    # )

    logger.info(
        f"[RECV] StopMediaTransmission "
        f"conference_id={conference_id} "
        f"pass_through_party_id={pass_through_party_id} "
        f"call_reference={call_reference}"
    )


@register_handler(0x008C, "StartMediaReception")
def parse_start_media_reception(client, payload):    # Wireshark dissector doesn't name this message; making an assumption here
    buf = Buf(payload)

    conference_id = buf.read_u32(0)
    pass_through_party_id = buf.read_u32(0) if buf.remaining() >= 4 else 0
    call_reference = buf.read_u32(0) if buf.remaining() >= 4 else 0

    infer_resumed_on_media_start(
        client,
        call_reference=call_reference or pass_through_party_id,
        source="StartMediaReception",
    )

    logger.info(
        f"[RECV] StartMediaReception "
        f"conference_id={conference_id} "
        f"pass_through_party_id={pass_through_party_id} "
        f"call_reference={call_reference}"
    )


@register_handler(0x008D, "StopMediaReception")
def parse_stop_media_reception(client, payload):    # Wireshark dissector doesn't name this message; making an assumption here
    buf = Buf(payload)

    conference_id = buf.read_u32(0)
    pass_through_party_id = buf.read_u32(0) if buf.remaining() >= 4 else 0
    call_reference = buf.read_u32(0) if buf.remaining() >= 4 else 0

    client.state.media_active = False

    logger.info(
        f"[RECV] StopMediaReception "
        f"conference_id={conference_id} "
        f"pass_through_party_id={pass_through_party_id} "
        f"call_reference={call_reference}"
    )


@register_handler(0x0105, "OpenReceiveChannel")
def parse_open_receive_channel(client, payload):
    buf = Buf(payload)

    conference_id = buf.read_u32(0)
    pass_through_party_id = buf.read_u32(0)
    milli_second_packet_size = buf.read_u32(20)
    compression_type = buf.read_u32(0)
    ec_value = buf.read_u32(0)
    g723_bitrate = buf.read_u32(0)
    call_reference = buf.read_u32(0) if buf.remaining() >= 4 else 0
    algorithm_id = buf.read_u32(0) if buf.remaining() >= 4 else 0
    key_len = buf.read_u16(0) if buf.remaining() >= 2 else 0
    salt_len = buf.read_u16(0) if buf.remaining() >= 2 else 0

    key_bytes = buf.read_bytes(16) if buf.remaining() >= 16 else b""
    salt_bytes = buf.read_bytes(16) if buf.remaining() >= 16 else b""

    key = clean_bytes(key_bytes)
    salt = clean_bytes(salt_bytes)

    if not call_reference:
        from utils.call_management import skinny_wire_call_ref

        raw = (
            getattr(client.state, "selected_call_reference", None)
            or getattr(client.state, "active_call_reference", None)
            or (client.state.active_calls_list[-1] if client.state.active_calls_list else 0)
        )
        call_reference = skinny_wire_call_ref(client, raw)
    if not call_reference:
        call_reference = int(pass_through_party_id or 0)

    logger.info(f"[RECV] OpenReceiveChannel")

    send_open_receive_channel_ack(
        client,
        {
            "passThroughPartyId": int(pass_through_party_id),
            "callReference": int(call_reference),
        },
    )


def send_open_receive_channel_ack(client, payload):
    media_reception_status = 0  # 0 = OK

    rx = RTPReceiver(
        worker=_rtp_play_worker(client),
        bind_ip="0.0.0.0",
        source_id="rx",
        log=client.logger,
    )
    rx.start()
    client.state._rtp_rx = rx
    port_number = rx.port

    call_reference = int(payload["callReference"] or 0)
    rec = _start_rtp_recorder(client, call_reference)
    if rec is not None:
        rx.attach_recorder(rec)
    stats = _ensure_rtp_stats(client)
    if stats is not None:
        rx.attach_stats(stats)

    call_manager_host_ip = get_local_ip(client.state.server)
    station_ip = ip_to_int(call_manager_host_ip)  # still in int form
    pass_through_party_id = int(payload["passThroughPartyId"] or 0)
    station_ip_packed = struct.pack("!I", station_ip)  # Big-endian (network byte order)

    data = struct.pack(
        "<I",
        media_reception_status
    )
    data += station_ip_packed
    data += struct.pack(
        "<III",
        port_number,
        pass_through_party_id,
        call_reference
    )

    # Call Trace Logging
    # trace_data = {
    #     "mediaReceptionStatus": media_reception_status,
    #     "callManagerHostIp": call_manager_host_ip,
    #     "portNumber": port_number,
    #     "passThroughPartyId": pass_through_party_id,
    #     "callReference": call_reference,
    # }
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=None, log=log, override_message_data=trace_data)

    logger.info(f"[SEND] OpenReceiveChannelAck -> IP: {call_manager_host_ip}, Port: {port_number}, CallRef: {call_reference}")
    send_skinny_message(client, 0x0022, trailing_data=data, silent=True)


@register_handler(0x0106, "CloseReceiveChannel")
def parse_close_receive_channel(client, payload):
    buf = Buf(payload)
    conference_id = buf.read_u32(0)
    pass_through_party_id = buf.read_u32(0) if buf.remaining() >= 4 else 0
    call_reference = buf.read_u32(0) if buf.remaining() >= 4 else 0

    # Close/clear RTP Receiver
    rx = client.state._rtp_rx or None
    if rx:
        rx.stop()
    client.state._rtp_rx = None
    client.state._rtp_echo_source = None
    _stop_rtp_recorder(client)
    _stop_rtp_stats_monitor(client)

    logger.info(f"[RECV] CloseReceiveChannel")


@register_handler(0x0120, "DisplayPriNotify")
def parse_display_pri_notify(client, payload):
    time_out_value, priority = struct.unpack("<II", payload[:8])
    notify_bytes = payload[8:40]                                                                                         # 32 bytes
    notify = clean_bytes(notify_bytes)

    # logger.info(f"[RECV] DisplayPriNotify timeOutValue: {time_out_value}, priority: {priority}, notify: {notify}")
    logger.info(f"[RECV] DisplayPriNotify")


@register_handler(0x0003, "KeypadButton")
def parse_keypad_button(client, payload):
    kp_button, line_instance, call_reference = struct.unpack("<III", payload[:12])

    logger.info(f"[RECV] KeypadButton {kp_button}")

    ch = _keypad_code_to_char(kp_button)
    if ch:
        client._on_digit(ch)


@register_handler(0x0130, "CallSelectStatRes")
def parse_call_select_stat_res(client, payload):
    call_select_stat, call_reference, line_instance = struct.unpack("<III", payload)
    call_state_name = CALL_STAT_STATE_NAMES.get(call_select_stat, "UNKNOWN")

    # # Track call lifecycle
    # handle_call_state(line_instance, call_reference, call_state_name, shared_state)
    #
    # trace_data = {
    #     "callSelectStat": call_select_stat,
    #     "callReference": call_reference,
    #     "lineInstance": line_instance,
    # }
    #
    # # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log, override_message_data=trace_data)

    # logger.info(f"[RECV] CallSelectStatRes callSelectStat: {call_state_name} ({call_select_stat}), callReference: {call_reference}, lineInstance: {line_instance}")
    logger.info(f"[RECV] CallSelectStatRes")


@register_handler(0x0114, "DisplayNotify")
def parse_display_notify(client, payload):
    time_out_value = struct.unpack("<I", payload[0:4])[0]
    notify = clean_bytes(payload[4:36])

    client.state.update_prompt(notify, time_out_value)
    client.state.display_notify = {
        "timeOutValue": time_out_value,
        "notify": notify,
        "received_at": time.time() if time_out_value > 0 else None,
    }

    logger.info(f"[PROMPT] '{notify}' Timeout: {time_out_value}")


@register_handler(0x0099, "DisplayText")
def parse_display_text(client, payload):
    display_text = clean_bytes(payload[0:32])
    time_out_value = 9999

    client.state.update_prompt(display_text, time_out_value)
    client.state.display_notify = {
        "timeOutValue": time_out_value,
        "notify": display_text,
        "received_at": time.time() if time_out_value > 0 else None,
    }

    logger.info(f"[RECV] DisplayText='{display_text}'")

