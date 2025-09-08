import struct
import datetime
import time
from dispatcher import register_handler
from messages.generic import STIMULUS_NAMES, CALL_STATE_NAMES, TONE_NAMES, TONE_OUTPUT_DIRECTION_NAMES, CALL_TYPE_NAMES, CALL_STAT_STATE_NAMES, clean_bytes, send_skinny_message
from utils.client import get_local_ip, ip_to_int, _keypad_code_to_char
from audio_worker import RTPReceiver, RTPSender, socket
import logging
logger = logging.getLogger(__name__)


@register_handler(0x0085, "SetRinger")
def parse_set_ringer(client, payload):
    ring_mode, ring_duration, line_instance, call_reference = struct.unpack("<IIII", payload)

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


@register_handler(0x0088, "SetSpeakerMode")
def parse_set_speaker_mode(client, payload):
    speaker_mode = struct.unpack("<I", payload)[0]

    client.state.speaker_mode = speaker_mode
    # logging.info(f"[RECV] SetSpeakerMode speakerMode: {speaker_mode}")
    logger.info(f"[RECV] SetSpeakerMode")


@register_handler(0x0086, "SetLamp")
def parse_set_lamp(client, payload):
    stimulus, stimulus_instance, lamp_mode = struct.unpack("<III", payload)
    stimulus_name = STIMULUS_NAMES.get(str(stimulus), "UNKNOWN")

    client.state.stimulus = 0
    client.state.stimulus_name = None
    client.state.stimulus_instance = 0
    client.state.lamp_mode = 0

    # logging.info(f"[RECV] SetLamp stimulus: {stimulus_name} ({stimulus}), stimulusInstance: {stimulus_instance}, lampMode: {lamp_mode}")
    logger.info(f"[RECV] SetLamp")


@register_handler(0x0111, "CallState")
def parse_call_state(client, payload):
    call_state, line_instance, call_reference, privacy, precedence_level, precedence_domain = struct.unpack("<IIIIII", payload)
    call_state_name = CALL_STATE_NAMES.get(call_state, "UNKNOWN")

    current_time = datetime.datetime.now(datetime.timezone.utc)
    if str(call_reference) in client.state.calls:
        call_started = client.state.calls[str(call_reference)]["call_started"]
        call_ended = client.state.calls[str(call_reference)]["call_ended"]
    else:
        call_started = None
        call_ended = None

    client.state.calls[str(call_reference)] = {"call_state": call_state, "call_state_name": call_state_name, "line_instance": line_instance, "call_reference": call_reference, "privacy": privacy, "precedence_level": precedence_level, "precedence_domain": precedence_domain, "current_time": current_time, "call_started": call_started, "call_ended": call_ended}
    if str(call_reference) not in client.state.calls_list:
        client.state.calls_list.append(str(call_reference))

    if call_state in [0, 2]:                        # Idle, OnHook
        if str(call_reference) in client.state.active_calls_list:
            client.state.active_calls_list.remove(str(call_reference))

        client.state.calls[str(call_reference)]["call_ended"] = current_time
        client.state.active_call = False
        client.state.call_active = False
        client.state.call_connected = False
        client.state.media_active = False
        client.events.call_ringing.clear()
        client.events.call_connected.clear()
        client.events.media_started.clear()
        if call_state == 2:
            client.events.call_ended.set()
        else:
            client.events.call_ended.clear()
    elif call_state in [3, 4]:                      # RingOut, RingIn
        if str(call_reference) not in client.state.active_calls_list:
            client.state.active_calls_list.append(str(call_reference))

        client.state.call_active = True
        client._call_epoch += 1
        client.state.last_call_epoch = client._call_epoch
        client.events.call_ringing.set()
        client.events.call_ended.clear()
    elif call_state in [5,]:                        # Connected
        if str(call_reference) not in client.state.active_calls_list:
            client.state.active_calls_list.append(str(call_reference))

        if client.state.calls[str(call_reference)].get("call_started") is None:
            client.state.calls[str(call_reference)]["call_started"] = current_time
        client.state.call_active = True
        client.state.call_connected = True
        client.events.call_connected.set()
        client.events.call_ended.clear()

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # Track call lifecycle: TODO: working on this next
    # previous_state = handle_call_state(line_instance, call_reference, call_state_name, shared_state)
    # lifecycle = shared_state["calls"][line_instance][call_reference]["lifecycle"]
    # if call_state_name == "OnHook":
    #     if "RingIn" in lifecycle and "Connected" not in lifecycle:
    #         log_call_event("missed", {}, shared_state, log)
    #     elif "RingIn" in lifecycle and "Connected" in lifecycle:
    #         log_call_event("received", {}, shared_state, log)
    #     elif "RingOut" in lifecycle:
    #         log_call_event("placed", {}, shared_state, log)

    # logger.info(f"[RECV] CallState callState: {call_state_name} ({call_state}), lineInstance: {line_instance}, callReference: {call_reference}, privacy: {privacy}, precedenceLevel: {precedence_level}, precedenceDomain: {precedence_domain}")
    logger.info(f"[RECV] CallState")


