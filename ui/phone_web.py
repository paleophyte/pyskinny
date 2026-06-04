"""Mini web UI for Cisco 79xx HTTP CGI remote control and LCD screenshots."""

from __future__ import annotations

import html
import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from tools.phone import (
    ScreenshotNotSupportedError,
    dial,
    fetch_screenshot_png_bytes,
    hardkey,
    nav,
    press_keys,
    probe_phone_http,
    softkey,
    _execute,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhoneTarget:
    ip: str
    user: str | None = None
    password: str | None = None
    port: int | None = None
    use_https: bool = False
    try_https_fallback: bool = False

    def auth(self) -> tuple[str, str] | None:
        if self.user:
            return (self.user, self.password or "")
        return None

    def http_kwargs(self) -> dict[str, Any]:
        return {
            "use_https": self.use_https,
            "try_https_fallback": self.try_https_fallback,
            "port": self.port,
        }


def _parse_phone(payload: dict[str, Any]) -> PhoneTarget:
    ip = str(payload.get("ip") or "").strip()
    if not ip:
        raise ValueError("phone ip is required")
    port_raw = payload.get("port")
    port = int(port_raw) if port_raw not in (None, "") else None
    user = str(payload.get("user") or "").strip() or None
    password = payload.get("password")
    if password is not None:
        password = str(password)
    return PhoneTarget(
        ip=ip,
        user=user,
        password=password,
        port=port,
        use_https=bool(payload.get("https")),
        try_https_fallback=bool(payload.get("try_https")),
    )


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _page_html(*, title: str = "Phone remote") -> bytes:
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{
  --bg: #0f1419;
  --panel: #1a2332;
  --border: #2d3a4d;
  --text: #e7ecf3;
  --muted: #8b9cb3;
  --accent: #3d8bfd;
  --ok: #3dd68c;
  --warn: #ffb020;
  --err: #ff6b6b;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  margin: 0;
  min-height: 100vh;
}}
header {{
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}}
header h1 {{ font-size: 1.15rem; margin: 0; font-weight: 600; }}
.badge {{
  font-size: 0.75rem;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--muted);
}}
.badge.ok {{ color: var(--ok); border-color: #2a6b4a; }}
.badge.warn {{ color: var(--warn); border-color: #7a5520; }}
main {{
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(300px, 420px);
  gap: 1rem;
  padding: 1rem 1.25rem 2rem;
  max-width: 1100px;
  margin: 0 auto;
}}
@media (max-width: 820px) {{
  main {{ grid-template-columns: 1fr; }}
}}
.panel {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1rem;
}}
.panel h2 {{
  margin: 0 0 0.75rem;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}}
.screen-wrap {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}}
#screen {{
  max-width: 100%;
  image-rendering: pixelated;
  background: #000;
  border: 1px solid var(--border);
  border-radius: 6px;
  min-height: 120px;
  min-width: 160px;
}}
.screen-placeholder {{
  color: var(--muted);
  text-align: center;
  padding: 2rem 1rem;
  font-size: 0.9rem;
  line-height: 1.5;
}}
label {{ display: block; font-size: 0.8rem; color: var(--muted); margin-bottom: 0.25rem; }}
input[type=text], input[type=password], input[type=number] {{
  width: 100%;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  margin-bottom: 0.65rem;
}}
.row {{ display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.65rem; }}
.row label {{ margin: 0; display: flex; align-items: center; gap: 0.35rem; }}
.btn-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.4rem;
}}
.btn-grid.wide {{ grid-template-columns: repeat(4, 1fr); }}
button {{
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  border-radius: 6px;
  padding: 0.5rem 0.65rem;
  font-size: 0.85rem;
}}
button:hover {{ border-color: var(--accent); }}
button.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
#status {{
  font-size: 0.8rem;
  color: var(--muted);
  min-height: 1.2rem;
  margin-top: 0.5rem;
}}
#status.err {{ color: var(--err); }}
#status.ok {{ color: var(--ok); }}
.dial-row {{ display: flex; gap: 0.4rem; }}
.dial-row input {{ flex: 1; margin-bottom: 0; }}
.nav-pad {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.35rem;
  max-width: 180px;
  margin: 0 auto;
}}
.nav-pad .spacer {{ visibility: hidden; }}
footer {{
  text-align: center;
  font-size: 0.75rem;
  color: var(--muted);
  padding: 0 1rem 1.5rem;
}}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <span id="cap-screenshot" class="badge">screenshot ?</span>
  <span id="cap-execute" class="badge">remote control ?</span>
