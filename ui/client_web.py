"""Web UI that controls a local SCCPClient (console softphone companion)."""

from __future__ import annotations

import html
import io
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from messages.generic import handle_button_press

if TYPE_CHECKING:
    from client import SCCPClient

logger = logging.getLogger(__name__)

_DISPLAY_W = 320
_DISPLAY_H = 200


def _ui_softkey_set(client: SCCPClient) -> int | None:
    state = client.state
    if not (getattr(state, "active_call", False) or getattr(state, "active_calls_list", None)):
        return state.selected_softkey_set

    best_idx = None
    best_ref = -1
    for key, meta in (state.selected_softkeys or {}).items():
        if not str(key).isdigit():
            continue
        ref = int(key)
        idx = meta.get("softkeyset_index")
        if idx is not None and ref >= best_ref:
            best_ref = ref
            best_idx = idx
    return best_idx if best_idx is not None else state.selected_softkey_set


def _button_label(state, *, type_name: str, instance: int) -> str:
    if type_name == "Line":
        line = (state.lines or {}).get(str(instance), {})
        dn = line.get("line_dir_number")
        return f"Line {instance}" + (f" {dn}" if dn else "")
    if type_name == "Speed Dial":
        sd = (state.speed_dials or {}).get(str(instance), {})
        number = sd.get("speed_dial_number") or sd.get("number")
        return f"SD {instance}" + (f" {number}" if number else "")
    return type_name


