from scapy.all import sniff, Raw
from scapy.layers.l2 import LLC, Ether, SNAP, sendp
from functools import partial
import requests
import json
import time
import struct
import platform
import socket
import threading
import psutil
from utils.client import hexdump, normalize_mac_address
from enum import IntFlag, auto
# from sccp_utils import clean_bytes, hexdump


MERAKI_LSP_IPS = [
    "10.128.128.126",  # Meraki Wireless AP
    "198.18.0.1",      # MS390 latest firmware
    "10.128.128.130",  # MS390 older firmware
    "1.1.1.100",       # Other MS switches
]


CDP_TLV_TYPES = {
    0x0001: {"description": "Device ID", "name": "device_id"},
    0x0002: {"description": "Address", "name": "address"},
    0x0003: {"description": "Port ID", "name": "port_id"},
    0x0004: {"description": "Capabilities", "name": "capabilities"},
    0x0005: {"description": "Software Version", "name": "software_version"},
    0x0006: {"description": "Platform", "name": "platform"},
    0x0008: {"description": "VTP Management Domain"},
    0x000a: {"description": "Native VLAN", "name": "native_vlan"},
    0x000b: {"description": "Duplex"},
    0x0016: {"description": "Management Address", "name": "mgmt_address"},
    0x001a: {"description": "Power", "name": "power"},
}


class CDPCapability(IntFlag):
    ROUTER = 0x01
    TRANSPARENT_BRIDGE = 0x02
    SOURCE_ROUTE_BRIDGE = 0x04
    SWITCH = 0x08
    HOST = 0x10
    IGMP_CAPABLE = 0x20
    REPEATER = 0x40
    VOIP_PHONE = 0x80
    REMOTELY_MANAGED = 0x100
    CVTA_CAMERA = 0x200
    TWO_PORT_MAC_RELAY = 0x400


LLDP_TLV_TYPES = {
    0: {"description": "End of LLDPDU"},
    1: {"description": "Chassis ID", "name": "chassis_id"},
    2: {"description": "Port ID", "name": "port_id"},
    3: {"description": "Time To Live"},
    4: {"description": "Port Description", "name": "port_desc"},
    5: {"description": "System Name", "name": "system_name"},
    6: {"description": "System Description", "name": "system_desc"},
    7: {"description": "System Capabilities", "name": "capabilities"},
    8: {"description": "Management Address", "name": "mgmt_address"},
}


def hex_to_ip(hex_str):
    if len(hex_str) == 8:
        try:
            return ".".join(str(int(hex_str[i:i+2], 16)) for i in range(0, 8, 2))
        except ValueError:
            return hex_str
    return hex_str


def find_interface_for_target_ip(target_ip):
    def get_first_physical_mac():
        for fallback_iface, fallback_addrs in psutil.net_if_addrs().items():
            for addr in fallback_addrs:
                if addr.family == psutil.AF_LINK and addr.address:
                    mac = addr.address
                    # Basic sanity check: avoid all-zero MACs
                    if mac and not mac.startswith("00:00:00"):
                        return fallback_iface, mac
        return None, None

    try:
        # Step 1: Get the local IP used to reach the target
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_ip, 12345))  # doesn't send packets
        local_ip = s.getsockname()[0]
        s.close()

        # Step 2: Match local IP to interface
        for iface_name, iface_addrs in psutil.net_if_addrs().items():
            ip_match = False
            mac_address = None

            for addr in iface_addrs:
                if addr.family == socket.AF_INET and addr.address == local_ip:
                    ip_match = True
                elif addr.family == psutil.AF_LINK and addr.address:
                    if not addr.address.startswith("00:00:00"):
                        mac_address = addr.address

            if ip_match:
                if mac_address:
                    return iface_name, local_ip, mac_address
                else:
                    # No MAC on this interface, fall back
                    fallback_iface, fallback_mac = get_first_physical_mac()
                    return iface_name, local_ip, fallback_mac

        # Couldn’t find matching interface for IP, fallback
        fallback_iface, fallback_mac = get_first_physical_mac()
        return fallback_iface, local_ip, fallback_mac

    except Exception as e:
        return None, None, f"Error: {e}"