</header>
<main>
  <section class="panel screen-wrap">
    <h2>LCD</h2>
    <img id="screen" alt="phone LCD" hidden>
    <div id="screen-placeholder" class="screen-placeholder">
      Connect to a phone and press <strong>Probe</strong> or <strong>Refresh</strong>.
      Some firmware supports remote control but not <code>/CGI/Screenshot</code>.
    </div>
    <div class="row">
      <button type="button" class="primary" id="btn-probe">Probe</button>
      <button type="button" id="btn-refresh" disabled>Refresh screen</button>
      <label><input type="checkbox" id="auto-refresh"> Auto (3s)</label>
    </div>
  </section>
  <section class="panel">
    <h2>Connection</h2>
    <label for="ip">Phone IP</label>
    <input id="ip" type="text" placeholder="10.0.0.71" autocomplete="off">
    <label for="user">Web username (optional)</label>
    <input id="user" type="text" placeholder="Administrator" autocomplete="username">
    <label for="password">Web password</label>
    <input id="password" type="password" autocomplete="current-password">
    <label for="port">HTTP port (blank = 80)</label>
    <input id="port" type="number" min="1" max="65535" placeholder="80">
    <div class="row">
      <label><input type="checkbox" id="https"> HTTPS only</label>
      <label><input type="checkbox" id="try-https"> Try HTTPS fallback</label>
    </div>
    <h2 style="margin-top:1rem">Softkeys</h2>
    <div class="btn-grid wide">
      <button type="button" data-action="softkey" data-index="1" disabled>Soft 1</button>
      <button type="button" data-action="softkey" data-index="2" disabled>Soft 2</button>
      <button type="button" data-action="softkey" data-index="3" disabled>Soft 3</button>
      <button type="button" data-action="softkey" data-index="4" disabled>Soft 4</button>
    </div>
    <div class="row" style="margin-top:0.5rem">
      <button type="button" data-action="newcall" disabled>New call</button>
    </div>
    <h2 style="margin-top:1rem">Keypad</h2>
    <div class="btn-grid" id="keypad">
      <button type="button" data-key="1" disabled>1</button>
      <button type="button" data-key="2" disabled>2</button>
      <button type="button" data-key="3" disabled>3</button>
      <button type="button" data-key="4" disabled>4</button>
      <button type="button" data-key="5" disabled>5</button>
      <button type="button" data-key="6" disabled>6</button>
      <button type="button" data-key="7" disabled>7</button>
      <button type="button" data-key="8" disabled>8</button>
      <button type="button" data-key="9" disabled>9</button>
      <button type="button" data-key="*" disabled>*</button>
      <button type="button" data-key="0" disabled>0</button>
      <button type="button" data-key="#" disabled>#</button>
    </div>
    <h2 style="margin-top:1rem">Dial</h2>
    <div class="dial-row">
      <input id="dial-number" type="text" placeholder="1001" autocomplete="off">
      <button type="button" id="btn-dial" disabled>Dial</button>
    </div>
    <h2 style="margin-top:1rem">Navigation</h2>
    <div class="nav-pad">
      <span class="spacer"></span>
      <button type="button" data-action="nav" data-dir="up" disabled>Up</button>
      <span class="spacer"></span>
      <button type="button" data-action="nav" data-dir="left" disabled>Left</button>
      <button type="button" data-action="nav" data-dir="select" disabled>OK</button>
      <button type="button" data-action="nav" data-dir="right" disabled>Right</button>
      <span class="spacer"></span>
      <button type="button" data-action="nav" data-dir="down" disabled>Down</button>
      <span class="spacer"></span>
    </div>
    <div class="row" style="justify-content:center;margin-top:0.5rem">
      <button type="button" data-action="nav" data-dir="back" disabled>Back</button>
    </div>
    <h2 style="margin-top:1rem">Hard keys</h2>
    <div class="btn-grid wide">
      <button type="button" data-action="hook" data-name="speaker" disabled>Speaker</button>
      <button type="button" data-action="hook" data-name="headset" disabled>Headset</button>
      <button type="button" data-action="hook" data-name="mute" disabled>Mute</button>
      <button type="button" data-action="hook" data-name="messages" disabled>Messages</button>
      <button type="button" data-action="hook" data-name="services" disabled>Services</button>
      <button type="button" data-action="hook" data-name="directories" disabled>Directories</button>
      <button type="button" data-action="hook" data-name="settings" disabled>Settings</button>
    </div>
    <h2 style="margin-top:1rem">Raw Execute URL</h2>
    <div class="dial-row">
      <input id="raw-url" type="text" placeholder="Key:Soft2" autocomplete="off">
      <button type="button" id="btn-press" disabled>Send</button>
    </div>
    <div id="status"></div>
  </section>
