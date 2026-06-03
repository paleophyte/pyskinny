"""Hold / resume / transfer plumbing for run_cli and run_macro."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from client import SCCPClient
from state import PhoneState
from ui.cli import load_cli_spec, resolve_command_with_tokens
from ui.cli_handlers import (
    exec_phone_end,
    exec_phone_hold,
    exec_phone_resume,
    exec_phone_transfer,
)
from ui.macro_cli import MacroInstruction, parse_macro_script, run_macro
from utils.call_management import mark_call_connected


def _make_client(*, call_ref: int = 16777221) -> SCCPClient:
    state = PhoneState(server="127.0.0.1", mac="AABBCCDDEEFF", model="7970")
    state.softkey_template = {
        "1": {"label": "Hold", "event": 3},
        "2": {"label": "Resume", "event": 10},
        "3": {"label": "Transfer", "event": 4},
        "4": {"label": "EndCall", "event": 9},
        "5": {"label": "NewCall", "event": 2},
    }
    client = SCCPClient(state)
    mark_call_connected(client, call_reference=call_ref, line_instance=1)
    state.selected_call_reference = str(call_ref)
    return client


def test_resolve_call_target_uses_active_call_ref_not_line_key():
    client = _make_client(call_ref=16777221)
    line, ref = client.resolve_call_target()
    assert line == 1
    assert ref == 16777221


@patch("client.handle_softkey_press")
def test_press_softkey_uses_resolved_call_reference(mock_softkey):
    client = _make_client(call_ref=99988877)
    client.press_softkey("Hold")
    mock_softkey.assert_called_once_with(client, 1, 3, 99988877)


@patch("client.handle_softkey_press")
@patch("client.handle_keypad_press")
def test_blind_transfer_sequence(mock_keypad, mock_softkey):
    client = _make_client()
    client.blind_transfer("1001", pause=0)

    assert mock_softkey.call_count == 2
    mock_softkey.assert_any_call(client, 1, 4, 16777221)
    assert [c.args[2] for c in mock_keypad.call_args_list] == [1, 0, 0, 1]


class _Ctx:
    def __init__(self, client=None):
        self.client = client


def test_cli_hold_resume_end_require_connection():
    logs: list[str] = []

    def log(msg):
        logs.append(msg)

    exec_phone_hold(_Ctx(), "phone hold", ["phone", "hold"], log)
    assert logs == ["% Not connected"]


@patch("client.handle_softkey_press")
def test_cli_hold_sends_hold_softkey(mock_softkey):
    client = _make_client()
    logs: list[str] = []

    exec_phone_hold(_Ctx(client), "phone hold", ["phone", "hold"], lambda m: logs.append(m))
    mock_softkey.assert_called_once_with(client, 1, 3, 16777221)


@patch("client.handle_softkey_press")
def test_cli_transfer_without_number(mock_softkey):
    client = _make_client()
    exec_phone_transfer(_Ctx(client), "phone transfer", ["phone", "transfer"], lambda m: None)
    mock_softkey.assert_called_once_with(client, 1, 4, 16777221)


def test_cli_transfer_with_number():
    client = _make_client()
    with patch.object(client, "blind_transfer") as mock_blind:
        exec_phone_transfer(
            _Ctx(client),
            "phone transfer 1001",
            ["phone", "transfer", "1001"],
            lambda m: None,
        )
        mock_blind.assert_called_once_with("1001")


def test_cli_spec_parses_phone_hold_and_transfer():
    spec = load_cli_spec("ui/cli_commands.json")
    func, tokens, _caps, err = resolve_command_with_tokens(spec, ["phone", "hold"])
    assert err == ""
    assert func == "exec_phone_hold"
    assert tokens == ["phone", "hold"]

    func, tokens, _caps, err = resolve_command_with_tokens(spec, ["phone", "transfer"])
    assert err == ""
    assert func == "exec_phone_transfer"

    func, tokens, _caps, err = resolve_command_with_tokens(spec, ["phone", "transfer", "1001"])
    assert err == ""
    assert func == "exec_phone_transfer"
    assert tokens == ["phone", "transfer", "1001"]


@patch("ui.macro_cli.logger")
@patch("client.handle_softkey_press")
def test_macro_hold_and_resume(mock_softkey, _logger):
    client = _make_client()
    stop = threading.Event()
    instructions = [
        MacroInstruction("HOLD"),
        MacroInstruction("RESUME"),
    ]
    run_macro(client, instructions, {}, stop)
    assert mock_softkey.call_args_list[0].args[2:] == (3, 16777221)
    assert mock_softkey.call_args_list[1].args[2:] == (10, 16777221)


@patch("ui.macro_cli.logger")
@patch("client.handle_softkey_press")
@patch("client.handle_keypad_press")
def test_macro_transfer_with_number(mock_keypad, mock_softkey, _logger):
    client = _make_client()
    stop = threading.Event()
    instructions, _ = parse_macro_script("TRANSFER 1001, END")
    run_macro(client, instructions, {}, stop)
    assert mock_softkey.call_count >= 2
    assert any(c.args[2] == 9 for c in mock_softkey.call_args_list)
