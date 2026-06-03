import socket
import time

import pytest
import tftpy

from simulator.tftp_config import build_sep_config, build_xml_default
from simulator.tftp_service import TftpConfigService
from simulator.registry import DeviceRegistry
from utils.tftp import get_device_config_via_tftp


def test_build_xml_default_contains_cm_host():
    xml = build_xml_default("10.0.0.50", skinny_port=2000)
    assert "10.0.0.50" in xml
    assert "<ethernetPhonePort>2000</ethernetPhonePort>" in xml


def test_build_sep_config_includes_dn():
    xml = build_sep_config("SEP222233334444", "1003", "127.0.0.1")
    assert "1003" in xml
    assert "127.0.0.1" in xml
    assert "<featureID>9</featureID>" in xml


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def tftp_service():
    reg = DeviceRegistry(dn_start=3000)
    svc = TftpConfigService(
        reg,
        "127.0.0.1",
        skinny_port=2000,
        listen_host="127.0.0.1",
        listen_port=_free_udp_port(),
    )
    svc.start(background=True)
    time.sleep(0.3)
    port = svc.bound_port
    yield svc, port
    svc.stop()


def test_tftp_dynamic_sep_file(tftp_service):
    svc, port = tftp_service
    client = tftpy.TftpClient("127.0.0.1", port)
    import tempfile

    dest = tempfile.mktemp(suffix=".cnf.xml")
    client.download("SEPAAAABBBBCCCC.cnf.xml", dest, timeout=5)
    body = open(dest, encoding="utf-8").read()
    assert "127.0.0.1" in body
    assert "3000" in body
    assert reg_get(svc, "SEPAAAABBBBCCCC") == "3000"


def reg_get(svc, name):
    return svc.registry.get(name)


def test_get_device_config_via_tftp_helper(tftp_service):
    _svc, port = tftp_service
    text = get_device_config_via_tftp("127.0.0.1", "SEP111122223333", port=port)
    assert text
    assert "processNodeName" in text