def parse_cdp_ip(data):
    try:
        if len(data) < 12:
            return "Invalid CDP IP format"

        # First 4 bytes = address count (usually 1, skip)
        addr_count = struct.unpack("!I", data[0:4])[0]
        if addr_count != 1:
            return f"Unsupported address count: {addr_count}"

        protocol_type = data[4]
        protocol_length = data[5]

        # Make sure we have enough bytes
        if len(data) < 8 + protocol_length + 2:
            return "Invalid CDP IP format"

        # Protocol field (typically 1 byte for IPv4)
        protocol = data[6:6 + protocol_length]
        address_length = struct.unpack("!H", data[6 + protocol_length : 8 + protocol_length])[0]
        address = data[8 + protocol_length : 8 + protocol_length + address_length]

        if protocol_type == 0x01 and protocol == b'\xcc' and address_length == 4:
            return ".".join(str(b) for b in address)

        return f"Unsupported protocol or address length"
    except Exception as e:
        return f"Error parsing CDP IP: {e}"



def parse_lldp_ip(data):
    try:
        if len(data) >= 6 and data[1] == 0x01:  # IPv4
            ip_bytes = data[2:6]
            return ".".join(str(b) for b in ip_bytes)
    except Exception as e:
        return f"Error parsing LLDP IP: {e}"
    return "Invalid LLDP IP format"


def smart_decode_or_hex(value: bytes) -> str:
    try:
        decoded = value.decode(errors="ignore").strip()
        if decoded and decoded.isprintable():
            return decoded
    except Exception:
        pass
    # Fallback: return hex string
    return value.hex()


def decode_cdp_capabilities(value: bytes) -> tuple:
    if not value:
        return "None", []

    cap_val = int.from_bytes(value, byteorder='big')
    # caps = [desc for bit, desc in CDP_CAPABILITIES_TYPES.items() if cap_val & bit]
    caps = [cap.name for cap in CDPCapability if cap & cap_val]
    return ", ".join(caps) if caps else f"Unknown Capabilities: {cap_val:#x}", caps


def handle_cdp_packet(pkt, client=None):
    if pkt.haslayer(LLC) and pkt.haslayer(Raw):
        if pkt.dst == "01:00:0c:cc:cc:cc":
            payload = bytes(pkt[Raw])
            client.logger.debug("[TOPOLOGY] CDP Packet Received:")
            # log(hexdump(payload))
            parse_cdp_tlvs(payload, client=client)


def parse_cdp_tlvs(payload, client=None):
    if len(payload) < 4:
        client.logger.warning("[TOPOLOGY] CDP packet too short")
        return

    if "cdp" not in client.state.topology:
        client.state.topology["cdp"] = {}

    version, ttl, checksum = struct.unpack("!BBH", payload[:4])
    if version in (1, 2):
        client.logger.debug(f"[TOPOLOGY] CDP Version: {version}, TTL: {ttl}, Checksum: {checksum:#04x}")

        offset = 4
        while offset + 4 <= len(payload):
            tlv_type, tlv_len = struct.unpack("!HH", payload[offset:offset+4])
            if tlv_len < 4 or offset + tlv_len > len(payload):
                client.logger.warning("[TOPOLOGY] CDP Malformed TLV or truncated packet")
                break

            value = payload[offset+4:offset+tlv_len]
            tlv_name = CDP_TLV_TYPES.get(tlv_type, {}).get("description", f"Unknown TLV ({tlv_type:#04x})")
            tlv_state_field = CDP_TLV_TYPES.get(tlv_type, {}).get("name")

            share_value = None
            if tlv_type == 0x0004:  # Capabilities
                content, cap_list = decode_cdp_capabilities(value)
                share_value = cap_list
            elif tlv_type == 0x0002 or tlv_type == 0x0016:
                content = parse_cdp_ip(value)
                share_value = content
            else:
                content = smart_decode_or_hex(value)
                share_value = content

            if tlv_state_field:
                client.state.topology["cdp"][tlv_state_field] = share_value

            client.logger.debug(f"[TOPOLOGY] CDP {tlv_name} (type {tlv_type:#04x}): {content}")
            offset += tlv_len
    else:
        client.logger.warning(f"[TOPOLOGY] Skipping unknown CDP Version: {version}, TTL: {ttl}, Checksum: {checksum:#04x}")


def cdp_sniffer(client):
    client.logger.info(f"[TOPOLOGY] Starting CDP sniffer")

    sniff(
        filter="ether dst 01:00:0c:cc:cc:cc",
        prn=partial(handle_cdp_packet, client=client),
        store=0,
        promisc=True
    )


