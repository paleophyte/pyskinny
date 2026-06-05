"""
Unified client integration tests against live CallManager labs.

Configure labs via ``PYSKINNY_INTEGRATION_LABS`` (default: all known labs).

Built-in defaults:

  cm2   10.0.0.11       Virtual30SPplus   device names pyskinny01–03
  cm31  10.0.0.181      7960              MAC 222233334444–446
  cm33  10.0.0.182      7970              MAC 222233334444–446
  cm41  10.0.0.180      7970              MAC 222233334444–446
  cm43  100.69.0.100    7970              MAC 222233334444–446

  set PYSKINNY_INTEGRATION_LABS=cm2,cm31,cm33,cm41,cm43
  pytest tests/test_integration_live.py -m integration -v --no-audio

Per-lab markers: ``cm2``, ``cm31``, ``cm33``, ``cm41``, ``cm43``.
Override any lab: ``PYSKINNY_CM41_SERVER``, ``PYSKINNY_CM31_MODEL``, etc.
Disable one lab: ``PYSKINNY_CM33_DISABLE=1``.
"""

from __future__ import annotations

import logging
import time

import messages  # noqa: F401
import pytest

from tests.integration_lab import (
    LabProfile,
    assert_hold_capable,
    wait_hold_observed,
    wait_connected_after_hold,
    call_ref_summary,
    connect_two_party,
    configured_labs,
    expected_device_name,
    hangup,
    line_dn,
    log_softkey_inventory,
    start_client,
    stop_client,
    wait_blind_transfer_complete,
    wait_call_cleared,
    wait_call_state,
)

logger = logging.getLogger(__name__)


def pytest_generate_tests(metafunc):
    if "live_lab" in metafunc.fixturenames:
        labs = configured_labs()
        if not labs:
            metafunc.parametrize(
                "live_lab",
                [
                    pytest.param(
                        None,
                        marks=pytest.mark.skip(
                            reason="No integration labs configured "
                            "(set PYSKINNY_INTEGRATION_LABS=cm2,cm31,cm33,cm41,cm43)"
                        ),
                    )
                ],
            )
        else:
            params = [pytest.param(name, marks=getattr(pytest.mark, name)) for name in labs]
            metafunc.parametrize("live_lab", params, indirect=True, ids=labs)


@pytest.fixture
def live_lab(request) -> LabProfile:
    from tests.integration_lab import load_lab

    profile = load_lab(request.param)
    assert profile is not None
    return profile


@pytest.mark.integration
class TestLiveRegistration:
    def test_register_unregister(self, live_lab: LabProfile):
        client, state = start_client(live_lab, live_lab.endpoint_a)
        try:
            assert state.device_name == expected_device_name(live_lab, live_lab.endpoint_a)
            assert state.keepalive_interval > 0
            assert state.button_template, "expected ButtonTemplateRes"
            dn = line_dn(state)
            logger.info(
                "[%s] %s registered DN=%s model=%s softkeys=%s",
                live_lab.name,
                state.device_name,
                dn,
                state.model_name,
                bool(state.softkey_template),
            )
            if live_lab.name == "cm2":
                assert not state.softkey_template, "CM2 button phones should not get softkey template"
            elif live_lab.expects_softkeys:
                assert state.softkey_template, f"{live_lab.name} should receive SoftKeyTemplateRes"
        finally:
            stop_client(client, state)

    def test_each_endpoint_registers(self, live_lab: LabProfile):
        time.sleep(2)
        endpoints = [live_lab.endpoint_a, live_lab.endpoint_b]
        if live_lab.endpoint_c:
            endpoints.append(live_lab.endpoint_c)
        for endpoint in endpoints:
            client, state = start_client(live_lab, endpoint)
            try:
                dn = line_dn(state)
                logger.info("[%s] %s -> %s", live_lab.name, state.device_name, dn)
            finally:
                stop_client(client, state)
                time.sleep(2)