@register_handler(0x0116, "ActivateCallPlane")
def parse_activate_callplane(client, payload):
    line_instance = struct.unpack("<I", payload)[0]

    client.state.active_call = True
    client.state.active_call_line_instance = line_instance

    # logger.info(f"[RECV] ActivateCallPlane lineInstance: {line_instance}")
    logger.info(f"[RECV] ActivateCallPlane")


@register_handler(0x0082, "StartTone")
def parse_start_tone(client, payload):
    tone, tone_output_direction, line_instance, call_reference = struct.unpack("<IIII", payload)
    tone_name = TONE_NAMES.get(tone, "UNKNOWN")
    tone_output_direction_name = TONE_OUTPUT_DIRECTION_NAMES.get(tone_output_direction, "UNKNOWN")

    client.state.play_tones = {"tone": tone, "tone_name": tone_name, "tone_output_direction": tone_output_direction, "tone_output_direction_name": tone_output_direction_name, "call_reference": call_reference, "line_instance": line_instance}
    client.audio.set_tone(line_instance, tone, gain_db=client.state.tone_volume)

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # logger.info(f"[RECV] StartTone tone: {tone_name} ({tone}), toneOutputDirection: {tone_output_direction_name} ({tone_output_direction}), lineInstance: {line_instance}, callReference: {call_reference}")
    logger.info(f"[RECV] StartTone")