def parse_lldp_tlvs(payload, client=None):
    offset = 0

    if "lldp" not in client.state.topology:
        client.state.topology["lldp"] = {}

    while offset + 2 <= len(payload):
        # Read 2-byte TLV header
        tlv_header = struct.unpack("!H", payload[offset:offset+2])[0]
        tlv_type = (tlv_header >> 9) & 0x7F
        tlv_len = tlv_header & 0x1FF
        offset += 2

        if tlv_type == 0:  # End of LLDPDU
            client.logger.debug("[TOPOLOGY] LLDP End of LLDPDU")
            break

        if offset + tlv_len > len(payload):
            client.logger.warning("[TOPOLOGY] LLDP Malformed TLV (too short)")
            break

        value = payload[offset:offset+tlv_len]
        tlv_name = LLDP_TLV_TYPES.get(tlv_type, {}).get("description", f"LLDP TLV ({tlv_type})")
        tlv_state_field = LLDP_TLV_TYPES.get(tlv_type, {}).get("name")

        # if tlv_type in [8]:
        #     content = parse_lldp_ip(value)
        # else:
        #     content = smart_decode_or_hex(value)

        # Handle special TLVs with subtypes
        if tlv_type in (1, 2):  # Chassis ID or Port ID
            if len(value) < 2:
                content = "<invalid subtype>"
            else:
                subtype = value[0]
                subtype_value = value[1:]

                # Try to decode port/chassis info
                if subtype in (3, 4):  # MAC address or IP
                    content = ":".join(f"{b:02x}" for b in subtype_value)
                else:
                    try:
                        content = subtype_value.decode("utf-8").strip()
                    except Exception:
                        content = subtype_value.hex()

                content = f"({subtype}) {content}"

        elif tlv_type in (8,):  # Management Address
            content = parse_lldp_ip(value)

        else:
            content = smart_decode_or_hex(value)

        if tlv_state_field:
            client.state.topology["lldp"][tlv_state_field] = content

        client.logger.debug(f"[TOPOLOGY] LLDP {tlv_name} (type {tlv_type}): {content}")
        offset += tlv_len


def handle_lldp_packet(pkt, client=None):
    if pkt.haslayer(Ether) and pkt[Ether].type == 0x88cc:
        payload = bytes(pkt[Raw]) if pkt.haslayer(Raw) else None
        if not payload:
            client.logger.warning("[TOPOLOGY] LLDP packet missing payload.")
            return
        client.logger.debug("[TOPOLOGY] LLDP Packet Received:")
        parse_lldp_tlvs(payload, client=client)


def lldp_sniffer(client):
    client.logger.info(f"[TOPOLOGY] Starting LLDP sniffer")

    sniff(
        filter="ether proto 0x88cc",
        prn=lambda pkt: handle_lldp_packet(pkt, client=client),
        store=0,
        promisc=True
    )


def poll_meraki_lsp(interval=60, max_initial_failures=3, client=None):
    if client is None:
        state = {}

    failure_counts = {ip: 0 for ip in MERAKI_LSP_IPS}
    success_flags = {ip: False for ip in MERAKI_LSP_IPS}

    while True:
        for ip in MERAKI_LSP_IPS:
            url = f"http://{ip}/index.json"

            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        cfg = data.get('config', {})
                        node_name = cfg.get('node_name', '')
                        product_model = cfg.get('product_model', '')
                        if node_name and product_model:
                            if not success_flags[ip]:
                                client.logger.info(f"[TOPOLOGY] Detected Meraki LSP at {ip}.")
                                success_flags[ip] = True

                            # Store under topology -> meraki -> by IP
                            if "meraki" not in client.state.topology:
                                client.state.topology["meraki"] = {}
                            client.state.topology["meraki"][ip] = data

                            client.logger.debug(f"[TOPOLOGY] Connected AP: {node_name} ({product_model}) at {ip}")
                        else:
                            client.logger.debug(f"[TOPOLOGY] No device info at {ip}.")
                    except json.JSONDecodeError:
                        client.logger.debug(f"[TOPOLOGY] Invalid JSON at {ip}.")
                else:
                    client.logger.debug(f"[TOPOLOGY] HTTP {response.status_code} from {ip}.")
                    if not success_flags[ip]:
                        failure_counts[ip] += 1
            except requests.RequestException as e:
                client.logger.debug(f"[TOPOLOGY] Request error from {ip}: {e}")
                if not success_flags[ip]:
                    failure_counts[ip] += 1

            if not success_flags[ip] and failure_counts[ip] >= max_initial_failures:
                client.logger.debug(f"[TOPOLOGY] Giving up on {ip} after {max_initial_failures} failures.")
                # Stop checking this IP again
                success_flags[ip] = "failed"

        # Break the loop if all devices are marked either success or failed
        if all(v is not False for v in success_flags.values()):
            client.logger.debug("[TOPOLOGY] All Meraki LSP targets reached or failed. Exiting polling loop.")
            break

        time.sleep(interval)