class ClientWebController:
    """Thread-safe remote control for one SCCPClient."""

    def __init__(
        self,
        client: SCCPClient,
        *,
        line: int = 1,
        lock: threading.Lock | None = None,
    ):
        self.client = client
        self.line = line
        self.lock = lock or threading.Lock()

    def _require_client(self) -> SCCPClient:
        if not self.client or not self.client.running:
            raise RuntimeError("SCCP client is not running")
        return self.client

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            client = self._require_client()
            state = client.state
            registered = state.is_registered.is_set()
            softkeys: list[dict[str, str]] = []
            buttons: list[dict[str, Any]] = []

            if state.softkey_template:
                for label, _event in state.get_current_softkeys(_ui_softkey_set(client)):
                    if label:
                        softkeys.append({"label": label, "kind": "softkey"})
            elif state.button_template:
                for _pos, button in sorted(
                    (state.button_template or {}).items(),
                    key=lambda item: int(item[0]),
                ):
                    button_type = int(button.get("type", 255))
                    if button_type == 255:
                        continue
                    instance = int(button.get("instance", 0) or 0)
                    type_name = button.get("type_name") or f"Type {button_type}"
                    buttons.append(
                        {
                            "label": _button_label(
                                state,
                                type_name=type_name,
                                instance=instance,
                            ),
                            "kind": "button",
                            "button_type": button_type,
                            "instance": instance,
                        }
                    )

            refs = [str(r) for r in (state.active_calls_list or [])]
            calls = []
            for ref in refs:
                info = dict((state.calls or {}).get(ref, {}) or {})
                calls.append(
                    {
                        "ref": ref,
                        "state": info.get("call_state_name") or str(info.get("call_state", "")),
                        "remote": info.get("remote_name")
                        or info.get("called_party")
                        or info.get("calling_party")
                        or "",
                    }
                )

            return {
                "registered": registered,
                "device_name": state.device_name or "",
                "model": state.model or "",
                "server": state.server or "",
                "prompt": state.current_prompt or "",
                "line": self.line,
                "softkeys": softkeys,
                "buttons": buttons,
                "calls": calls,
                "capabilities": {"screenshot": True, "execute": registered},
            }

    def render_png(self) -> bytes:
        from PIL import Image, ImageDraw, ImageFont

        snap = self.snapshot()
        img = Image.new("RGB", (_DISPLAY_W, _DISPLAY_H), (18, 22, 30))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        y = 8
        header = f"{snap['device_name']}  —  {'Registered' if snap['registered'] else 'Connecting…'}"
        draw.text((8, y), header[:48], fill=(180, 190, 205), font=font)
        y += 18
        draw.text((8, y), f"CM {snap['server']}"[:40], fill=(120, 130, 150), font=font)
        y += 20

        prompt = snap.get("prompt") or "(no prompt)"
        for chunk in _wrap_text(prompt, 38):
            draw.text((8, y), chunk, fill=(235, 238, 245), font=font)
            y += 14
            if y > _DISPLAY_H - 70:
                break

        y = max(y + 8, _DISPLAY_H - 68)
        draw.line((4, y - 4, _DISPLAY_W - 4, y - 4), fill=(45, 55, 70))
        for call in snap.get("calls", [])[:3]:
            line = f"{call['ref']}: {call['state']} {call['remote']}"[:42]
            draw.text((8, y), line, fill=(160, 210, 180), font=font)
            y += 14

        actions = snap.get("softkeys") or snap.get("buttons") or []
        if actions:
            labels = [a["label"] for a in actions[:8]]
            sk_text = "  |  ".join(labels)
            draw.text((8, _DISPLAY_H - 22), sk_text[:50], fill=(140, 170, 220), font=font)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def run_action(self, action: str, payload: dict[str, Any]) -> None:
        with self.lock:
            client = self._require_client()
            line = int(payload.get("line") or self.line)
            action = action.strip().lower()

            if action == "softkey":
                label = str(payload.get("label") or "").strip()
                if not label:
                    raise ValueError("softkey label is required")
                _, call_ref = client.resolve_call_target(line, 0, softkey_name=label)
                if label == "NewCall":
                    call_ref = 0
                client.press_softkey(label, line=line, call_ref=call_ref)
                return

            if action == "button":
                button_type = int(payload["button_type"])
                instance = int(payload.get("instance") or 1)
                handle_button_press(client, button_type, instance)
                return

            if action == "keys":
                client.dial_digits(str(payload.get("digits") or ""), line=line)
                return

            if action == "dial":
                client.place_call(str(payload.get("number") or ""), line=line)
                return

            if action == "newcall":
                if client.uses_softkeys():
                    client.press_softkey("NewCall", line=line, call_ref=0)
                else:
                    client.press_line_button(line)
                return

            if action == "endcall":
                _, call_ref = client.resolve_call_target(line, 0)
                client.press_softkey("EndCall", line=line, call_ref=call_ref)
                return

            if action == "hold":
                _, call_ref = client.resolve_call_target(line, 0)
                client.press_softkey("Hold", line=line, call_ref=call_ref)
                return

            if action == "resume":
                _, call_ref = client.resolve_call_target(line, 0)
                client.press_softkey("Resume", line=line, call_ref=call_ref)
                return

            if action == "hook":
                mode = str(payload.get("mode") or "toggle").lower()
                if mode == "offhook":
                    client.off_hook()
                elif mode == "onhook":
                    client.on_hook()
                else:
                    active = bool(
                        getattr(client.state, "active_call", False)
                        or getattr(client.state, "active_calls_list", None)
                    )
                    if active:
                        client.on_hook()
                    else:
                        client.off_hook()
                return

            raise ValueError(f"unknown action: {action!r}")


