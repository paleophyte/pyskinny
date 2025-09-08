import struct
import calendar
import time
import datetime
from dispatcher import register_handler
from messages.generic import get_skinny_message, send_skinny_message, KEY_SET_INDEX_NAMES, SOFTKEY_TEMPLATE_INDEXES, SOFTKEY_INFO_INDEXES
from utils.client import clean_bytes
import logging
logger = logging.getLogger(__name__)


@register_handler(0x009B, "CapabilitiesReq")
def send_caps_and_stats(sock, payload):
    send_capabilities_response(sock, payload)
    send_post_registration_sequence(sock, payload)
    send_stat_requests_1(sock, payload)


def send_capabilities_response(client, payload):
    msg_id = 0x0010
    cap_count = 7
    total_caps = 18  # expected by CUCM

    capabilities = [
        # payload_id, max_frames, codec_mode, dyn_payload, param1, param2
        (0x04, 40, 0, 0, 0, 0),  # G711Ulaw
        (0x02, 40, 0, 0, 0, 0),  # G711Alaw
        (0x0B, 60, 0, 0, 0, 0),  # G729
        (0x0C, 60, 0, 0, 0, 0),  # G729AnnexA
        (0x0F, 60, 0, 0, 0, 0),  # G729AnnexB
        (0x12, 60, 0, 0, 0, 0),  # GSM Full Rate
        (0x56, 60, 3, 98, 0, 0), # iLBC
    ]

    # Add padding to reach 18 capabilities
    while len(capabilities) < total_caps:
        capabilities.append((0, 0, 0, 0, 0, 0))

    payload_length = 8 + total_caps * 16  # capCount (4) + 18 × 16
    header = struct.pack("<I I I", payload_length, 0, msg_id)
    body = struct.pack("<I", cap_count)

    for cap in capabilities:
        body += struct.pack("<I I B B B B I", *cap, 0)  # pad with 0

    packet = header + body
    client.sock.sendall(packet)
    logger.info(f"({client.state.device_name}) [SEND] CapabilitiesRes with {cap_count} capabilities")


def send_post_registration_sequence(client, payload):
    # ButtonTemplateReq with trailing 0x08 00 00 00
    send_skinny_message(client, 0x000E, struct.pack("<I", 8))

    # SoftKeyTemplateReq (no payload)
    send_skinny_message(client, 0x0028)

    # SoftKeySetReq (no payload)
    send_skinny_message(client, 0x0025)


def send_stat_requests_1(client, payload):
    # ConfigStatReq (no payload)
    send_skinny_message(client, 0x000c)

    # LineStatReq with trailing 0x01 00 00 00 (this gets info about Line 1)
    send_skinny_message(client, 0x000b, struct.pack("<I", 1))

    # ForwardStatReq with trailing 0x01 00 00 00 (this gets info about Line 1)
    send_skinny_message(client, 0x0009, struct.pack("<I", 1))

    # RegisterAvailableLines with trailing 0x02 00 00 00 (maxNumOfAvailLines = 2)
    send_skinny_message(client, 0x002d, struct.pack("<I", client.state.line_count))