def summarize_meraki_status(meraki_data, log):
    try:
        for ip, data in meraki_data.items():
            config = data.get("config", {})
            conn = data.get("connection_state", {})
            client = data.get("client", {})

            node_name = config.get("node_name", "Unknown")
            product_model = config.get("product_model", "Unknown")
            network_name = config.get("network_name", "Unknown")
            mgmt_ip = conn.get("wired_ip") or client.get("ip") or ip
            client_ip = client.get("ip", "Unknown")

            log("\nMeraki Local Status Page:")
            log(f"Model:       {product_model}")
            log(f"Name:        {node_name}")
            log(f"Network:     {network_name}")
            log(f"Mgmt IP:     {mgmt_ip}")
            log(f"Client IP:   {client_ip}")

            if config.get("iswireless"):
                log(f"Radio:       {client.get('band', '')} / Ch {client.get('channel', '')} ({client.get('wireless_mode', '')})")
                log(f"RSSI:        {client.get('rssi', '')} dBm")
                # log(f"Uplink:      {conn.get('eth_speed', '')} {conn.get('eth_duplex', '').title()}")
            elif config.get("isswitch"):
                log(f"Port:        {client.get('port', '')}")
                log(f"VLAN:        {client.get('vlan', '')}")

        # log(f"Tunnel:      {conn.get('tunnel_address', '')}")
    except Exception as e:
        log(f"[ERROR] Failed to summarize Meraki status: {e}")


def build_cdp_tlv(tlv_type, value_bytes):
    length = len(value_bytes) + 4
    return struct.pack("!HH", tlv_type, length) + value_bytes


def calculate_cdp_checksum(data: bytes) -> int:
    checksum = 0
    if len(data) % 2 == 1:
        data += b"\x00"
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        checksum += word
    while checksum >> 16:
        checksum = (checksum & 0xFFFF) + (checksum >> 16)
    checksum = ~checksum & 0xFFFF
    return checksum


def in_cksum_cdp(data: bytes) -> int:
    sum_words = 0
    data_length = len(data)
    i = 0

    if data_length % 2 == 0:
        while i < data_length:
            sum_words += (data[i] << 8) + data[i + 1]
            i += 2
    else:
        padded_buffer = bytearray(data_length + 1)
        padded_buffer[:data_length] = data
        padded_buffer[data_length] = padded_buffer[data_length - 1]
        padded_buffer[data_length - 1] = 0
        if padded_buffer[data_length] & 0x80:
            padded_buffer[data_length] -= 1
            if padded_buffer[data_length - 1] > 0:
                padded_buffer[data_length - 1] -= 1
            else:
                padded_buffer[data_length - 1] = 0xFF  # Wireshark’s adjustment
        while i < data_length + 1:
            sum_words += (padded_buffer[i] << 8) + padded_buffer[i + 1]
            i += 2

    while sum_words >> 16:
        sum_words = (sum_words & 0xFFFF) + (sum_words >> 16)

    return (~sum_words & 0xFFFF)


def build_cdp_address_tlv(ip_address):
    ip_bytes = socket.inet_aton(ip_address)
    addr = (
            b"\x00\x00\x00\x01"  # number of addresses = 1
            + b"\x01"  # protocol type = NLPID
            + b"\x01"  # protocol length
            + b"\xCC"  # protocol = SNAP
            + b"\x00\x04"  # address length = 4
            + ip_bytes  # IP address
    )
    return build_cdp_tlv(0x0002, addr)


def build_cdp_management_address(ip_address):
    ip_bytes = socket.inet_aton(ip_address)
    return (
        build_cdp_tlv(0x0016,
                      b"\x00\x00\x00\x01"  # count
                      + b"\x01"  # NLPID
                      + b"\x01"  # length
                      + b"\xCC"  # protocol SNAP
                      + b"\x00\x04"  # address length
                      + ip_bytes  # IP
                      )
    )


def compute_cdp_pre_checksum(data):
    odd_length = len(data) % 2 != 0
    pad_byte = None
    if odd_length:
        pad_byte = data[-1]
        data += b'\x00'

    checksum = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i+1]
        checksum += word
        checksum = (checksum & 0xFFFF) + (checksum >> 16)

    checksum = ~checksum & 0xFFFF

    # Cisco-specific odd-length fix
    if odd_length:
        if pad_byte >= 0x80:
            checksum = 0xFF00
        else:
            checksum = 0x0000

    return checksum