</main>
<footer>Lab tool — binds locally by default. Credentials stay in your browser (localStorage).</footer>
<script>
const STORAGE_KEY = "pyskinny.phone_web.v1";
let caps = {{ screenshot: false, execute: false }};
let autoTimer = null;

function $(id) {{ return document.getElementById(id); }}

function phonePayload() {{
  const portVal = $("port").value.trim();
  return {{
    ip: $("ip").value.trim(),
    user: $("user").value.trim(),
    password: $("password").value,
    port: portVal ? parseInt(portVal, 10) : null,
    https: $("https").checked,
    try_https: $("try-https").checked,
  }};
}}

function saveSettings() {{
  const p = phonePayload();
  localStorage.setItem(STORAGE_KEY, JSON.stringify({{
    ip: p.ip, user: p.user, port: p.port,
    https: p.https, try_https: p.try_https,
  }}));
}}

function loadSettings() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const s = JSON.parse(raw);
    if (s.ip) $("ip").value = s.ip;
    if (s.user) $("user").value = s.user;
    if (s.port) $("port").value = s.port;
    $("https").checked = !!s.https;
    $("try-https").checked = !!s.try_https;
  }} catch (e) {{}}
}}

function setStatus(msg, kind) {{
  const el = $("status");
  el.textContent = msg || "";
  el.className = kind || "";
}}

function setCaps(c) {{
  caps = c;
  const ss = $("cap-screenshot");
  const ex = $("cap-execute");
  ss.textContent = c.screenshot ? "screenshot ok" : "no screenshot";
  ss.className = "badge " + (c.screenshot ? "ok" : "warn");
  ex.textContent = c.execute ? "remote control ok" : "no remote control";
  ex.className = "badge " + (c.execute ? "ok" : "warn");
  const ctrl = c.execute;
  document.querySelectorAll("[data-action],[data-key],#btn-dial,#btn-press").forEach(btn => {{
    btn.disabled = !ctrl;
  }});
  $("btn-refresh").disabled = !c.screenshot;
  if (!c.screenshot) {{
    $("screen").hidden = true;
    $("screen-placeholder").hidden = false;
    $("screen-placeholder").innerHTML =
      c.execute
        ? "Remote control works; this phone does not expose <code>/CGI/Screenshot</code> (or decode failed)."
        : "Connect and probe the phone.";
  }}
}}

async function api(path, body) {{
  const res = await fetch(path, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(body),
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

async function probe() {{
  saveSettings();
  setStatus("Probing…");
  try {{
    const data = await api("/api/probe", {{ phone: phonePayload() }});
    setCaps(data);
    setStatus(data.execute || data.screenshot ? "Ready." : "No HTTP CGI support detected.", data.execute ? "ok" : "err");
    if (data.screenshot) await refreshScreen(true);
  }} catch (e) {{
    setStatus(String(e.message || e), "err");
  }}
}}

async function refreshScreen(quiet) {{
  if (!caps.screenshot) return;
  if (!quiet) setStatus("Capturing…");
  try {{
    const res = await api("/api/screenshot", {{ phone: phonePayload() }});
    const blob = await res.blob();
    $("screen").src = URL.createObjectURL(blob) + "#" + Date.now();
    $("screen").hidden = false;
    $("screen-placeholder").hidden = true;
    if (!quiet) setStatus("Screen updated.", "ok");
  }} catch (e) {{
    setStatus(String(e.message || e), "err");
  }}
}}

async function runAction(action, extra) {{
  saveSettings();
  setStatus("Sending…");
  try {{
    await api("/api/action", {{ phone: phonePayload(), action, ...extra }});
    setStatus("OK: " + action, "ok");
    if (caps.screenshot) setTimeout(() => refreshScreen(true), 350);
  }} catch (e) {{
    setStatus(String(e.message || e), "err");
  }}
}}

function setupAutoRefresh() {{
  if (autoTimer) {{ clearInterval(autoTimer); autoTimer = null; }}
  if ($("auto-refresh").checked && caps.screenshot) {{
    autoTimer = setInterval(() => refreshScreen(true), 3000);
  }}
}}

$("btn-probe").addEventListener("click", probe);
$("btn-refresh").addEventListener("click", () => refreshScreen(false));
$("auto-refresh").addEventListener("change", setupAutoRefresh);
$("btn-dial").addEventListener("click", () => runAction("dial", {{ number: $("dial-number").value }}));
$("btn-press").addEventListener("click", () => runAction("press", {{ url: $("raw-url").value }}));

document.querySelectorAll("[data-action]").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const action = btn.dataset.action;
    if (action === "softkey") runAction("softkey", {{ index: parseInt(btn.dataset.index, 10) }});
    else if (action === "newcall") runAction("newcall", {{}});
    else if (action === "nav") runAction("nav", {{ direction: btn.dataset.dir }});
    else if (action === "hook") runAction("hook", {{ name: btn.dataset.name }});
  }});
}});

