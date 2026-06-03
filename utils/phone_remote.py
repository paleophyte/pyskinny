"""
Lab CLI for Cisco 79xx phone control via HTTP CGI (Execute / Screenshot).

This is a thin wrapper around ``tools.phone`` — the HTTP/CGI implementation lives
there. Use this module for simulator-lab ergonomics (env vars, subcommands,
interactive REPL, capture-hint). Use ``tools.phone`` directly if importing from
Python code.

Examples:
  set PHONE_IP=10.102.10.209
  set PHONE_USER=Administrator
  set PHONE_PASS=secret

  python -m utils.phone_remote screenshot -o screen.png
  python -m utils.phone_remote softkey 2          # Soft2 (often New Call on 7912)
  python -m utils.phone_remote keys 1001
  python -m utils.phone_remote newcall
  python -m utils.phone_remote interactive

  python -m utils.phone_remote press Key:Speaker
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from tools.phone import (
    dial as phone_dial,
    fetch_screenshot,
    hardkey,
    nav,
    press_keys,
    softkey as phone_softkey,
    _execute,
)

# 7912 on-hook layout varies by firmware; Soft2 is commonly "New Call"
DEFAULT_NEW_CALL_SOFTKEY = int(os.environ.get("PHONE_NEW_CALL_SOFTKEY", "2"))
_env_port = os.environ.get("PHONE_PORT")
DEFAULT_PORT = int(_env_port) if _env_port else None


def _auth(user: str | None, password: str | None) -> tuple[str, str] | None:
    if user:
        return (user, password or "")
    return None


def _http_kwargs(
    *,
    use_https: bool = False,
    try_https_fallback: bool = False,
    port: int | None = None,
) -> dict:
    return {
        "use_https": use_https,
        "try_https_fallback": try_https_fallback,
        "port": port,
    }


def _phone_ip(ip: str | None) -> str:
    host = ip or os.environ.get("PHONE_IP", "")
    if not host:
        raise SystemExit("Set --ip or PHONE_IP")
    return host


def press_url(
    ip: str,
    url: str,
    *,
    user: str | None = None,
    password: str | None = None,
    delay: float = 0,
    use_https: bool = False,
    try_https_fallback: bool = False,
    port: int | None = None,
) -> bool:
    """Send one CiscoIPPhoneExecute URL (e.g. Key:Soft2, Key:KeyPad5)."""
    auth = _auth(user, password)
    _execute(
        ip,
        [url],
        auth,
        use_https=use_https,
        try_https_fallback=try_https_fallback,
        port=port,
    )
    if delay:
        time.sleep(delay)
    return True


def press_keys_seq(
    ip: str,
    keys: list[str],
    *,
    delay: float = 0.35,
    user: str | None = None,
    password: str | None = None,
) -> None:
    for key in keys:
        press_url(ip, key, user=user, password=password)
        time.sleep(delay)


def new_call(
    ip: str,
    *,
    softkey_index: int = DEFAULT_NEW_CALL_SOFTKEY,
    user: str | None = None,
    password: str | None = None,
    use_https: bool = False,
    try_https_fallback: bool = False,
    port: int | None = None,
) -> None:
    """Press the softkey that maps to New Call on 7912-class phones."""
    phone_softkey(
        ip,
        softkey_index,
        _auth(user, password),
        use_https=use_https,
        try_https_fallback=try_https_fallback,
        port=port,
    )


def screenshot(
    ip: str,
    path: str,
    *,
    user: str | None = None,
    password: str | None = None,
    use_https: bool = False,
    try_https_fallback: bool = False,
    port: int | None = None,
) -> str | None:
    auth = _auth(user, password)
    _data, _ext, saved = fetch_screenshot(
        ip,
        auth=auth,
        save_as=path,
        use_https=use_https,
        try_https_fallback=try_https_fallback,
        port=port,
    )
    return saved


def interactive_loop(
    ip: str,
    *,
    user: str | None = None,
    password: str | None = None,
    use_https: bool = False,
    try_https_fallback: bool = False,
    port: int | None = None,
) -> None:
    """Minimal REPL for lab troubleshooting."""
    help_text = """
Commands:
  screenshot [file]     capture LCD (default phone_screen.png)
  softkey <1-4>         Soft1..Soft4
  newcall               default new-call softkey (PHONE_NEW_CALL_SOFTKEY)
  keys <digits>         dial digits e.g. keys 1001#
  dial <digits>         Dial: URL if supported, else keypad
  press <Key:...>       raw Execute URL
  nav up|down|left|right|select|back
  hook speaker|headset|mute
  help
  quit
