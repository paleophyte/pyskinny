"""Console transfer key (t)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ui.console import ConsoleApp


def _app_with_call(*, in_transfer: bool = False) -> ConsoleApp:
    app = ConsoleApp()
    app.line = 1
    app.client = MagicMock()
    state = SimpleNamespace(
        active_call=True,
        media_active=False,
        active_calls_list=["cm2-1"],
        calls={
            "cm2-1": {
                "call_state": 10 if in_transfer else 5,
                "call_state_name": "In Transfer" if in_transfer else "Connected",
            }
        },
        current_prompt="Enter Number" if in_transfer else "Connected",
    )
    app.client.state = state
    app.log = MagicMock()
    return app


def test_press_transfer_when_call_active():
    app = _app_with_call()
    app._press_transfer()
    app.client.press_transfer.assert_called_once_with(line=1)


def test_press_transfer_ignored_when_idle():
    app = ConsoleApp()
    app.client = MagicMock()
    app.client.state = SimpleNamespace(
        active_call=False,
        media_active=False,
        active_calls_list=[],
        calls={},
        current_prompt="",
    )
    app._press_transfer()
    app.client.press_transfer.assert_not_called()