@register_handler(0x0083, "StopTone")
def parse_stop_tone(client, payload):
    line_instance, call_reference = struct.unpack("<II", payload)

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
    calling_party_name = clean_bytes(payload[:40])                                                                       # 40 bytes
    calling_party = clean_bytes(payload[40:64])                                                                          # 24 bytes
    called_party_name = clean_bytes(payload[64:104])                                                                     # 40 bytes
    called_party = clean_bytes(payload[104:128])                                                                         # 24 bytes
    line_instance, call_reference, call_type = struct.unpack("<III", payload[128:140])                            # 4 + 4 + 4
    original_called_party_name = clean_bytes(payload[140:180])                                                           # 40 bytes
    original_called_party = clean_bytes(payload[180:204])                                                                # 24 bytes
    last_redirecting_party_name = clean_bytes(payload[204:244])                                                          # 40 bytes
    last_redirecting_party = clean_bytes(payload[244:268])                                                               # 24 bytes
    original_cpdn_redirect_reason, last_redirecting_reason = struct.unpack("<II", payload[268:276])               # 4 + 4
    cgpn_voicemail_box = clean_bytes(payload[276:300])                                                                   # 24 bytes
    cdpn_voicemail_box = clean_bytes(payload[300:324])                                                                   # 24 bytes
    original_cdpn_voicemail_box = clean_bytes(payload[324:348])                                                          # 24 bytes
    last_redirecting_voicemail_box = clean_bytes(payload[348:372])                                                       # 24 bytes
    call_instance, call_security_status, party_pi_restriction_bits = struct.unpack("<III", payload[372:])         # 4 + 4 + 4

    call_type_name = CALL_TYPE_NAMES.get(call_type, "UNKNOWN")

    binary_flags = format(party_pi_restriction_bits, 'b').zfill(32)
    client.state.callinfo[str(call_reference)] = {"calling_party_name": calling_party_name, "calling_party": calling_party, "called_party_name": called_party_name, "called_party": called_party, "line_instance": line_instance, "call_reference": call_reference, "call_type": call_type, "call_type_name": call_type_name, "original_called_party_name": original_called_party_name, "original_called_party": original_called_party, "last_redirecting_party_name": last_redirecting_party_name, "last_redirecting_party": last_redirecting_party, "original_cpdn_redirect_reason": original_cpdn_redirect_reason, "last_redirecting_reason": last_redirecting_reason, "cgpn_voice_mail_box": cgpn_voicemail_box, "cdpn_voice_mail_box": cdpn_voicemail_box, "original_cdpn_voice_mail_box": original_cdpn_voicemail_box, "last_redirecting_voice_mail_box": last_redirecting_voicemail_box, "call_instance": call_instance, "call_security_status": call_security_status, "party_pi_restriction_bits": binary_flags}
    if str(call_reference) not in client.state.calls_list:
        client.state.calls_list.append(str(call_reference))

    # # Track call lifecycle
    # call_state_name = "RingIn"
    # handle_call_state(line_instance, call_reference, call_state_name, shared_state)
    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log)

    # logger.info(f"[RECV] CallInfo callingPartyName: {calling_party_name}, callingParty: {calling_party}, calledPartyName: {called_party_name}, calledParty: {called_party}, lineInstance: {line_instance}, callReference: {call_reference}, callType: {call_type_name} ({call_type}), originalCalledPartyName: {original_called_party_name}, originalCalledParty: {original_called_party}, lastRedirectingPartyName: {last_redirecting_party_name}, lastRedirectingParty: {last_redirecting_party}, originalCpdnRedirectReason: {original_cpdn_redirect_reason}, lastRedirectingReason: {last_redirecting_reason}, cgpnVoiceMailBox: {cgpn_voicemail_box}, cpdnVoiceMailBox: {cdpn_voicemail_box}, originalCdpnVoiceMailBox: {original_cdpn_voicemail_box}, lastRedirectingVoiceMailBox: {last_redirecting_voicemail_box}, callInstance: {call_instance}, callSecurityStatus: {call_security_status}, partyPIRestrictionBits: {binary_flags}")
    logger.info(f"[RECV] CallInfo")


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
    conference_id, pass_through_party_id, remote_ip_addr, remote_port_number, milli_second_packet_size, compression_type, precedence_value, ss_value, max_frames_per_packet, padding, g723_bitrate, call_reference, algorithm_id, key_len, salt_len = struct.unpack("<IIIIIIIIHHIIIHH", payload[:52])
    key_bytes = payload[52:68]                                                                                           # 16 bytes
    salt_bytes = payload[68:84]                                                                                          # 16 bytes

    key = clean_bytes(key_bytes)
    salt = clean_bytes(salt_bytes)
    # logger.info(f"[RECV] StartMediaTransmission conferenceId: {conference_id}, passThroughPartyId: {pass_through_party_id}, remoteIpAddr: {remote_ip_addr}, remotePortNumber: {remote_port_number}, milliSecondPacketSize: {milli_second_packet_size}, compressionType: {compression_type}, precedenceValue: {precedence_value}, ssValue: {ss_value}, maxFramesPerPacket: {max_frames_per_packet}, padding: {padding}, g723Bitrate: {g723_bitrate}, callReference: {call_reference}, algorithmId: {algorithm_id}, keyLen: {key_len}, saltLen: {salt_len}, key: {key}, salt: {salt}")

    client.state.media_active = True
    client.events.media_started.set()

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
    pt = 0  # usually PCMU in NA; map from compression_type if you have it
    tx = RTPSender(remote_ip, remote_port_number, ptime_ms=ptime, payload_type=pt, log=client.logger)
    tx.start()
    play_mode = client.state.kv_dict.get("audio_play_mode", "silent")
    if play_mode in ["silent", "silence"]:
        logger.debug(f"RTP Sending mode: Silence")
        pass
    elif play_mode in ["mic", "microphone"]:
        logger.debug(f"RTP Sending mode: Microphone")
        tx.send_microphone()
    else:
        logger.debug(f"RTP Sending mode: File {play_mode}")
        tx.send_wav(play_mode, loop=True)
    client.state._rtp_tx = tx

    logger.info(f"[RECV] StartMediaTransmission")


@register_handler(0x008B, "StopMediaTransmission")
def parse_stop_media_transmission(client, payload):
    conference_id, pass_through_party_id, call_reference = struct.unpack("<III", payload)

    # Close/clear RTP Sender
    tx = client.state._rtp_tx or None
    if tx: tx.stop()

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
    logger.info(f"[RECV] StopMediaTransmission")


