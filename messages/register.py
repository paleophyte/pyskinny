import struct
from utils.client import get_local_ip, ip_to_int, clean_bytes
from messages.generic import UNREGISTER_STATUS_NAMES
from dispatcher import register_handler
from messages.generic import send_skinny_message
import time
import logging
logger = logging.getLogger(__name__)


@register_handler(0x0001, "RegisterReq")
def send_register_req(state):
    # SCCP header
    msg_id = 0x0001
    # Will be calculated from payload length; pad for now
    data_length = 68
    header_version = 0

    # Your values
    device_name = state.device_name.encode("ascii")[:15].ljust(16, b"\x00")
    reserved = 0
    instance = 0
    call_manager_host_ip = get_local_ip(state.server)
    station_ip = ip_to_int(call_manager_host_ip)
    logger.info(f"({state.device_name}) Client IP: {call_manager_host_ip}")
    state.client_ip = call_manager_host_ip
    device_type = state.model
    max_rtp_streams = 5
    active_rtp_streams = 1
    protocol_version = 5
    unknown = 0

    # Feature bits → 2-byte bitfield
    # Manually pack into a 16-bit int (little endian)
    # bit1 = 0, bit2 = 0, ..., bit6 = 1, bit7 = 1, ..., bit11 = 1
    feature_flags = (
        (0 << 0) | (0 << 1) | (0 << 2) | (0 << 3) |
        (0 << 4) | (1 << 5) | (1 << 6) | (0 << 7) |
        (1 << 8) | (0 << 9) | (1 << 10) | (0 << 11) |
        (0 << 12) | (0 << 13) | (0 << 14) | (0 << 15)
    )

    max_conferences = 4294467296  # 0xFFFFFEE0

    station_ip_packed = struct.pack("!I", station_ip)  # Big-endian (network byte order)
    payload = struct.pack(
        "<I I I 16s I I",  # up to but not including station_ip
        data_length,
        header_version,
        msg_id,
        device_name,
        reserved,
        instance,
    )
    payload += station_ip_packed
    payload += struct.pack(
        "<I I I B B H I",
        device_type,
        max_rtp_streams,
        active_rtp_streams,
        protocol_version,
        unknown,
        feature_flags,
        max_conferences,
    )
    # Unknown static data from Wireshark capture?
    extra_bytes = bytes.fromhex("ffffffff00000000e082180000000000")

    return payload + extra_bytes


@register_handler(0x0081, "RegisterAck")
def parse_register_ack(client, payload):
    if len(payload) < 20:
        logger.warning(f"({client.state.device_name}) RegisterAck payload too short")
        return

    keepalive = struct.unpack("<I", payload[0:4])[0]
    # start_keepalive_timer(client, shared_state, interval=keepalive, log=log, on_disconnect=on_disconnect)
    date_template = payload[4:10].decode("ascii", errors="ignore")
    padding = struct.unpack("<H", payload[10:12])[0]
    second_keepalive = struct.unpack("<I", payload[12:16])[0]
    max_protocol = payload[16]
    unknown = payload[17]
    feature_flags = struct.unpack("<H", payload[18:20])[0]

    client.state.keepalive_interval = keepalive
    client.state.second_keepalive_interval = second_keepalive
    client.state.date_template = date_template
    client.state.feature_flags = feature_flags
    client.state.feature_flag_str = f"{feature_flags:016b}"

    # logger.info(f"[REGISTER_ACK] KeepAlive: {keepalive}s, SecondKA: {second_keepalive}s, DateFmt: {date_template}, Features: {feature_flags:016b}")
    logger.info(f"({client.state.device_name}) [RECV] RegisterAck")


@register_handler(0x0027, "UnregisterReq")
def send_unregister_req(client):
    if client.state.active_call:
        logger.warning(f"({client.state.device_name}) Attempting to Unregister with active call. Ending Call first.")
        client.press_softkey("EndCall")
        time.sleep(0.5)
        logger.warning(f"({client.state.device_name}) Now attempting to Unregister...")

    send_skinny_message(client, 0x0027)


@register_handler(0x0118, "UnregisterAck")
def parse_unregister_ack(client, payload):
    status = struct.unpack("<I", payload[0:4])[0]
    status_name = UNREGISTER_STATUS_NAMES.get(status, "UNKNOWN")

    if status != 0:
        logger.error(f"({client.state.device_name}) [RECV] UnregisterAck Response {status_name} ({status})")

    client.running = False
    client.state.is_unregistered.set()

    # logger.info(f"[RECV] UnregisterAck status: {status_name} ({status})")
    logger.info(f"({client.state.device_name}) [RECV] UnregisterAck")


@register_handler(0x009D, "RegisterReject")
def parse_register_reject(client, payload):
    error_bytes = payload[:32]
    error = clean_bytes(error_bytes)

    logger.error(f"({client.state.device_name}) [RECV] RegisterReject {error}")

    client.running = False
    client.state.is_unregistered.set()