def send_stat_requests_2(client, payload):
    # Next, the phone stacks a bunch of messages together
    packet = get_skinny_message(0x002d, struct.pack("<I", client.state.line_count))                    # RegisterAvailableLines

    for k, v in client.state.button_template.items():
        button_type = v["type"]
        button_instance = v["instance"]
        # print(button_type, button_instance)
        if button_type == 9:
            logger.debug(f"({client.state.device_name}) [SEND] LineStatReq for line {button_instance}")
            packet += get_skinny_message(0x000b, struct.pack("<I", button_instance))  # LineStatReq for Line 'l+1'
        elif button_type == 2:
            logger.debug(f"({client.state.device_name}) [SEND] SpeedDialStatReq for speed dial {button_instance}")
            packet += get_skinny_message(0x000a, struct.pack("<I", button_instance))  # SpeedDialStatReq for SD 's+1'

    client.sock.sendall(packet)

    # for l in range(0, client.state.line_count):
    #     logger.debug(f"({client.state.device_name}) [SEND] LineStatReq for line {l+1}")
    #     packet += get_skinny_message(0x000b, struct.pack("<I", l+1))             # LineStatReq for Line 'l+1'
    #
    # for s in range(0, client.state.speed_dial_count):
    #     logger.debug(f"({client.state.device_name}) [SEND] SpeedDialStatReq for speed dial {s+1}")
    #     packet += get_skinny_message(0x000a, struct.pack("<I", s+1))             # SpeedDialStatReq for SD 's+1'

    # packet += get_skinny_message(0x000b, struct.pack("<I", 1))             # LineStatReq for Line 1
    # packet += get_skinny_message(0x000b, struct.pack("<I", 2))             # LineStatReq for Line 2
    # packet += get_skinny_message(0x000a, struct.pack("<I", 1))             # SpeedDialStatReq for SD 1
    # packet += get_skinny_message(0x000a, struct.pack("<I", 2))             # SpeedDialStatReq for SD 2
    # packet += get_skinny_message(0x000a, struct.pack("<I", 3))             # SpeedDialStatReq for SD 3
    # packet += get_skinny_message(0x000a, struct.pack("<I", 4))             # SpeedDialStatReq for SD 4
    # packet += get_skinny_message(0x000a, struct.pack("<I", 5))             # SpeedDialStatReq for SD 5
    # packet += get_skinny_message(0x000a, struct.pack("<I", 6))             # SpeedDialStatReq for SD 6
    # packet += get_skinny_message(0x0009, struct.pack("<I", 1))             # ForwardStatReq for Line 1
    # client.sock.sendall(packet)

    # TimeDateReq
    send_skinny_message(client, 0x000d)


@register_handler(0x000d, "TimeDateReq")
def _time_date_req(client, payload):
    pass


@register_handler(0x000e, "ButtonTemplateReq")
def _button_template_req(client, payload):
    pass


@register_handler(0x0028, "SoftKeyTemplateReq")
def _softkey_template_req(client, payload):
    pass


@register_handler(0x0025, "SoftKeySetReq")
def _softkey_set_req(client, payload):
    pass


@register_handler(0x000c, "ConfigStatReq")
def _config_stat_req(client, payload):
    pass


@register_handler(0x000b, "LineStatReq")
def _line_stat_req(client, payload):
    pass


@register_handler(0x000a, "SpeedDialStatReq")
def _speed_dial_stat_req(client, payload):
    pass


@register_handler(0x0009, "ForwardStatReq")
def _forward_stat_req(client, payload):
    pass


@register_handler(0x002d, "RegisterAvailableLines")
def _register_available_lines(client, payload):
    pass


@register_handler(0x0097, "ButtonTemplateRes")
def parse_button_template(client, payload):
    button_types = {
        "2": "Speed Dial",
        "9": "Line"
    }

    button_offset, button_count, total_button_count = struct.unpack("<III", payload[:12])
    max_btn = int(len(payload[12:])/2)
    # logger.info(f"({client.state.device_name}) [RECV] ButtonTemplateRes ButtonOffset: {button_offset}, ButtonCount: {button_count}, TotalButtonCount: {total_button_count}, max: {max_btn}")
    logger.info(f"({client.state.device_name}) [RECV] ButtonTemplateRes")

    client.state.button_offset = button_offset
    client.state.button_count = button_count
    client.state.total_button_count = total_button_count
    client.state.max_button_count = max_btn
    client.state.button_template = {}

    for x in range(button_count):
        offset = 12 + x * 2
        if offset + 2 > len(payload):
            logger.warning(f"({client.state.device_name}) [WARN] Button {x} exceeds payload length")
            break

        btn_def = struct.unpack("<H", payload[offset:offset+2])[0]
        btn_index = btn_def & 0xFF
        btn_type = (btn_def >> 8) & 0xFF
        btn_type_name = button_types.get(str(btn_type), "UNKNOWN")

        # logger.debug(f"  Button {x+1}: Instance={btn_index}, Type={btn_type_name}")
        client.state.button_template[str(x + 1)] = {"instance": btn_index, "type": btn_type, "type_name": btn_type_name}