@register_handler(0x0105, "OpenReceiveChannel")
def parse_open_receive_channel(client, payload):
    conference_id, pass_through_party_id, milli_second_packet_size, compression_type, ec_value, g723_bitrate, call_reference, algorithm_id, key_len, salt_len = struct.unpack("<IIIIIIIIHH", payload[:36])
    key_bytes = payload[36:52]                                                                                           # 16 bytes
    salt_bytes = payload[52:68]                                                                                          # 16 bytes

    key = clean_bytes(key_bytes)
    salt = clean_bytes(salt_bytes)
    # logger.info(f"[RECV] OpenReceiveChannel conferenceId: {conference_id}, passThroughPartyId: {pass_through_party_id}, milliSecondPacketSize: {milli_second_packet_size}, compressionType: {compression_type}, ecValue: {ec_value}, g723Bitrate: {g723_bitrate}, callReference: {call_reference}, algorithmId: {algorithm_id}, keyLen: {key_len}, saltLen: {salt_len}, key: {key}, salt: {salt}")
    logger.info(f"[RECV] OpenReceiveChannel")

    # trace_data = {
    #     "conferenceId": conference_id,
    #     "passThroughPartyId": pass_through_party_id,
    #     "milliSecondPacketSize": milli_second_packet_size,
    #     "compressionType": compression_type,
    #     "ecValue": ec_value,
    #     "g723Bitrate": g723_bitrate,
    #     "callReference": call_reference,
    #     "algorithmId": algorithm_id,
    #     "keyLen": key_len,
    #     "saltLen": salt_len,
    #     "key": key,
    #     "salt": salt,
    # }

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=None, log=log, override_message_data=trace_data)

    send_open_receive_channel_ack(client, {"passThroughPartyId": pass_through_party_id, "callReference": call_reference})


@register_handler(0x0034, "OpenReceiveChannelAck")
def send_open_receive_channel_ack(client, payload):
    media_reception_status = 0  # 0 = OK
    # loopback_config = client.state.get("loopback", {})
    # mode = loopback_config.get("mode", "play")  # default to play
    # loopback_enabled = loopback_config.get("enabled", False)
    # port_number = 0

    rx = RTPReceiver(worker=client.audio, bind_ip="0.0.0.0", source_id="rx", log=client.logger)
    rx.start()
    client.state._rtp_rx = rx
    port_number = rx.port

    # player = RTPAudioPlayer()
    # player.start()
    # port_number = player.port
    # client.state["rtp_player"] = player
    # client.state["rtp_socket"] = player.sock
    # client.state["rtp_port_number"] = port_number

    # # Default playback
    # player = None
    # if loopback_enabled and mode in ("play", "both"):
    #     player = RTPAudioPlayer(log=log)
    #     player.start()
    #     log(f"[Audio] RTP player started in mode: {mode}")
    #     port_number = player.port
    #     shared_state["rtp_player"] = player
    #     shared_state["rtp_socket"] = player.sock
    #     shared_state["rtp_port_number"] = port_number
    #
    # # Setup for loopback echo
    # echo = None
    # if loopback_enabled and mode in ("loopback", "both"):
    #     log("loopback mode requested")
    #     remote_ip = shared_state.get("rtp_remote_ip")
    #     remote_port = shared_state.get("rtp_remote_port")
    #     if remote_ip and remote_port:
    #         echo = RTPLoopbackEcho(remote_ip=remote_ip, remote_port=remote_port, log=log)
    #         echo.start()
    #         log(f"[Audio] RTP loopback started in mode: {mode}")
    #         port_number = echo.local_port
    #         shared_state["rtp_echo_player"] = echo
    #         shared_state["rtp_echo_socket"] = echo.sock
    #         shared_state["rtp_echo_port_number"] = port_number
    #     else:
    #         log("no port info")

    call_manager_host_ip = get_local_ip(client.state.server)

    station_ip = ip_to_int(call_manager_host_ip)  # still in int form
    pass_through_party_id = payload["passThroughPartyId"]
    call_reference = payload["callReference"]
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
    conference_id, pass_through_party_id, call_reference = struct.unpack("<III", payload)

    # Close/clear RTP Receiver
    rx = client.state._rtp_rx or None
    if rx: rx.stop()

    # player = client.state.get("rtp_player")
    # if player:
    #     player.stop()
    #     client.state["rtp_player"] = None
    #     client.state["rtp_socket"] = None
    #     client.state["rtp_port_number"] = None
    #
    # echo = client.state.get("rtp_echo_player")
    # if echo:
    #     echo.stop()
    #     client.state["rtp_echo_player"] = None
    #     client.state["rtp_echo_socket"] = None
    #     client.state["rtp_echo_port_number"] = None
    #
    # # Close/clear RTP Sender
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
    # call_state_name = "OnHook"
    # handle_call_state(conference_id, call_reference, call_state_name, shared_state)
    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=None, log=log, override_message_data=trace_data)

    # logger.info(f"[RECV] CloseReceiveChannel conferenceId: {conference_id}, passThroughPartyId: {pass_through_party_id}, callReference: {call_reference}")
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
