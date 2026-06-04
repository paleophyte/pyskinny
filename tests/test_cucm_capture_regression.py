"""Regression tests: simulator Skinny wire format vs CUCM pcaps (cm_cap, cm_call_from_pyskinny_to_7912)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from simulator import payloads
from simulator.call_hub import CallHub, SimCall
from simulator.cucm_legacy_assets import (
    LEGACY_FEATURE_STAT_RES,
    LEGACY_SOFTKEY_SET_RES,
    LEGACY_SOFTKEY_TEMPLATE_RES,
)
from simulator.session import SkinnySession
from tests.cucm_capture import (
    LINE,
    PASS_THROUGH_PARTY_ID,
    REF_INCOMING_CALL,
    REF_NEW_CALL,
    assert_frame,
    assert_packet_equal,
    load_fixture_group,
    msg_id,
    wire_from_hex,
)


class TestLegacyRegistrationAssets:
    def test_softkey_template_res_matches_cm_cap(self):
        wire = wire_from_hex(load_fixture_group("cm_cap_assets")["40"])
        assert_packet_equal(
            wire,
            payloads.normalize_skinny_packet(LEGACY_SOFTKEY_TEMPLATE_RES),
            label="SoftKeyTemplateRes",
            normalize_wire=True,
        )

    def test_softkey_set_res_blob_matches_cm_cap(self):
        wire = wire_from_hex(load_fixture_group("cm_cap_assets")["43"])
        assert_packet_equal(
            wire,
            payloads.normalize_skinny_packet(LEGACY_SOFTKEY_SET_RES),
            label="SoftKeySetRes blob",
            normalize_wire=True,
        )

    def test_feature_stat_res_matches_cm_cap(self):
        assert_frame(
            "cm_cap_assets",
            50,
            payloads.feature_stat_res(legacy=True),
        )

    def test_idle_softkeys_and_display_match_cm_cap(self):
        assert_frame("cm_cap_reg_idle", 45, payloads.legacy_select_softkeys_idle())
        assert_frame("cm_cap_reg_idle", 46, payloads.legacy_display_prompt_idle())

    def test_ready_display_matches_cm_cap(self):
        assert_frame("cm_cap_reg_ready", 63, payloads.legacy_display_prompt_ready())


class TestNewCallOutbound:
    """cm_cap.pcapng frames 80-87 — 7912 New Call / dial tone."""

    @pytest.fixture
    def packets(self):
        session = SkinnySession.__new__(SkinnySession)
        return session._legacy_outbound_packets(LINE, REF_NEW_CALL)

    @pytest.mark.parametrize(
        "frame,index",
        [
            ("80", 0),
            ("81", 1),
            ("82", 2),
            ("83", 3),
            ("84", 4),
            ("85", 5),
            ("86", 6),
            ("87", 7),
        ],
    )
    def test_frame_matches_cucm(self, packets, frame, index):
        assert_frame("cm_cap_new_call", frame, packets[index])


class TestIncomingRingIn:
    """cm_call_from_pyskinny_to_7912.pcapng frames 132-138 (ring-in to 7912)."""

    @staticmethod
    def _ring_packets(caller_dn: str = "1003"):
        ref = REF_INCOMING_CALL
        tail = CallHub._legacy_ring_in_tail(
            SimCall(call_ref=ref, caller=SimpleNamespace(), line=LINE),
        )
        return [
            payloads.call_state(payloads.CALL_STATE_RINGIN, LINE, ref),
            payloads.select_soft_keys(LINE, ref, softkey_set_index=3),
            payloads.legacy_display_text(caller_dn, LINE, ref),
            payloads.display_pri_notify(caller_dn),
            *tail,
        ]

    @pytest.mark.parametrize(
        "frame,index",
        [
            ("132", 0),
            ("133", 1),
            ("134", 2),
            ("135", 3),
            ("137", 4),
            ("138", 5),
        ],
    )
    def test_frame_matches_cucm(self, frame, index):
        assert_frame("cm_call_ring", frame, self._ring_packets()[index])

    def test_ring_tail_reselects_softkeys(self):
        packets = self._ring_packets()
        assert_frame("cm_call_ring", 133, packets[1])
        # Final packet in tail repeats SelectSoftKeys after SetRinger
        assert_frame("cm_call_ring", 133, packets[-1])


class TestAnswerConnect:
    """cm_call_from_pyskinny_to_7912.pcapng frames 141-147, 150-151 — off-hook answer."""

    @pytest.fixture
    def packets(self):
        return CallHub._legacy_callee_connect_packets(
            SimCall(call_ref=REF_INCOMING_CALL, caller=SimpleNamespace(), line=LINE),
            caller_name="Python",
            caller_dn="1003",
            callee_name="SEP001380AD9E5F",
            callee_dn="1000",
        )

    @pytest.mark.parametrize(
        "frame,index",
        [
            ("141", 0),
            ("142", 1),
            ("143", 2),
            ("144", 3),
            ("145", 4),
            ("146", 5),
            ("147", 6),
            ("150", 9),
            ("151", 10),
        ],
    )
    def test_frame_matches_cucm(self, packets, frame, index):
        assert_frame("cm_call_answer", frame, packets[index])

class TestMediaPayloads:
    """cm_call_from_pyskinny_to_7912.pcapng frames 148, 154, 155 — OpenRx / StartMedia / Ack."""

    def test_open_receive_channel_matches_cucm(self):
        assert_frame(
            "cm_call_open_rx",
            148,
            payloads.open_receive_channel(REF_INCOMING_CALL),
        )

    def test_start_media_transmission_matches_cucm(self):
        from tests.cucm_capture import (
            MEDIA_PRECEDENCE,
            MEDIA_REMOTE_IP,
            MEDIA_REMOTE_PORT,
        )

        assert_frame(
            "cm_call_media",
            154,
            payloads.start_media_transmission(
                REF_INCOMING_CALL,
                MEDIA_REMOTE_IP,
                MEDIA_REMOTE_PORT,
                precedence_value=MEDIA_PRECEDENCE,
            ),
        )

    def test_open_receive_channel_ack_parses_7912_port(self):
        pkt = wire_from_hex(load_fixture_group("cm_call_media")["155"])
        parsed = payloads.parse_open_receive_channel_ack(pkt[12:])
        assert parsed["status"] == 0
        assert parsed["port"] == 16384
        assert parsed["pass_through_party_id"] == PASS_THROUGH_PARTY_ID


class TestMessageSequenceOrder:
    """Sanity: outbound New Call emits the same msg_id order as CUCM."""

    def test_new_call_msg_id_order(self):
        session = SkinnySession.__new__(SkinnySession)
        built = session._legacy_outbound_packets(LINE, REF_NEW_CALL)
        cucm = [wire_from_hex(h) for h in load_fixture_group("cm_cap_new_call").values()]
        assert [msg_id(p) for p in built] == [msg_id(p) for p in cucm]
