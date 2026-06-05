"""Tests for console-integrated client web UI."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock

from ui.client_web import ClientWebController, start_client_web


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _mock_client(*, registered: bool = True) -> MagicMock:
    client = MagicMock()
    client.running = True
    client.uses_softkeys.return_value = True
    client.resolve_call_target.return_value = (1, 0)

    state = SimpleNamespace(
        is_registered=threading.Event(),
        device_name="SEP222233334444",
        model="7970",
        server="10.0.0.180",
        current_prompt="Your current options",
        selected_softkey_set=0,
        selected_softkeys={},
        active_call=False,
        active_calls_list=[],
        calls={},
        softkey_template={"0": {"label": "NewCall", "event": 1}},
        button_template={},
        lines={"1": {"line_dir_number": "1003"}},
        speed_dials={},
    )
    if registered:
        state.is_registered.set()
    state.get_current_softkeys = MagicMock(
        return_value=[("NewCall", 1), ("EndCall", 9)],
    )
    client.state = state
    return client


def _post_json(url: str, payload: dict | None = None) -> tuple[int, dict | bytes, str]:
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "json" in ct:
                return resp.status, json.loads(raw.decode()), ct
            return resp.status, raw, ct
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        ct = exc.headers.get("Content-Type", "")
        if "json" in ct:
            return exc.code, json.loads(raw.decode()), ct
        return exc.code, raw, ct


def test_client_web_state_and_screenshot():
    client = _mock_client()
    ctrl = ClientWebController(client, line=1)
    snap = ctrl.snapshot()
    assert snap["registered"] is True
    assert snap["device_name"] == "SEP222233334444"
    assert len(snap["softkeys"]) == 2
    png = ctrl.render_png()
    assert png.startswith(b"\x89PNG")


def test_client_web_http_action():
    client = _mock_client()
    server = start_client_web(client, host="127.0.0.1", port=_free_port())
    port = server.server_address[1]
    try:
        status, data, _ = _post_json(f"http://127.0.0.1:{port}/api/state")
        assert status == 200
        assert data["capabilities"]["execute"] is True

        status, body, ct = _post_json(f"http://127.0.0.1:{port}/api/screenshot")
        assert status == 200
        assert ct.startswith("image/png")
        assert body.startswith(b"\x89PNG")

        status, data, _ = _post_json(
            f"http://127.0.0.1:{port}/api/action",
            {"action": "softkey", "label": "NewCall"},
        )
        assert status == 200
        client.press_softkey.assert_called()
    finally:
        server.shutdown()
        server.server_close()


def test_client_web_not_running():
    client = _mock_client()
    client.running = False
    ctrl = ClientWebController(client)
    try:
        ctrl.snapshot()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