@register_handler(0x0108, "SoftKeyTemplateRes")
def parse_softkey_template(client, payload):
    softkey_offset, softkey_count, total_softkey_count = struct.unpack("<III", payload[:12])
    max_sk = int(len(payload[12:])/20)

    logger.info(f"({client.state.device_name}) [RECV] SoftKeyTemplateRes")
    # logger.info(f"({client.state.device_name}) [RECV] SoftKeyTemplateRes softKeyOffset: {softkey_offset}, softKeyCount: {softkey_count}, totalSoftKeyCount: {total_softkey_count}, max: {max_sk}")

    client.state.softkey_offset = softkey_offset
    client.state.softkey_count = softkey_count
    client.state.total_softkey_count = total_softkey_count
    client.state.max_softkey_count = max_sk
    client.state.softkey_template = {}

    softkeys = []
    for x in range(softkey_count):
        offset = 12 + x * 20
        if offset + 20 > len(payload):
            logger.warning(f"({client.state.device_name}) [WARN] Softkey {x} exceeds payload length")
            break

        label_bytes = payload[offset:offset+16]
        event_bytes = payload[offset+16:offset+20]

        softkey_label = label_bytes.decode("ascii", errors="ignore").rstrip('\x00')
        softkey_event = struct.unpack("<I", event_bytes)[0]
        softkeys.append((softkey_label, softkey_event, softkey_event))

        client.state.softkey_template[str(x+1)] = {"label": softkey_label, "event": softkey_event}
        # logger.debug(f"  Softkey {x+1}: Label={softkey_label}, Event={softkey_event}")


@register_handler(0x0109, "SoftKeySetRes")
def parse_softkey_set(client, payload):
    softkeyset_offset, softkeyset_count, total_softkeyset_count = struct.unpack("<III", payload[:12])
    max_sks = int(len(payload[12:])/48)

    client.state.softkey_set_offset = softkeyset_offset
    client.state.softkey_set_count = softkeyset_count
    client.state.total_softkey_set_count = total_softkeyset_count
    client.state.max_softkey_set_count = max_sks
    client.state.selected_softkey_set = 0
    client.state.softkey_set_definition = {}

    # logger.info(f"({client.state.device_name}) [RECV] SoftKeySetRes softKeySetOffset: {softkeyset_offset}, softKeySetCount: {softkeyset_count}, totalSoftKeySetCount: {total_softkeyset_count}, max: {max_sks}")
    logger.info(f"({client.state.device_name}) [RECV] SoftKeySetRes")

    for x in range(softkeyset_count):
        # shared_state["SoftKeySetRes"][str(x)] = {}
        offset = 12 + x * 48
        if offset + 48 > len(payload):
            logger.debug(f"({client.state.device_name}) [WARN] SoftkeySet {x} exceeds payload length")
            break

        skti_bytes = payload[offset:offset+16]              # 16 bytes: softKeyTemplateIndex, each is 1 byte
        skii_bytes = payload[offset+16:offset+48]           # 32 bytes: softKeyInfoIndex, each is 2 bytes
        client.state.softkey_set_definition[str(x)] = {}

        # logger.debug(f"  Definition {x} / {softkeyset_count}")
        for i in range(total_softkeyset_count):
            template_index = skti_bytes[i]
            info_index = struct.unpack_from("<H", skii_bytes, i * 2)[0]

            template_index_name = SOFTKEY_TEMPLATE_INDEXES.get(template_index, "UNKNOWN")
            template_info_name = SOFTKEY_INFO_INDEXES.get(info_index, "UNKNOWN")

            if i == 0 or template_index != 0:
                client.state.softkey_set_definition[str(x)][str(i)] = {"template_index": template_index, "template_index_name": template_index_name, "info_index": info_index, "template_info_name": template_info_name}
                # logger.debug(f"    - softKeyTemplateIndex {i}: {template_index_name} ({template_index}), softKeyInfoIndex {i+1}: {template_info_name} ({info_index})")