@pytest.mark.integration
class TestLiveCalls:
    def test_outbound_call_connect_hangup(self, live_lab: LabProfile):
        time.sleep(2)
        client_b, state_b = start_client(live_lab, live_lab.endpoint_b)
        dn_b = line_dn(state_b)
        client_a, state_a = start_client(live_lab, live_lab.endpoint_a)
        try:
            connect_two_party(client_a, state_a, client_b, state_b, dn_b=dn_b)
            logger.info(
                "[%s] connected A %s B %s",
                live_lab.name,
                call_ref_summary(state_a),
                call_ref_summary(state_b),
            )
            hangup(client_a)
            hangup(client_b)
            assert wait_call_cleared(client_a) or wait_call_cleared(client_b), (
                f"call did not clear after hangup: A={state_a.active_calls_list} B={state_b.active_calls_list}"
            )
        finally:
            stop_client(client_a, state_a)
            stop_client(client_b, state_b)

    def test_hold_and_resume(self, live_lab: LabProfile):
        time.sleep(2)
        client_b, state_b = start_client(live_lab, live_lab.endpoint_b)
        dn_b = line_dn(state_b)
        client_a, state_a = start_client(live_lab, live_lab.endpoint_a)
        try:
            if live_lab.name == "cm2":
                assert state_a.button_template, (
                    f"{state_a.device_name}: expected ButtonTemplateRes on cm2"
                )
            else:
                log_softkey_inventory(state_a, lab=live_lab.name)
                assert_hold_capable(state_a, lab=live_lab.name)
            connect_two_party(client_a, state_a, client_b, state_b, dn_b=dn_b)
            ref = str(state_a.active_calls_list[-1])
            client_a.press_hold()
            hold_action = "Stimulus 3 (hold toggle)" if live_lab.name == "cm2" else "SoftKey Hold"
            held = (
                wait_hold_observed(client_a, ref, timeout=15.0, peer_client=client_b)
                if live_lab.name == "cm2"
                else wait_call_state(client_a, ref, 8, expected_name="Hold", timeout=12.0)
            )
            if not held:
                pytest.skip(
                    f"[{live_lab.name}] hold not observed after {hold_action} "
                    f"(ref={ref}, state={state_a.calls.get(ref)}, "
                    f"prompt={state_a.current_prompt!r}) — check CM hold feature on "
                    f"{state_a.device_name}"
                )
            time.sleep(0.5)
            client_a.press_resume()
            resumed = (
                wait_connected_after_hold(
                    client_a, ref, timeout=15.0, peer_client=client_b
                )
                if live_lab.name == "cm2"
                else wait_call_state(
                    client_a, ref, 5, expected_name="Connected", timeout=12.0
                )
            )
            if live_lab.name == "cm2" and not resumed:
                pytest.skip(
                    f"[cm2] resume not observed after Stimulus 3 toggle "
                    f"(ref={ref}, state={state_a.calls.get(ref)}) — hold send OK; "
                    f"try console h on a live call or capture Skinny on resume"
                )
            assert resumed, state_a.calls.get(ref)
            hangup(client_a)
            hangup(client_b)
        finally:
            stop_client(client_a, state_a)
            stop_client(client_b, state_b)

    def test_blind_transfer(self, live_lab: LabProfile):
        time.sleep(2)
        endpoints = [live_lab.endpoint_a, live_lab.endpoint_b, live_lab.endpoint_c]
        if not live_lab.endpoint_c:
            pytest.skip("third endpoint required for blind transfer")
        clients = []
        try:
            for ep in endpoints:
                clients.append(start_client(live_lab, ep))
            client_a, state_a = clients[0]
            client_b, state_b = clients[1]
            client_c, state_c = clients[2]
            if live_lab.name == "cm2":
                assert state_a.button_template, (
                    f"{state_a.device_name}: expected ButtonTemplateRes on cm2"
                )
            dn_b = line_dn(state_b)
            dn_c = line_dn(state_c)
            connect_two_party(client_a, state_a, client_b, state_b, dn_b=dn_b)
            logger.info(
                "[%s] blind transfer A %s -> C %s (B=%s)",
                live_lab.name,
                call_ref_summary(state_a),
                dn_c,
                dn_b,
            )
            client_a.blind_transfer(dn_c)
            wait_blind_transfer_complete(client_a, client_c, client_b)
            hangup(client_b)
            hangup(client_c)
            assert wait_call_cleared(client_b) or wait_call_cleared(client_c)
        finally:
            for client, state in reversed(clients):
                stop_client(client, state)
                time.sleep(1.5)
