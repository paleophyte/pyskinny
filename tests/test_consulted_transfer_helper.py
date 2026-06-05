"""Unit tests for integration_lab consulted-transfer helper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.integration_lab import run_consulted_transfer


def _client(name: str) -> MagicMock:
    client = MagicMock()
    client.state = SimpleNamespace(device_name=name, active_calls_list=[], calls={})
    client.events = SimpleNamespace(
        call_connected=MagicMock(),
        call_ringing=MagicMock(),
        call_ended=MagicMock(),
    )
    client.events.call_ringing.wait.return_value = False
    client.events.call_connected.wait.return_value = True
    return client


@patch("tests.integration_lab.wait_call_cleared", return_value=False)
@patch("tests.integration_lab.threading.Thread")
def test_run_consulted_transfer_skips_when_transferor_stays_active(mock_thread, _cleared):
    transferor = _client("SEP-A")
    target = _client("SEP-C")
    original = _client("SEP-B")

    mock_thread.return_value.start = MagicMock()
    mock_thread.return_value.join = MagicMock()

    with pytest.raises(pytest.skip.Exception) as exc:
        run_consulted_transfer(transferor, target, original, "5003", ring_timeout=0.01)

    assert "consulted transfer did not complete" in str(exc.value).split("\n")[0]
    transferor.consulted_transfer.assert_called_once()
