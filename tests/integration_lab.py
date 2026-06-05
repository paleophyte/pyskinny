"""Shared helpers and lab profiles for live CallManager integration tests."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

import pytest

from client import SCCPClient
from state import PhoneState
from utils.client import normalize_mac_address

logger = logging.getLogger(__name__)

LabName = Literal["cm2", "cm31", "cm33", "cm41", "cm43"]

ALL_LABS: tuple[LabName, ...] = ("cm2", "cm31", "cm33", "cm41", "cm43")

# Built-in lab defaults (override with PYSKINNY_<LAB>_SERVER / _MODEL / _MAC_*).
LAB_DEFAULTS: dict[str, dict] = {
    "cm2": {
        "server": "10.0.0.11",
        "model": "Virtual30SPplus",
        "uses_device_names": True,
        "endpoint_a": "pyskinny01",
        "endpoint_b": "pyskinny02",
        "endpoint_c": "pyskinny03",
    },
    "cm31": {
        "server": "10.0.0.181",
        "model": "7960",
        "uses_device_names": False,
        "endpoint_a": "222233334444",
        "endpoint_b": "222233334445",
        "endpoint_c": "222233334446",
    },
    "cm33": {
        "server": "10.0.0.182",
        "model": "7970",
        "uses_device_names": False,
        "endpoint_a": "222233334444",
        "endpoint_b": "222233334445",
        "endpoint_c": "222233334446",
    },
    "cm41": {
        "server": "10.0.0.180",
        "model": "7970",
        "uses_device_names": False,
        "endpoint_a": "222233334444",
        "endpoint_b": "222233334445",
        "endpoint_c": "222233334446",
    },
    "cm43": {
        "server": "100.69.0.100",
        "model": "7970",
        "uses_device_names": False,
        "endpoint_a": "222233334444",
        "endpoint_b": "222233334445",
        "endpoint_c": "222233334446",
    },
}


@dataclass(frozen=True)
class LabProfile:
    name: LabName
    server: str
    model: str
    skip_tftp: bool
    register_timeout: float
    endpoint_a: str
    endpoint_b: str
    endpoint_c: str | None
    uses_device_names: bool

    @property
    def marker(self) -> str:
        return self.name

    @property
    def expects_softkeys(self) -> bool:
        return not self.uses_device_names


def _env_bool(key: str, default: str = "1") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes")


def _register_timeout() -> float:
    return float(os.environ.get("PYSKINNY_REGISTER_TIMEOUT", "60"))


def _env_prefix(lab: str) -> str:
    return f"PYSKINNY_{lab.upper()}"


def load_lab(name: str) -> LabProfile | None:
    """Return a lab profile when the lab is listed in PYSKINNY_INTEGRATION_LABS."""
    if name not in LAB_DEFAULTS:
        return None

    requested = os.environ.get("PYSKINNY_INTEGRATION_LABS", "")
    requested_names = {part.strip().lower() for part in requested.split(",") if part.strip()}
    if requested_names and name not in requested_names:
        return None

    defaults = LAB_DEFAULTS[name]
    prefix = _env_prefix(name)

    server = os.environ.get(f"{prefix}_SERVER", defaults["server"])
    if os.environ.get(f"{prefix}_DISABLE", "").lower() in ("1", "true", "yes"):
        return None

    skip_tftp = _env_bool("PYSKINNY_SKIP_TFTP", "1")
    timeout = _register_timeout()
    uses_device_names = defaults["uses_device_names"]

    if uses_device_names:
        endpoint_a = os.environ.get(f"{prefix}_DEVICE", defaults["endpoint_a"])
        endpoint_b = os.environ.get(f"{prefix}_DEVICE_B", defaults["endpoint_b"])
        endpoint_c = os.environ.get(f"{prefix}_DEVICE_C", defaults.get("endpoint_c"))
    else:
        shared_a = os.environ.get("PYSKINNY_MAC_A", os.environ.get("PYSKINNY_TEST_MAC"))
        shared_b = os.environ.get("PYSKINNY_MAC_B")
        shared_c = os.environ.get("PYSKINNY_MAC_C")
        endpoint_a = os.environ.get(f"{prefix}_MAC_A", shared_a or defaults["endpoint_a"])
        endpoint_b = os.environ.get(f"{prefix}_MAC_B", shared_b or defaults["endpoint_b"])
        endpoint_c = os.environ.get(
            f"{prefix}_MAC_C",
            shared_c or defaults.get("endpoint_c"),
        )

    return LabProfile(
        name=name,  # type: ignore[arg-type]
        server=server,
        model=os.environ.get(f"{prefix}_MODEL", defaults["model"]),
        skip_tftp=skip_tftp,
        register_timeout=timeout,
        endpoint_a=endpoint_a,
        endpoint_b=endpoint_b,
        endpoint_c=endpoint_c,
        uses_device_names=uses_device_names,
    )


def configured_labs() -> list[str]:
    requested = os.environ.get("PYSKINNY_INTEGRATION_LABS")
    if requested:
        names = [part.strip().lower() for part in requested.split(",") if part.strip()]
    else:
        names = list(ALL_LABS)
    return [name for name in names if load_lab(name) is not None]


def make_state(lab: LabProfile, endpoint: str) -> PhoneState:
    if lab.uses_device_names:
        return PhoneState(server=lab.server, device_name=endpoint, model=lab.model)
    return PhoneState(server=lab.server, mac=endpoint, model=lab.model)


def start_client(lab: LabProfile, endpoint: str) -> tuple[SCCPClient, PhoneState]:
    state = make_state(lab, endpoint)
    state.enable_audio = False
    client = SCCPClient(state)
    client.get_tftp_config = not lab.skip_tftp
    client.start()
    registered = state.is_registered.wait(timeout=lab.register_timeout)
    if not registered and client.events.register_rejected.is_set():
        reason = state.register_reject_reason or "RegisterReject"
        client.stop()
        pytest.skip(f"{expected_device_name(lab, endpoint)} rejected by {lab.server}: {reason}")
    assert registered, (
        f"{expected_device_name(lab, endpoint)} did not register on {lab.server} "
        f"within {lab.register_timeout}s"
    )
    time.sleep(0.75)
    return client, state


def stop_client(client: SCCPClient, state: PhoneState) -> None:
    client.stop()
    assert state.is_unregistered.wait(timeout=20), f"{state.device_name} did not unregister"


def expected_device_name(lab: LabProfile, endpoint: str) -> str:
    if lab.uses_device_names:
        return endpoint
    return "SEP" + normalize_mac_address(endpoint)


def line_dn(state: PhoneState) -> str:
    if not state.lines:
        time.sleep(1.0)
    assert state.lines, f"{state.device_name}: no LineStatRes lines yet"
    line = state.lines.get("1") or next(iter(state.lines.values()))
    dn = (line.get("line_dir_number") or "").strip()
    assert dn, f"{state.device_name}: empty directory number in {line!r}"
    return dn


def place_call(client: SCCPClient, number: str) -> None:
    client.place_call(number)


def answer_call(client: SCCPClient) -> None:
    client.answer_call()


def hangup(client: SCCPClient) -> None:
    if not client.state.active_calls_list and not client.state.call_active:
        return
    if client.uses_softkeys():
        client.press_softkey("EndCall")
    else:
        client.on_hook()
    time.sleep(1.0)
    if client.state.active_calls_list or client.state.call_active:
        client.on_hook()
        time.sleep(0.75)


def wait_call_cleared(client: SCCPClient, *, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.events.call_ended.is_set() or not client.state.active_calls_list:
            return True
        time.sleep(0.25)
    return not client.state.active_calls_list


def connect_two_party(
    client_a: SCCPClient,
    state_a: PhoneState,
    client_b: SCCPClient,
    state_b: PhoneState,
    *,
    dn_b: str,
    ring_timeout: float = 20.0,
    connect_timeout: float = 20.0,
) -> None:
    place_call(client_a, dn_b)
    assert client_b.events.call_ringing.wait(timeout=ring_timeout), (
        f"{state_b.device_name} did not ring for DN {dn_b}"
    )
    answer_call(client_b)
    time.sleep(0.75)
    assert client_a.events.call_connected.wait(timeout=connect_timeout), (
        f"caller {state_a.device_name} not connected: {state_a.calls}"
    )
    assert client_b.events.call_connected.wait(timeout=connect_timeout), (
        f"callee {state_b.device_name} not connected: {state_b.calls}"
    )
    assert state_a.active_calls_list, "caller missing active call ref"
    assert state_b.active_calls_list, "callee missing active call ref"
    ref_a = str(state_a.active_calls_list[-1])
    ref_b = str(state_b.active_calls_list[-1])
    assert wait_call_state(
        client_a, ref_a, 5, expected_name="Connected", timeout=connect_timeout
    ), f"caller not in Connected: {state_a.calls.get(ref_a)}"
    assert wait_call_state(
        client_b, ref_b, 5, expected_name="Connected", timeout=connect_timeout
    ), f"callee not in Connected: {state_b.calls.get(ref_b)}"


def call_ref_summary(state: PhoneState) -> str:
    refs = list(state.active_calls_list or [])
    kinds = ["synthetic" if str(r).startswith("cm2-") else "numeric" for r in refs]
    return f"refs={refs} kinds={kinds}"


def wait_call_state(
    client: SCCPClient,
    call_ref: str | int,
    expected_state: int,
    *,
    timeout: float = 12.0,
    expected_name: str | None = None,
) -> bool:
    """Poll until a call ref reaches the given Skinny call_state (e.g. 8 = Hold)."""
    ref = str(call_ref)
    deadline = time.time() + timeout
    while time.time() < deadline:
        call = client.state.calls.get(ref, {}) or {}
        if call.get("call_state") == expected_state:
            return True
        if expected_name and call.get("call_state_name") == expected_name:
            return True
        time.sleep(0.25)
    return False


def log_softkey_inventory(state: PhoneState, *, lab: str = "") -> None:
    from utils.softkeys import connected_softkey_labels, template_label_set

    prefix = f"[{lab}] " if lab else ""
    labels = template_label_set(state.softkey_template or {})
    connected = connected_softkey_labels(
        state.softkey_set_definition or {},
        state.softkey_template or {},
    )
    logger.info(
        "%s%s softkeys: template=%s connected_set=%s selected_set=%s",
        prefix,
        state.device_name,
        labels,
        connected,
        state.selected_softkey_set,
    )


def assert_hold_capable(state: PhoneState, *, lab: str = "") -> None:
    """Skip early when CM template clearly lacks Hold/Resume."""
    from utils.softkeys import template_label_set

    labels = template_label_set(state.softkey_template or {})
    if not labels:
        return
    missing = [name for name in ("Hold", "Resume") if name not in labels]
    if missing:
        pytest.skip(
            f"{lab + ': ' if lab else ''}{state.device_name} SoftKeyTemplate missing "
            f"{', '.join(missing)} — assign a standard 79xx softkey template in CUCM"
        )