def build_cdp_packet(client):
    device_id = client.state.device_name
    client_ip = client.state.client_ip
    platform_str = platform.platform()
    port_id = client.state.interface

    # Build payload without Management Address TLV
    payload = b""
    payload += build_cdp_tlv(0x0001, device_id.encode())
    payload += build_cdp_address_tlv(client_ip)
    payload += build_cdp_tlv(0x0003, port_id.encode())
    payload += build_cdp_tlv(0x0004, struct.pack(">I", CDPCapability.HOST | CDPCapability.VOIP_PHONE))
    payload += build_cdp_tlv(0x0005, b"Python SCCP Client v0.1")
    payload += build_cdp_tlv(0x0006, platform_str.encode())
    payload += build_cdp_management_address(client_ip)

    # Construct full CDP packet with 0 checksum
    header = struct.pack("!BBH", 2, 180, 0x0000)        #compute_cdp_pre_checksum(payload)
    cdp_packet = bytearray(header + payload)

    # Compute checksum
    checksum = in_cksum_cdp(bytes(cdp_packet))
    # print(f"Calculated checksum: 0x{checksum:04x}")

    # Inject checksum into the packet
    header = struct.pack("!BBH", 2, 180, checksum)
    cdp_packet = header + payload

    return bytes(cdp_packet)


def send_cdp_frame(client):
    cdp = build_cdp_packet(client)
    iface = client.state.interface
    mac = client.state.interface_mac
    eth_len = len(cdp) + 8  # 3 bytes for LLC + 5 bytes for SNAP

    frame = (
        Ether(dst="01:00:0C:CC:CC:CC", src=mac) /
        LLC(dsap=0xAA, ssap=0xAA, ctrl=0x03) /
        SNAP(OUI=0x00000C, code=0x2000) /
        cdp
    )
    frame.len = eth_len
    sendp(frame, iface=iface, verbose=False)


def lldp_tlv(tlv_type, value_bytes):
    length = len(value_bytes)
    header = ((tlv_type & 0x7F) << 9) | (length & 0x1FF)
    return struct.pack("!H", header) + value_bytes


def build_lldp_packet(client):
    device_name = client.state.device_name
    client_ip = client.state.client_ip
    system_name = platform.node()
    system_desc = platform.platform()
    iface = client.state.interface
    mac = normalize_mac_address(client.state.interface_mac)
    mac_bytes = bytes.fromhex(mac)

    payload = b""

    # Chassis ID TLV (type 1), subtype 4 = MAC address
    payload += lldp_tlv(1, b"\x04" + mac_bytes)

    # Port ID TLV (type 2), subtype 5 = interface name
    payload += lldp_tlv(2, b"\x05" + iface.encode())

    # TTL TLV (type 3)
    payload += lldp_tlv(3, struct.pack("!H", 120))  # 120 seconds TTL

    # System Name TLV (type 5)
    payload += lldp_tlv(5, device_name.encode())

    # System Description TLV (type 6)
    payload += lldp_tlv(6, system_desc.encode())

    # Management Address TLV (type 8)
    ip_bytes = socket.inet_aton(client_ip)
    mgmt_value = (
        b"\x01"                    # IPv4 address length
        + b"\x01"                  # Address subtype (IPv4)
        + ip_bytes                # IP
        + b"\x00"                 # Interface numbering subtype (unknown)
        + b"\x00\x00\x00\x00"     # Interface number (reserved)
        + b"\x00"                 # OID string length
    )
    payload += lldp_tlv(8, mgmt_value)

    # End of LLDPDU TLV (type 0)
    payload += lldp_tlv(0, b"")

    return payload


def send_lldp_frame(client):
    iface = client.state.interface
    lldp = build_lldp_packet(client)
    frame = Ether(dst="01:80:C2:00:00:0E", type=0x88cc) / lldp
    sendp(frame, iface=iface, verbose=False)


def start_topology_timer(client, interval=30):
    def send_keepalive_loop(stop_event):
        last_sent = time.time()

        while not stop_event.is_set():
            time.sleep(1)  # Check every second for better responsiveness

            now = time.time()
            elapsed = now - last_sent

            if elapsed >= interval:
                # try:
                send_cdp_frame(client)
                #     log(f"[TOPOLOGY] Sent CDP packet after {elapsed:.2f}s")
                # except Exception as e:
                #     log(f"[TOPOLOGY] ERROR while sending CDP packet: {e}")

                # try:
                send_lldp_frame(client)
                #     log(f"[TOPOLOGY] Sent LLDP packet after {elapsed:.2f}s")
                # except Exception as e:
                #     log(f"[TOPOLOGY] ERROR while sending LLDP packet: {e}")

                last_sent = time.time()

    stop_keepalive_thread = threading.Event()
    thread = threading.Thread(target=send_keepalive_loop, args=(stop_keepalive_thread, ), daemon=True)
    client.state._topology_thread = thread
    client.state._stop_topology_thread = stop_keepalive_thread
    thread.start()