@register_handler(0x0110, "SelectSoftKeys")
def parse_select_softkeys(client, payload):
    lineInstance, callReference, softKeySetIndex, validKeyMask = struct.unpack("<IIII", payload[:16])
    softKeySetIndexName = KEY_SET_INDEX_NAMES.get(softKeySetIndex, "UNKNOWN")

    # client.state.selected_softkeys[str(lineInstance)] = {"call_reference": callReference, "softkeyset_index": softKeySetIndex, "softkeyset_index_name": softKeySetIndexName, "validkey_mask": validKeyMask, "validkey_mask_str": f"{validKeyMask:016b}"}
    client.state.selected_softkeys[str(callReference)] = {"line_instance": lineInstance, "call_reference": callReference, "softkeyset_index": softKeySetIndex, "softkeyset_index_name": softKeySetIndexName, "validkey_mask": validKeyMask, "validkey_mask_str": f"{validKeyMask:016b}"}
    client.state.selected_softkey_set = softKeySetIndex

    # logger.info(f"({client.state.device_name}) [RECV] SelectSoftKeys lineInstance: {lineInstance}, callReference: {callReference}, softKeySetIndex: {softKeySetIndexName} ({softKeySetIndex}), validKeyMask: {validKeyMask:016b}")
    logger.info(f"({client.state.device_name}) [RECV] SelectSoftKeys")


@register_handler(0x0112, "DisplayPromptStatus")
def parse_display_prompt_status(client, payload):
    if len(payload) < 44:
        logger.warning(f"({client.state.device_name}) [WARN] DisplayPromptStatus too short: {len(payload)} bytes")
        return

    timeout = struct.unpack("<I", payload[0:4])[0]
    prompt_status = payload[4:36].decode("ascii", errors="ignore").strip("\x00")
    line_instance = struct.unpack("<I", payload[36:40])[0]
    call_reference = struct.unpack("<I", payload[40:44])[0]

    client.state.update_prompt(prompt_status, timeout, line_instance, call_reference)

    # logger.info(f"[PROMPT] '{prompt_status}' (Timeout: {timeout}, Line: {line_instance}, CallRef: {call_reference})")
    logger.info(f"({client.state.device_name}) [RECV] DisplayPromptStatus")



@register_handler(0x0113, "ClearPromptStatus")
def parse_clear_prompt_status(client, payload):
    line_instance, call_reference = struct.unpack("<II", payload)

    client.state.update_prompt("", 0, line_instance, call_reference)

    # Call Trace Logging
    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(call_reference, message_info, shared_state, line_instance=line_instance, log=log, override_message_name="DisplayPromptStatus")

    # logger.info(f"[RECV] ClearPromptStatus lineInstance: {line_instance}, callReference: {call_reference}")
    logger.info(f"[RECV] ClearPromptStatus")