document.querySelectorAll("#keypad [data-key]").forEach(btn => {{
  btn.addEventListener("click", () => runAction("keys", {{ digits: btn.dataset.key }}));
}});

["ip","user","port","https","try-https"].forEach(id => {{
  $(id).addEventListener("change", saveSettings);
}});

loadSettings();
setCaps({{ screenshot: false, execute: false }});
</script>
</body>
</html>"""
    return body.encode("utf-8")


class _PhoneWebHandler(BaseHTTPRequestHandler):
    title: str = "Phone remote"

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("phone-web %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        path = urlparse(self.path or "/").path
        if path in ("/", "/index.html"):
            self._send_bytes(_page_html(title=self.title), "text/html; charset=utf-8")
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path or "/").path
        try:
            if path == "/api/probe":
                self._handle_probe()
            elif path == "/api/screenshot":
                self._handle_screenshot()
            elif path == "/api/action":
                self._handle_action()
            else:
                self._send_json(404, {"error": "not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError as exc:
            self._send_json(401, {"error": str(exc)})
        except ScreenshotNotSupportedError as exc:
            self._send_json(501, {"error": str(exc)})
        except Exception as exc:
            logger.exception("phone-web API error")
            self._send_json(500, {"error": str(exc)})

    def _phone_from_body(self) -> PhoneTarget:
        data = _read_json_body(self)
        phone_raw = data.get("phone")
        if not isinstance(phone_raw, dict):
            raise ValueError("phone object is required")
        return _parse_phone(phone_raw)

    def _handle_probe(self) -> None:
        phone = self._phone_from_body()
        result = probe_phone_http(phone.ip, phone.auth(), **phone.http_kwargs())
        self._send_json(200, result)

    def _handle_screenshot(self) -> None:
        phone = self._phone_from_body()
        png = fetch_screenshot_png_bytes(phone.ip, phone.auth(), **phone.http_kwargs())
        self._send_bytes(png, "image/png")

    def _handle_action(self) -> None:
        data = _read_json_body(self)
        phone = _parse_phone(data.get("phone") or {})
        action = str(data.get("action") or "").strip().lower()
        auth = phone.auth()
        http = phone.http_kwargs()

        if action == "softkey":
            softkey(phone.ip, int(data["index"]), auth, **http)
        elif action == "newcall":
            idx = int(data.get("index") or 2)
            softkey(phone.ip, idx, auth, **http)
        elif action == "keys":
            press_keys(phone.ip, str(data["digits"]), auth, **http)
        elif action == "dial":
            dial(phone.ip, str(data["number"]), auth, **http)
        elif action == "nav":
            nav(phone.ip, str(data["direction"]), auth, **http)
        elif action == "hook":
            hardkey(phone.ip, str(data["name"]), auth, **http)
        elif action == "press":
            _execute(phone.ip, [str(data["url"])], auth, **http)
        else:
            raise ValueError(f"unknown action: {action!r}")

        self._send_json(200, {"ok": True, "action": action})

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


def start_phone_web(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    title: str = "Phone remote",
) -> ThreadingHTTPServer:
    handler = type("_BoundPhoneWebHandler", (_PhoneWebHandler,), {"title": title})
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"phone-web-{port}",
        daemon=True,
    )
    thread.start()
    display_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    logger.info("Phone remote UI http://%s:%s/", display_host, port)
    return server


def run_server(host: str, port: int, *, title: str, block: bool = True) -> ThreadingHTTPServer:
    server = start_phone_web(host, port, title=title)
    if block:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        server.shutdown()
        server.server_close()
    return server
