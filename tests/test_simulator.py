import struct

import messages  # noqa: F401
import pytest

from client import SCCPClient
from simulator import SkinnySimulator
from simulator.protocol import pack_message, parse_register_req
from simulator.registry import DeviceRegistry
from simulator import payloads
from state import PhoneState


def test_registry_assigns_dns_from_start():
    reg = DeviceRegistry(dn_start=1000)
    assert reg.assign("SEP111122223333") == "1000"
    assert reg.assign("SEP444455556666") == "1001"
    assert reg.assign("SEP111122223333") == "1000"


def test_parse_register_req_device_name():
    body = b"SEPDEADBEEFCAFE\x00".ljust(16, b"\x00")
    body += struct.pack("<II", 0, 0)
    body += struct.pack("!I", 0x0A000001)  # 10.0.0.1
    body += struct.pack("<I", 30006)
    info = parse_register_req(body)
    assert info.device_name == "SEPDEADBEEFCAFE"
    assert info.device_type == 30006


def test_payload_roundtrip_register_ack():
    packet = payloads.register_ack(25)
    _length, _ver, msg_id = struct.unpack("<III", packet[:12])
    assert msg_id == 0x0081


@pytest.fixture
def skinny_sim():
    sim = SkinnySimulator(host="127.0.0.1", port=0, dn_start=2000, server_name="TestSim")
    sim.start(background=True)
    host, port = sim.address
    yield sim, host, port
    sim.stop()


def test_pyskinny_client_registers_against_simulator(skinny_sim):
    sim, host, port = skinny_sim
    state = PhoneState(server=host, mac="AABBCCDDEEFF", model="7970", port=port)
    client = SCCPClient(state)
    client.get_tftp_config = False

    try:
        client.start()
        assert state.is_registered.wait(timeout=20), "client did not reach registered state"
        dn = sim.registry.get(state.device_name)
        assert dn == "2000"
        assert state.lines.get("1", {}).get("line_dir_number") == "2000"
    finally:
        client.stop()
        assert state.is_unregistered.wait(timeout=10)