@register_handler(0x0093, "ConfigStatRes")
def parse_config_stat(client, payload):
    device_name_bytes = payload[:16]                                                            # 16 bytes
    reserved, instance = struct.unpack("<II", payload[16:24])                            # 4 bytes, 4 bytes
    user_name_bytes = payload[24:64]                                                            # 40 bytes
    server_name_bytes = payload[64:104]                                                         # 40 bytes
    number_of_lines, number_of_speed_dials = struct.unpack("<II", payload[104:112])      # 4 bytes, 4 bytes

    device_name = device_name_bytes.decode("ascii", errors="ignore").rstrip('\x00')
    user_name = user_name_bytes.decode("ascii", errors="ignore").rstrip('\x00')
    server_name = server_name_bytes.decode("ascii", errors="ignore").rstrip('\x00')

    client.state.line_count = int(number_of_lines)
    client.state.speed_dial_count = int(number_of_speed_dials)
    client.state.instance = int(instance)
    client.state.user_name = user_name
    client.state.server_name = server_name

    # logger.info(f"[RECV] ConfigStatRes deviceName: {device_name}, instance: {instance}, userName: {user_name}, serverName: {server_name}, numberOfLines: {number_of_lines}, numberOfSpeedDials: {number_of_speed_dials}")
    logger.info(f"({client.state.device_name}) [RECV] ConfigStatRes")

    send_stat_requests_2(client, payload)


@register_handler(0x0092, "LineStatRes")
def parse_line_stat(client, payload):
    line_number = struct.unpack("<I", payload[:4])[0]                                    # 4 bytes
    line_dir_number_bytes = payload[4:28]                                                       # 24 bytes
    line_fqdn_bytes = payload[28:68]                                                            # 40 bytes
    line_text_label_bytes = payload[68:108]                                                     # 40 bytes
    line_display_options = struct.unpack("<I", payload[108:])[0]                         # 4 bytes

    line_dir_number = line_dir_number_bytes.decode("ascii", errors="ignore").rstrip('\x00')
    line_fqdn = line_fqdn_bytes.decode("ascii", errors="ignore").rstrip('\x00')
    line_text_label = line_text_label_bytes.decode("ascii", errors="ignore").rstrip('\x00')

    # message_info = get_current_message_info(message_table)
    # # trace = shared_state.get("trace", print)
    # trace(0, message_info, shared_state, line_instance=line_number, log=log)
    # cleanup_stale_calls(shared_state, line_instance=line_number, log=log)

    client.state.lines[str(line_number)] = {"line_dir_number": line_dir_number, "line_fully_qualified_display_name": line_fqdn, "line_text_label": line_text_label, "line_display_options": line_display_options, "line_display_options_str": f"{line_display_options:4b}"}

    # logger.info(f"[RECV] LineStatRes lineNumber: {line_number}, lineDirNumber: {line_dir_number}, lineFullyQualifiedDisplayName: {line_fqdn}, lineTextLabel: {line_text_label}, lineDisplayOptions: {line_display_options}")
    logger.info(f"({client.state.device_name}) [RECV] LineStatRes")


@register_handler(0x0090, "ForwardStatRes")
def parse_forward_stat(client, payload):
    active_forward, line_number, forward_all_active = struct.unpack("<III", payload[:12])   # 4 bytes, 4 bytes, 4 bytes
    forward_all_dir_num_bytes = payload[12:36]                                                     # 24 bytes
    forward_busy_active = struct.unpack("<I", payload[36:40])[0]                            # 4 bytes
    forward_busy_dir_num_bytes = payload[40:64]                                                    # 24 bytes
    forward_no_answer_active = struct.unpack("<I", payload[64:68])[0]                       # 4 bytes
    forward_no_answer_dir_num_bytes = payload[68:92]                                               # 24 bytes

    forward_all_dir_num = forward_all_dir_num_bytes.decode("ascii", errors="ignore").rstrip('\x00')
    forward_busy_dir_num = forward_busy_dir_num_bytes.decode("ascii", errors="ignore").rstrip('\x00')
    forward_no_answer_dir_num = forward_no_answer_dir_num_bytes.decode("ascii", errors="ignore").rstrip('\x00')

    client.state.active_forward = active_forward
    client.state.call_forward[str(line_number)] = {"forward_all_active": forward_all_active, "forward_all_dirnum": forward_all_dir_num, "forward_busy_active": forward_busy_active, "forward_busy_dirnum": forward_busy_dir_num, "forward_no_answer_active": forward_no_answer_active, "forward_no_answer_dirnum": forward_no_answer_dir_num}

    # logger.info(f"({client.state.device_name}) [RECV] ForwardStatRes activeForward: {active_forward}, lineNumber: {line_number}, forwardAllActive: {forward_all_active}, forwardAllDirnum: {forward_all_dir_num}, forwardBusyActive: {forward_busy_active}, forwardBusyDirnum: {forward_busy_dir_num}, forwardNoAnswerActive: {forward_no_answer_active}, forwardNoAnswerDirnum: {forward_no_answer_dir_num}")
    logger.info(f"({client.state.device_name}) [RECV] ForwardStatRes")