def _wrap_text(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = (" ".join(current + [word])).strip()
        if len(trial) <= width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [text[:width]]


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _page_html(*, title: str, device_name: str) -> bytes:
    subtitle = html.escape(device_name or "console client")
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{
  --bg: #0f1419; --panel: #1a2332; --border: #2d3a4d;
  --text: #e7ecf3; --muted: #8b9cb3; --accent: #3d8bfd;
  --ok: #3dd68c; --err: #ff6b6b;
}}
* {{ box-sizing: border-box; }}
body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
header {{ padding: 1rem 1.25rem; border-bottom: 1px solid var(--border); }}
header h1 {{ margin: 0; font-size: 1.1rem; }}
header p {{ margin: 0.35rem 0 0; color: var(--muted); font-size: 0.85rem; }}
main {{
  display: grid; grid-template-columns: minmax(280px, 1fr) minmax(280px, 400px);
  gap: 1rem; padding: 1rem 1.25rem 2rem; max-width: 960px; margin: 0 auto;
}}
@media (max-width: 760px) {{ main {{ grid-template-columns: 1fr; }} }}
.panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; }}
.panel h2 {{ margin: 0 0 0.75rem; font-size: 0.8rem; text-transform: uppercase; color: var(--muted); }}
#screen {{ max-width: 100%; border: 1px solid var(--border); border-radius: 6px; background: #000; }}
#actions {{ display: flex; flex-wrap: wrap; gap: 0.4rem; min-height: 2rem; }}
button {{
  cursor: pointer; border: 1px solid var(--border); background: var(--bg);
  color: var(--text); border-radius: 6px; padding: 0.45rem 0.65rem; font-size: 0.85rem;
}}
button:hover {{ border-color: var(--accent); }}
button.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
.btn-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.4rem; }}
.dial-row {{ display: flex; gap: 0.4rem; margin-top: 0.5rem; }}
.dial-row input {{
  flex: 1; padding: 0.45rem; border-radius: 6px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text);
}}
#status {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.75rem; min-height: 1.2rem; }}
#status.err {{ color: var(--err); }}
#status.ok {{ color: var(--ok); }}
#meta {{ font-size: 0.8rem; color: var(--muted); line-height: 1.5; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>Controlling <strong>{subtitle}</strong> — same SCCP session as the curses console.</p>
</header>
<main>
  <section class="panel">
    <h2>Display (synthetic)</h2>
    <img id="screen" alt="client display" width="320">
    <div class="row" style="margin-top:0.75rem;display:flex;gap:0.5rem;align-items:center">
      <button type="button" class="primary" id="btn-refresh">Refresh</button>
      <label style="font-size:0.8rem;color:var(--muted)">
        <input type="checkbox" id="auto-refresh" checked> Auto (2s)
      </label>
    </div>
    <div id="meta"></div>
  </section>
  <section class="panel">
    <h2>Actions</h2>
    <div id="actions"><em style="color:var(--muted)">Waiting for registration…</em></div>
    <h2 style="margin-top:1rem">Keypad</h2>
    <div class="btn-grid" id="keypad"></div>
    <div class="dial-row">
      <input id="dial-number" type="text" placeholder="1001" autocomplete="off">
      <button type="button" id="btn-dial">Dial</button>
    </div>
    <div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.4rem">
      <button type="button" data-action="hook">Hook toggle</button>
      <button type="button" data-action="newcall">New call</button>
      <button type="button" data-action="endcall">End call</button>
    </div>
    <div id="status"></div>
  </section>
</main>
<script>
let state = null;
let autoTimer = null;

function $(id) {{ return document.getElementById(id); }}

function setStatus(msg, kind) {{
  const el = $("status");
  el.textContent = msg || "";
  el.className = kind || "";
}}

async function api(path, body) {{
  const res = await fetch(path, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(body || {{}}),
  }});
  const ct = res.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) {{
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }}
  if (!res.ok) throw new Error(res.statusText);
  return res;
}}

function renderActions() {{
  const box = $("actions");
  if (!state || !state.capabilities.execute) {{
    box.innerHTML = '<em style="color:var(--muted)">Register with CallManager to enable controls.</em>';
    document.querySelectorAll("#keypad button, [data-action], #btn-dial").forEach(b => b.disabled = true);
    return;
  }}
  const items = [...(state.softkeys || []), ...(state.buttons || [])];
  box.innerHTML = "";
  items.forEach(item => {{
    const btn = document.createElement("button");
    btn.textContent = item.label;
    btn.disabled = false;
    btn.onclick = () => runAction(item.kind === "button" ? "button" : "softkey", item);
    box.appendChild(btn);
  }});
  document.querySelectorAll("#keypad button, [data-action], #btn-dial").forEach(b => b.disabled = false);
}}

