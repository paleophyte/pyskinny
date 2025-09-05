import struct
from dispatcher import register_handler
import logging
logger = logging.getLogger(__name__)


def send_keepalive_req(client):
    msg_id = 0x0000
    header = struct.pack("<I I I", 4, 0, msg_id)
    try:
        logging.info(f"({client.state.device_name}) [SEND] KeepAliveReq")
        client.sock.sendall(header)
    except Exception as e:
        client.state.is_unregistered.set()
        client.running = False
        logging.info(f"({client.state.device_name}) [SEND] KeepAliveReq ERROR: {e}")


@register_handler(0x0100, "KeepAliveAck")
def parse_keep_alive_ack(client, payload):
    logging.info(f"({client.state.device_name}) [RECV] KeepAliveAck")