"""
    print(help_text.strip())
    http = _http_kwargs(
        use_https=use_https,
        try_https_fallback=try_https_fallback,
        port=port,
    )
    while True:
        try:
            line = input("phone> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]
        try:
            if cmd in ("q", "quit", "exit"):
                break
            if cmd == "help":
                print(help_text)
            elif cmd == "screenshot":
                path = args[0] if args else "phone_screen.png"
                out = screenshot(ip, path, user=user, password=password, **http)
                print(f"saved {out}")
            elif cmd == "softkey":
                phone_softkey(ip, int(args[0]), _auth(user, password), **http)
            elif cmd == "newcall":
                new_call(ip, user=user, password=password, **http)
            elif cmd == "keys":
                press_keys(ip, args[0], _auth(user, password), **http)
            elif cmd == "dial":
                phone_dial(ip, args[0], _auth(user, password), **http)
            elif cmd == "press":
                press_url(ip, args[0], user=user, password=password, **http)
            elif cmd == "nav":
                nav(ip, args[0], _auth(user, password), **http)
            elif cmd == "hook":
                hardkey(ip, args[0], _auth(user, password), **http)
            else:
                print("unknown command; type help")
        except Exception as exc:
            print(f"error: {exc}")


def _add_auth_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ip", default=os.environ.get("PHONE_IP"), help="Phone IP (or PHONE_IP)")
    p.add_argument("--user", default=os.environ.get("PHONE_USER"), help="Web username (PHONE_USER)")
    p.add_argument("--password", default=os.environ.get("PHONE_PASS"), help="Web password (PHONE_PASS)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port (or PHONE_PORT; default 80)")
    p.add_argument("--https", action="store_true", help="Use HTTPS only (default: plain HTTP)")
    p.add_argument(
        "--try-https",
        action="store_true",
        help="If HTTP fails, also try HTTPS (legacy behavior)",
    )
    p.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress success messages",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cisco 79xx phone remote control (HTTP CGI) for lab troubleshooting",
    )
    _add_auth_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ss = sub.add_parser("screenshot", help="Save LCD screenshot")
    p_ss.add_argument("-o", "--output", default="phone_screen.png")

    p_sk = sub.add_parser("softkey", help="Press Soft1..Soft4")
    p_sk.add_argument("index", type=int, choices=(1, 2, 3, 4))

    sub.add_parser("newcall", help="Press New Call softkey (default Soft2)")

    p_keys = sub.add_parser("keys", help="Send keypad digits")
    p_keys.add_argument("digits")

    p_dial = sub.add_parser("dial", help="Dial a number")
    p_dial.add_argument("number")

    p_press = sub.add_parser("press", help="Raw Execute URL")
    p_press.add_argument("url")

    p_nav = sub.add_parser("nav", help="Navigation key")
    p_nav.add_argument("direction", choices=["up", "down", "left", "right", "select", "back"])

    p_hook = sub.add_parser("hook", help="Speaker/headset/mute/etc.")
    p_hook.add_argument("name", choices=["speaker", "headset", "mute", "messages", "services", "directories", "settings"])

    sub.add_parser("interactive", help="Interactive REPL")

    p_cap = sub.add_parser("capture-hint", help="Print tshark capture instructions")
    p_cap.add_argument("--iface", default=os.environ.get("TSHARK_IFACE", "2"))

    args = parser.parse_args(argv)
    ip = _phone_ip(args.ip)
    auth_user, auth_pass = args.user, args.password
    http = _http_kwargs(
        use_https=args.https,
        try_https_fallback=args.try_https,
        port=args.port,
    )

    def _ok(label: str) -> None:
        if not args.quiet:
            auth_note = ""
            if auth_user and not args.password:
                auth_note = " (no password set)"
            elif not auth_user:
                auth_note = " (no auth — phone may allow unauthenticated CGI)"
            print(f"OK: {label} on {ip}{auth_note}")

    if args.command == "screenshot":
        out = screenshot(ip, args.output, user=auth_user, password=auth_pass, **http)
        if not args.quiet:
            print(out or args.output)
    elif args.command == "softkey":
        phone_softkey(ip, args.index, _auth(auth_user, auth_pass), **http)
        _ok(f"Soft{args.index}")
    elif args.command == "newcall":
        new_call(ip, user=auth_user, password=auth_pass, **http)
        _ok(f"New Call (Soft{DEFAULT_NEW_CALL_SOFTKEY})")
    elif args.command == "keys":
        press_keys(ip, args.digits, _auth(auth_user, auth_pass), **http)
        _ok(f"keys {args.digits}")
    elif args.command == "dial":
        phone_dial(ip, args.number, _auth(auth_user, auth_pass), **http)
        _ok(f"dial {args.number}")
    elif args.command == "press":
        press_url(ip, args.url, user=auth_user, password=auth_pass, **http)
        _ok(args.url)
    elif args.command == "nav":
        nav(ip, args.direction, _auth(auth_user, auth_pass), **http)
    elif args.command == "hook":
        hardkey(ip, args.name, _auth(auth_user, auth_pass), **http)
    elif args.command == "interactive":
        interactive_loop(ip, user=auth_user, password=auth_pass, **http)
    elif args.command == "capture-hint":
        print(
            f"Terminal 1:\n  python -m utils.skinny_capture --host {ip} --iface {args.iface}\n\n"
            f"Terminal 2:\n  python -m utils.phone_remote --ip {ip} newcall\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