function renderMeta() {{
  if (!state) return;
  $("meta").innerHTML =
    `<div><strong>${{state.device_name}}</strong> · ${{state.model}} · CM ${{state.server}}</div>` +
    `<div>Prompt: ${{state.prompt || "—"}}</div>` +
  (state.calls.length
    ? `<div>Calls: ${{state.calls.map(c => c.ref + " " + c.state).join(", ")}}</div>`
    : "");
}}

async function refreshState() {{
  try {{
    state = await api("/api/state");
    renderMeta();
    renderActions();
  }} catch (e) {{
    setStatus(String(e.message || e), "err");
  }}
}}

async function refreshScreen() {{
  try {{
    const res = await api("/api/screenshot");
    const blob = await res.blob();
    $("screen").src = URL.createObjectURL(blob) + "#" + Date.now();
  }} catch (e) {{
    setStatus(String(e.message || e), "err");
  }}
}}

async function runAction(action, extra) {{
  setStatus("Sending…");
  try {{
    const body = {{ action, ...extra }};
    if (action === "softkey") body.label = extra.label;
    if (action === "button") {{
      body.button_type = extra.button_type;
      body.instance = extra.instance;
    }}
    await api("/api/action", body);
    setStatus("OK", "ok");
    await refreshState();
    await refreshScreen();
  }} catch (e) {{
    setStatus(String(e.message || e), "err");
  }}
}}

function setupKeypad() {{
  const keys = "123456789*0#".split("");
  const grid = $("keypad");
  keys.forEach(k => {{
    const btn = document.createElement("button");
    btn.textContent = k;
    btn.disabled = true;
    btn.onclick = () => runAction("keys", {{ digits: k }});
    grid.appendChild(btn);
  }});
}}

$("btn-refresh").onclick = async () => {{ await refreshScreen(); await refreshState(); }};
$("btn-dial").onclick = () => runAction("dial", {{ number: $("dial-number").value }});
document.querySelectorAll("[data-action]").forEach(btn => {{
  btn.onclick = () => runAction(btn.dataset.action, {{}});
}});
$("auto-refresh").onchange = () => {{
  if (autoTimer) clearInterval(autoTimer);
  if ($("auto-refresh").checked) {{
    autoTimer = setInterval(async () => {{ await refreshScreen(); await refreshState(); }}, 2000);
  }}
}};
setupKeypad();
refreshState().then(refreshScreen);
autoTimer = setInterval(async () => {{ await refreshScreen(); await refreshState(); }}, 2000);
</script>
</body>
</html>"""
    return body.encode("utf-8")


class _ClientWebHandler(BaseHTTPRequestHandler):
    controller: ClientWebController
    title: str = "Pyskinny console"

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("client-web %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        path = urlparse(self.path or "/").path
        if path in ("/", "/index.html"):
            name = ""
            try:
                name = self.controller.snapshot().get("device_name") or ""
            except Exception:
                pass
            self._send_bytes(_page_html(title=self.title, device_name=name), "text/html; charset=utf-8")
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path or "/").path
        try:
            if path == "/api/state":
                self._send_json(200, self.controller.snapshot())
            elif path == "/api/screenshot":
                png = self.controller.render_png()
                self._send_bytes(png, "image/png")
            elif path == "/api/action":
                data = _read_json_body(self)
                action = str(data.get("action") or "")
                self.controller.run_action(action, data)
                self._send_json(200, {"ok": True, "action": action})
            else:
                self._send_json(404, {"error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(503, {"error": str(exc)})
        except Exception as exc:
            logger.exception("client-web API error")
            self._send_json(500, {"error": str(exc)})

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, payload: bytes, content_type: str, *, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_client_web(
    client: SCCPClient,
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    line: int = 1,
    lock: threading.Lock | None = None,
    title: str = "Pyskinny console",
) -> ThreadingHTTPServer:
    controller = ClientWebController(client, line=line, lock=lock)
    handler = type(
        "_BoundClientWebHandler",
        (_ClientWebHandler,),
        {"controller": controller, "title": title},
    )
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"client-web-{port}",
        daemon=True,
    )
    thread.start()
    display_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    logger.info("Console web UI http://%s:%s/", display_host, port)
    return server
