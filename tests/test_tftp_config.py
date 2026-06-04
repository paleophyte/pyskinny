import socket
import time
from pathlib import Path

import pytest
import tftpy

from simulator.tftp_config import (
    build_sep_config,
    build_xml_default,
    is_cucm_sep_config,
    patch_sep_config_for_sim,
)
from simulator.tftp_service import (
    FALLBACK_TFTP_PORT,
    PRIVILEGED_TFTP_PORT,
    TftpConfigService,
    resolve_tftp_listen_port,
)
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


def test_resolve_tftp_listen_port_non_default():
    assert resolve_tftp_listen_port("0.0.0.0", 50321) == 50321


def test_resolve_tftp_listen_port_fallback(monkeypatch):
    monkeypatch.setattr("simulator.tftp_service.can_bind_udp_port", lambda _h, p: p != PRIVILEGED_TFTP_PORT)
    assert resolve_tftp_listen_port("127.0.0.1", PRIVILEGED_TFTP_PORT) == FALLBACK_TFTP_PORT


def test_resolve_tftp_listen_port_keeps_69_when_bindable(monkeypatch):
    monkeypatch.setattr("simulator.tftp_service.can_bind_udp_port", lambda _h, _p: True)
    assert resolve_tftp_listen_port("127.0.0.1", PRIVILEGED_TFTP_PORT) == PRIVILEGED_TFTP_PORT


def test_tftp_service_fell_back_flag(monkeypatch):
    monkeypatch.setattr("simulator.tftp_service.can_bind_udp_port", lambda _h, p: p != PRIVILEGED_TFTP_PORT)
    reg = DeviceRegistry(dn_start=3000)
    svc = TftpConfigService(reg, "127.0.0.1", listen_port=PRIVILEGED_TFTP_PORT)
    assert svc.listen_port == FALLBACK_TFTP_PORT
    assert svc.fell_back_from_privileged is True


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


def test_patch_cucm_sep_preserves_load_and_adds_line():
    cucm = Path(__file__).resolve().parents[1] / "simulator/tftp_assets/SEP001380AD9E5F.cnf.xml"
    if not cucm.is_file():
        pytest.skip("lab SEP sample not in tree")
    raw = cucm.read_text(encoding="utf-8")
    assert is_cucm_sep_config(raw)
    patched = patch_sep_config_for_sim(
        raw,
        cm_host="10.102.172.11",
        directory_number="1000",
        skinny_port=2000,
        cip_port=8088,
    )
    assert "CP7912060000SCCP050124A" in patched
    assert "<processNodeName>10.102.172.11</processNodeName>" in patched
    assert "http://10.102.172.11:8088/CCMCIP/authenticate.asp" in patched
    assert "<proxyServerURL></proxyServerURL>" in patched
    assert "<webAccess>0</webAccess>" in patched
    assert "<lines>" in patched
    assert "<name>1000</name>" in patched


def test_softkey_set_res_has_fifteen_sets():
    from simulator.payloads import softkey_set_res

    pkt = softkey_set_res()
    assert len(pkt) >= 8 + 12 + 15 * 48
