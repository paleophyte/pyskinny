"""Per-phone Skinny session state machine."""

from __future__ import annotations

import logging
import socket

from simulator import payloads
from simulator.protocol import parse_register_req, read_message
from simulator.registry import DeviceRegistry
from simulator.tftp_service import TftpConfigService

logger = logging.getLogger(__name__)

# Client -> server message IDs handled during registration
MSG_REGISTER_REQ = 0x0001
MSG_IP_PORT = 0x0002
MSG_KEEPALIVE = 0x0000
MSG_CAPABILITIES_RES = 0x0010
MSG_BUTTON_TEMPLATE_REQ = 0x000E
MSG_SOFTKEY_TEMPLATE_REQ = 0x0028
MSG_SOFTKEY_SET_REQ = 0x0025
MSG_CONFIG_STAT_REQ = 0x000C
MSG_LINE_STAT_REQ = 0x000B
MSG_SPEED_DIAL_STAT_REQ = 0x000A
MSG_FORWARD_STAT_REQ = 0x0009
MSG_REGISTER_AVAILABLE_LINES = 0x002D
MSG_TIME_DATE_REQ = 0x000D
MSG_UNREGISTER_REQ = 0x0027


class SkinnySession:
    def __init__(
        self,
        conn: socket.socket,
        addr: tuple,
        registry: DeviceRegistry,
        server_name: str,
        tftp: TftpConfigService | None = None,
    ):
        self.conn = conn
        self.addr = addr
        self.registry = registry
        self.server_name = server_name
        self.tftp = tftp
        self.device_name = ""
        self.directory_number = ""
        self._registered = False
        self._lines = 1

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

    def _send(self, packet: bytes) -> None:
        self.conn.sendall(packet)

    def _send_many(self, packets: list[bytes]) -> None:
        for packet in packets:
            self._send(packet)

    def _handle(self, msg_id: int, payload: bytes) -> bool:
        if msg_id == MSG_REGISTER_REQ:
            return self._on_register(payload)
        if msg_id == MSG_IP_PORT:
            return True
        if msg_id == MSG_KEEPALIVE:
            self._send(payloads.keepalive_ack())
            return True
        if msg_id == MSG_UNREGISTER_REQ:
            self._send(payloads.unregister_ack(0))
            return False
        if not self.device_name:
            logger.debug("Ignoring msg 0x%04X before registration from %s", msg_id, self.addr)
            return True

        if msg_id == MSG_CAPABILITIES_RES:
            return True
        if msg_id == MSG_BUTTON_TEMPLATE_REQ:
            self._send(payloads.button_template_res())
            return True
        if msg_id == MSG_SOFTKEY_TEMPLATE_REQ:
            self._send(payloads.softkey_template_res())
            return True
        if msg_id == MSG_SOFTKEY_SET_REQ:
            self._send(payloads.softkey_set_res())
            return True
        if msg_id == MSG_CONFIG_STAT_REQ:
            self._send(
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
            self._send(payloads.line_stat_res(line, self.directory_number))
            return True
        if msg_id == MSG_FORWARD_STAT_REQ:
            line = self._read_u32(payload, default=1)
            self._send(payloads.forward_stat_res(line))
            return True
        if msg_id == MSG_SPEED_DIAL_STAT_REQ:
            sd = self._read_u32(payload, default=1)
            self._send(payloads.speed_dial_stat_res(sd))
            return True
        if msg_id == MSG_REGISTER_AVAILABLE_LINES:
            if len(payload) >= 4:
                self._lines = max(1, self._read_u32(payload))
            return True
        if msg_id == MSG_TIME_DATE_REQ:
            self._finish_registration()
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
        self.directory_number = self.registry.assign(self.device_name)
        if self.tftp:
            self.tftp.write_device_config(self.device_name, self.directory_number)
        logger.info(
            "Register %s from %s -> DN %s (type=0x%x, ip=%s)",
            self.device_name,
            self.addr[0],
            self.directory_number,
            info.device_type,
            info.station_ip,
        )
        self._send(payloads.register_ack())
        self._send(payloads.capabilities_req())
        return True

    def _finish_registration(self) -> None:
        self._send(payloads.time_date_res())
        self._send(payloads.display_prompt_status("Ready"))
        self._send(payloads.select_soft_keys())
        self._registered = True
        logger.info(
            "(%s) registration complete — DN %s",
            self.device_name,
            self.directory_number,
        )

    @staticmethod
    def _read_u32(payload: bytes, default: int = 0) -> int:
        if len(payload) < 4:
            return default
        import struct

        return struct.unpack("<I", payload[:4])[0]
