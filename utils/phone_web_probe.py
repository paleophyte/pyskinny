"""
Probe Cisco 79xx HTTP behavior (7912 often returns empty body on GET /).

Examples:
  python -m utils.phone_web_probe --ip 10.102.10.209
  python -m utils.phone_web_probe --ip 10.102.10.209 --user Administrator --password secret
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import quote_plus

import requests


def _probe(
    ip: str,
    path: str,
    *,
    auth: tuple[str, str] | None,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
) -> None:
    url = f"http://{ip}{path}"
    print(f"\n=== {method} {url} ===")
    try:
        if method == "GET":
            r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        else:
            r = requests.post(url, auth=auth, data=data, headers=headers or {}, timeout=timeout, verify=False)
    except requests.RequestException as exc:
        print(f"FAIL: {exc}")
        return
    print(f"status={r.status_code} len={len(r.content)}")
    if r.headers.get("Content-Type"):
        print(f"Content-Type: {r.headers['Content-Type']}")
    if r.content:
        preview = r.content[:200]
        try:
            print(preview.decode("utf-8", errors="replace"))
        except Exception:
            print(preview.hex())
    else:
        print("(empty body — common for GET / on 7912; try /CGI/Screenshot or /CGI/Execute)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Probe phone embedded HTTP / CGI endpoints")
    p.add_argument("--ip", required=True, help="Phone IP")
    p.add_argument("--user", help="HTTP basic auth user (optional)")
    p.add_argument("--password", default="", help="HTTP basic auth password")
    p.add_argument("--port", type=int, help="HTTP port if not 80")
    args = p.parse_args(argv)

    host = args.ip if not args.port else f"{args.ip}:{args.port}"
    auth = (args.user, args.password) if args.user else None

    print(
        "Note: 7912/7905 may return an empty TCP reply for GET /. "
        "That does not prove CGI is disabled — test /CGI/* below."
    )
    print(
        "webAccess in SEP*.cnf.xml: CUCM often stores 0 when the admin checkbox is ON "
        "(not a simple 0=off boolean). Legacy web enable is usually in gk* TFTP profiles "
        "(OpFlags bit 7 clear = web allowed)."
    )

    _probe(host, "/", auth=auth)
    _probe(host, "/CGI/Screenshot", auth=auth)
    _probe(host, "/CGI/Java/Serviceability?adapter=device.statistics.configuration", auth=auth)

    execute_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<CiscoIPPhoneExecute>"
        '<ExecuteItem Priority="0" URL="Key:Services"/>'
        "</CiscoIPPhoneExecute>"
    )
    form = "XML=" + quote_plus(execute_xml)
    _probe(
        host,
        "/CGI/Execute",
        auth=auth,
        method="POST",
        data=form.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