@register_handler(0x0091, "SpeedDialStatRes")
def parse_speed_dial_stat(client, payload):
    speed_dial_number = struct.unpack("<I", payload[:4])[0]                                 # 4 bytes
    speed_dial_dir_num_bytes = payload[4:28]                                                       # 24 bytes
    speed_dial_display_name_bytes = payload[28:68]                                                 # 40 bytes

    speed_dial_dir_num = clean_bytes(speed_dial_dir_num_bytes)
    speed_dial_display_name = clean_bytes(speed_dial_display_name_bytes)

    client.state.speed_dials[str(speed_dial_number)] = {"speedDialDirNumber": speed_dial_dir_num, "speedDialDisplayName": speed_dial_display_name}

    # logger.info(f"({client.state.device_name}) [RECV] SpeedDialStatRes speedDialNumber: {speed_dial_number}, speedDialDirNumber: {speed_dial_dir_num}, speedDialDisplayName: {speed_dial_display_name}")
    logger.info(f"({client.state.device_name}) [RECV] SpeedDialStatRes")


@register_handler(0x0094, "TimeDateRes")
def parse_time_date(client, payload):
    w_year, w_month, w_day_of_week, w_day, w_hour, w_minute, w_second, w_millisecond, w_systemtime = struct.unpack("<IIIIIIIII", payload)
    day_name = calendar.day_name[(w_day_of_week + 6) % 7]

    try:
        dt_system = datetime.datetime.utcfromtimestamp(w_systemtime)
        system_time_str = dt_system.strftime("%m/%d/%Y, %A %H:%M:%S") + " UTC"
    except (OSError, ValueError):
        system_time_str = f"[Invalid Timestamp: {w_systemtime}]"

    initial_time_dt = datetime.datetime(
        year=w_year,
        month=w_month,
        day=w_day,
        hour=w_hour,
        minute=w_minute,
        second=w_second
    )
    received_at = time.time()

    # shared_state["TimeDateRes"] = {"wMonth": w_month, "wDay": w_day, "wYear": w_year, "wDayOfWeek": w_day_of_week, "wDayOfWeekName": day_name, "wHour": w_hour, "wMinute": w_minute, "wSecond": w_second, "wMillisecond": w_millisecond, "wSystemTime": w_systemtime, "wSystemTimeDesc": system_time_str, "initial_time_dt": initial_time_dt, "received_at": received_at}
    client.state.w_month = w_month
    client.state.w_day = w_day
    client.state.w_year = w_year
    client.state.w_day_of_week = w_day_of_week
    client.state.w_day_of_week_name = day_name
    client.state.w_hour = w_hour
    client.state.w_minute = w_minute
    client.state.w_second = w_second
    client.state.w_millisecond = w_millisecond
    client.state.w_system_time = w_systemtime
    client.state.w_system_time_desc = system_time_str
    client.state.initial_time_dt = initial_time_dt
    client.state.received_at = received_at
    # logger.info(f"[RECV] TimeDateRes Date: {w_month}/{w_day}/{w_year}, DayOfWeek: {day_name} ({w_day_of_week}), Time: {w_hour}:{w_minute}:{w_second}.{w_millisecond}, SystemTime: {system_time_str}")
    logger.info(f"({client.state.device_name}) [RECV] TimeDateRes")

    client.state.is_registered.set()

