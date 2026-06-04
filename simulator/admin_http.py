"""Simple web admin for the Skinny simulator (phone list, tonreset, restart)."""

from __future__ import annotations

import html
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Callable
from urllib.parse import quote, unquote, urlparse

if TYPE_CHECKING:
    from simulator.call_hub import CallHub
    from simulator.registry import DeviceRegistry
    from simulator.tftp_service import TftpConfigService

logger = logging.getLogger(__name__)

_ProvisionFn = Callable[[str], str]


class _AdminContext:
    def __init__(
        self,
        *,
        hub: CallHub,
        registry: DeviceRegistry,
        tftp: TftpConfigService | None,
        provision: _ProvisionFn | None,
        server_name: str,
    ):
        self.hub = hub
        self.registry = registry
        self.tftp = tftp
        self.provision = provision
        self.server_name = server_name


def _admin_page(ctx: _AdminContext) -> bytes:
    phones = ctx.hub.snapshot_sessions()
    assigned = ctx.registry.snapshot()
    rows = []
    for phone in phones:
        dev = html.escape(phone["device"])
        dn = html.escape(phone["dn"] or "—")
        ip = html.escape(phone["ip"])
        state = html.escape(phone["call_state"])
        in_call = "yes" if phone["in_call"] else "no"
        rows.append(
            f"<tr>"
            f"<td><code>{dev}</code></td>"
            f"<td>{dn}</td>"
            f"<td>{ip}</td>"
            f"<td>{state}</td>"
            f"<td>"
            f'<form method="post" action="/phones/{dev}/tonreset" style="display:inline">'
            f'<button type="submit">Ton reset</button></form> '
            f'<form method="post" action="/phones/{dev}/restart" style="display:inline">'
            f'<button type="submit">Restart</button></form> '
            f'<form method="post" action="/phones/{dev}/end-call" style="display:inline">'
            f'<button type="submit"{" disabled" if not phone["in_call"] else ""}>End call</button></form>'
            f"</td>"
            f"</tr>"
        )

    provision_rows = []
    for device, dn in sorted(assigned.items()):
        dev = html.escape(device)
        provision_rows.append(
            f"<tr><td><code>{dev}</code></td><td>{html.escape(dn)}</td>"
            f'<td><form method="post" action="/phones/{dev}/provision" style="display:inline">'
            f'<button type="submit">Re-provision TFTP</button></form></td></tr>'
        )

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(ctx.server_name)} — phones</title>
<meta http-equiv="refresh" content="5">
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; margin: 1rem 0; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.7rem; text-align: left; }}
th {{ background: #f4f4f4; }}
button {{ cursor: pointer; }}
code {{ font-size: 0.95em; }}
h2 {{ margin-top: 2rem; }}
</style>
</head>
<body>
<h1>{html.escape(ctx.server_name)} — registered phones</h1>
<p>Auto-refreshes every 5s. <a href="/api/phones">JSON</a></p>
<table>
<thead><tr><th>Device</th><th>DN</th><th>IP</th><th>Call</th><th>Actions</th></tr></thead>
<tbody>
{"".join(rows) if rows else "<tr><td colspan='5'><em>No phones registered yet.</em></td></tr>"}
</tbody>
</table>
<h2>DN assignments (TFTP)</h2>
<table>
<thead><tr><th>Device</th><th>DN</th><th></th></tr></thead>
<tbody>
{"".join(provision_rows) if provision_rows else "<tr><td colspan='3'><em>None provisioned yet.</em></td></tr>"}
</tbody>
</table>
</body>
</html>
"""
    return body.encode("utf-8")


class _AdminHandler(BaseHTTPRequestHandler):
    ctx: _AdminContext | None = None

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("Admin %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        ctx = self.ctx
        if ctx is None:
            self._send_json(503, {"error": "admin not ready"})
            return
        path = urlparse(self.path or "").path
        if path in ("/", "/index.html"):
            self._send_bytes(_admin_page(ctx), "text/html; charset=utf-8")
            return
        if path == "/api/phones":
            payload = {
                "phones": ctx.hub.snapshot_sessions(),
                "assignments": ctx.registry.snapshot(),
            }
            self._send_json(200, payload)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        ctx = self.ctx
        if ctx is None:
            self._send_json(503, {"error": "admin not ready"})
            return
        path = urlparse(self.path or "").path
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "phones":
            device = unquote(parts[1])
            action = parts[2]
            ok, msg = self._run_action(ctx, device, action)
            accept = self.headers.get("Accept", "")
            if "application/json" in accept:
                status = 200 if ok else 404
                self._send_json(status, {"ok": ok, "message": msg})
                return
            loc = "/" if ok else f"/?error={quote(msg)}"
            self.send_response(303 if ok else 400)
            self.send_header("Location", loc)
            self.end_headers()
            return
        self._send_json(404, {"error": "not found"})

    def _run_action(self, ctx: _AdminContext, device: str, action: str) -> tuple[bool, str]:
        if action == "tonreset":
            ok = ctx.hub.ton_reset(device)
            return ok, "tonreset" if ok else "device not registered"
        if action == "restart":
            ok = ctx.hub.restart_session(device)
            return ok, "restart" if ok else "device not registered"
        if action == "end-call":
            ok = ctx.hub.end_call_for_device(device)
            return ok, "end-call" if ok else "no active call"
        if action == "provision":
            if ctx.provision is None:
                return False, "TFTP disabled"
            dn = ctx.provision(device)
            return True, f"provisioned DN {dn}"
        return False, "unknown action"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_admin_http(
    host: str,
    port: int,
    *,
    hub: CallHub,
    registry: DeviceRegistry,
    tftp: TftpConfigService | None = None,
    provision: _ProvisionFn | None = None,
    server_name: str = "SkinnySim",
) -> ThreadingHTTPServer:
    ctx = _AdminContext(
        hub=hub,
        registry=registry,
        tftp=tftp,
        provision=provision,
        server_name=server_name,
    )
    handler = type("_BoundAdminHandler", (_AdminHandler,), {"ctx": ctx})
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"admin-http-{port}",
        daemon=True,
    )
    thread.start()
    logger.info(
        "Simulator admin UI http://%s:%s/ (tonreset, restart, end-call, provision)",
        host if host != "0.0.0.0" else "127.0.0.1",
        port,
    )
    return server
