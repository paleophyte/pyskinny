"""Simulator SimMediaHub."""

from __future__ import annotations

from simulator.media_hub import SimMediaHub


def test_sim_media_hub_modes():
    hub = SimMediaHub("off")
    assert hub.mode == "off"
    hub = SimMediaHub("tone", advertise_ip="10.0.0.1")
    assert hub.mode == "tone"
    assert hub.advertise_ip == "10.0.0.1"
    hub = SimMediaHub("bogus")
    assert hub.mode == "off"


def test_sim_media_hub_start_call_requires_ports():
    hub = SimMediaHub("tone", advertise_ip="127.0.0.1")

    class FakeSession:
        device_name = "SEPA"
        station_ip = "127.0.0.1"

        def send(self, _pkt):
            pass

    caller = FakeSession()
    call = type("Call", (), {
        "call_ref": 1,
        "caller": caller,
        "callee": None,
        "media_ports": {},
    })()
    assert hub.start_call(call) is False
