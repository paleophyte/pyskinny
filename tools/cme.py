#!/usr/bin/env python3
import argparse
import json
import sys
import time
from typing import List, Optional

from netmiko import ConnectHandler
from netmiko.exceptions import NetMikoTimeoutException, NetMikoAuthenticationException

from cme.data_models import Snapshot, ConfigSection
from cme.parsers import parse_cme_sections, parse_translation_sections, parse_dial_peers, parse_telephony_service, snip_translation_region
from cme.utils import save_snapshot, load_json, pick_next_dn_number, current_ids


# ========= Netmiko session helper =========
class DeviceError(Exception):
    pass

class NetmikoSession:
    """
    Netmiko-backed CLI helper with SSH→Telnet fallback (or forced mode).
    """
    def __init__(self, host: str, username: str, password: str, secret: Optional[str],
                 transport: str = "auto", port: Optional[int] = None, timeout: int = 10,
                 session_log: Optional[str] = None):
        self.host = host
        self.username = username
        self.password = password
        self.secret = secret
        self.transport = transport  # 'auto' | 'ssh' | 'telnet'
        self.port = port
        self.timeout = timeout
        self.session_log = session_log
        self.conn = None

    def __enter__(self):
        self.conn = self._connect()
        # enter enable if needed
        try:
            if self.secret:
                self.conn.enable()
        except Exception:
            # if we're already in #, this is fine
            pass
        # disable paging
        try:
            self.send_command("terminal length 0")
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.conn:
                self.conn.disconnect()
        finally:
            self.conn = None

    def _connect(self):
        # try in selected order
        attempts = []
        order = []
        if self.transport == "ssh":
            order = ["ssh"]
        elif self.transport == "telnet":
            order = ["telnet"]
        else:
            order = ["ssh", "telnet"]

        last_exc = None
        for mode in order:
            try:
                params = {
                    "host": self.host,
                    "username": self.username,
                    "password": self.password,
                    "timeout": self.timeout,
                    "session_log": self.session_log,
                }
                if mode == "ssh":
                    params["device_type"] = "cisco_ios"
                    if self.port:
                        params["port"] = self.port
                else:
                    params["device_type"] = "cisco_ios_telnet"
                    if self.port:
                        params["port"] = self.port

                conn = ConnectHandler(**params)
                # On telnet, enable may still be needed; handled in __enter__
                return conn
            except (NetMikoTimeoutException, NetMikoAuthenticationException, OSError) as e:
                last_exc = e
                attempts.append((mode, str(e)))
                continue
        raise DeviceError(f"Connection failed via {', '.join(a for a,_ in attempts)}: {last_exc}")

    def prompt_hostname(self) -> Optional[str]:
        try:
            p = self.conn.find_prompt()
            # Expect something like 'Router#' or 'Router>'
            return p.rstrip("#>").strip()
        except Exception:
            return None

    def send_command(self, cmd: str, **kwargs) -> str:
        return self.conn.send_command(cmd, **kwargs)

    def send_config(self, commands: List[str], save: bool = False) -> str:
        out = self.conn.send_config_set(commands)
        if save:
            try:
                # IOS: 'write memory' or 'copy run start'
                try:
                    out += "\n" + self.conn.save_config()
                except Exception:
                    out += "\n" + self.conn.send_command_timing("write memory")
            except Exception:
                pass
        return out


# ========= collect =========
def cmd_collect(args):
    with NetmikoSession(
        host=args.host,
        username=args.username,
        password=args.password,
        secret=args.enable,
        transport=args.transport,
        port=args.port,
        timeout=args.timeout,
        session_log=args.session_log
    ) as sess:
        device_hostname = sess.prompt_hostname()
        ephone_text = sess.send_command("show run | sec ephone", read_timeout=args.timeout)
        dns, ephones = parse_cme_sections(ephone_text)

        ts_text = sess.send_command("show run | sec telephony-service", read_timeout=args.timeout)
        dp_text = sess.send_command("show run | sec dial-peer", read_timeout=args.timeout)
        telephony_service = parse_telephony_service(ts_text)
        dial_peers = parse_dial_peers(dp_text)

        tr_full = sess.send_command("show run | beg voice translation", read_timeout=args.timeout)
        tr_text = snip_translation_region(tr_full)
        translation_rules, translation_profiles, translation_refs = parse_translation_sections(tr_text)

        dn_ids = {d.id for d in dns}
        ephone_ids = {e.id for e in ephones}
        used_numbers = {int(d.number) for d in dns if str(d.number).isdigit()}

        cfg = ConfigSection(
            dn_range_start=args.dn_start,
            dn_range_end=args.dn_end,
            next_dn_number=(min(set(range(args.dn_start, args.dn_end + 1)) - used_numbers)
                            if (args.dn_start and args.dn_end) else None),
            next_ephone_id=(max(ephone_ids) + 1) if ephone_ids else 1,
            next_dn_id=(max(dn_ids) + 1) if dn_ids else 1,
        )

        snap = Snapshot(
            device_host=args.host,
            device_hostname=device_hostname,
            collected_at=time.time(),
            dns=dns,
            ephones=ephones,
            config=cfg,
            telephony_service=telephony_service,
            dial_peers=dial_peers or [],
            translation_rules = translation_rules or [],
            translation_profiles = translation_profiles or [],
            translation_refs = translation_refs or [],
        )
        save_snapshot(args.output, snap)


# ========= provision =========
def build_phone_config_commands(
    dn_id: int, dn_number: int, ephone_id: int, mac: str, phone_type: str, security_mode: str = "none"
) -> List[str]:
    return [
        f"ephone-dn  {dn_id}",
        f" number {dn_number}",
        "!",
        f"ephone  {ephone_id}",
        f" device-security-mode {security_mode}",
        f" mac-address {mac}",
        f" type {phone_type}",
        f" button  1:{dn_id}",
        "!"
    ]


def cmd_add_phone(args):
    data = load_json(args.json)
    cfg = data.get("config", {}) or {}
    dn_start = int(cfg.get("dn_range_start") or args.dn_start or 0)
    dn_end = int(cfg.get("dn_range_end") or args.dn_end or 0)
    if not (dn_start and dn_end and dn_end >= dn_start):
        raise SystemExit("DN range is not configured. Set it during collect or pass --dn-start/--dn-end here.")

    dn_ids, ephone_ids, used_dn_numbers = current_ids(data)

    # Allocate IDs and number
    next_dn_id = int(cfg.get("next_dn_id") or (max(dn_ids) + 1 if dn_ids else 1))
    next_ephone_id = int(cfg.get("next_ephone_id") or (max(ephone_ids) + 1 if ephone_ids else 1))
    dn_number = pick_next_dn_number(used_dn_numbers, dn_start, dn_end, prefer=args.dn_number)

    commands = build_phone_config_commands(
        dn_id=next_dn_id,
        dn_number=dn_number,
        ephone_id=next_ephone_id,
        mac=args.mac.lower(),
        phone_type=args.model,
        security_mode=args.security_mode,
    )

    print("\n--- Proposed configuration ---")
    for c in commands:
        print(c)
    print("------------------------------\n")

    if args.dry_run:
        print("Dry-run: no changes pushed.")
    else:
        with NetmikoSession(
            host=args.host,
            username=args.username,
            password=args.password,
            secret=args.enable,
            transport=args.transport,
            port=args.port,
            timeout=args.timeout,
            session_log=args.session_log
        ) as sess:
            sess.send_config(commands, save=args.commit)
            print("Configuration pushed.")

    # Update JSON on disk (can be skipped with --no-update-json)
    if not args.no_update_json:
        data.setdefault("dns", []).append({"id": next_dn_id, "number": str(dn_number)})
        data.setdefault("ephones", []).append({
            "id": next_ephone_id,
            "mac": args.mac.lower(),
            "type": args.model,
            "security_mode": args.security_mode,
            "buttons": [{"line": 1, "dn_id": next_dn_id}],
        })
        used_dn_numbers.add(dn_number)
        data.setdefault("config", {})
        data["config"]["next_dn_id"] = next_dn_id + 1
        data["config"]["next_ephone_id"] = next_ephone_id + 1
        try:
            data["config"]["next_dn_number"] = pick_next_dn_number(used_dn_numbers, dn_start, dn_end)
        except ValueError:
            data["config"]["next_dn_number"] = None
        if "dn_range_start" not in data["config"]:
            data["config"]["dn_range_start"] = dn_start
        if "dn_range_end" not in data["config"]:
            data["config"]["dn_range_end"] = dn_end

        with open(args.json, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Updated {args.json}.")


# ========= CLI =========
def build_parser():
    p = argparse.ArgumentParser(
        description="CME helper (collect CME state + add phones/ephone-dn) using Netmiko.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    p.add_argument("--host", required=True, help="Router IP/hostname")
    p.add_argument("--port", type=int, default=None, help="Optional port override")
    p.add_argument("--username", required=True, help="Login username")
    p.add_argument("--password", required=True, help="Login password")
    p.add_argument("--enable", default=None, help="Enable password (optional)")
    p.add_argument("--timeout", type=int, default=10, help="Session timeout (seconds)")
    p.add_argument("--transport", choices=["auto", "ssh", "telnet"], default="auto",
                   help="Transport selection (auto tries SSH then Telnet)")
    p.add_argument("--session-log", default=None, help="Path to write raw session log (Netmiko)")

    sub = p.add_subparsers(dest="cmd", required=True)

    # collect
    sp = sub.add_parser("collect", help="Collect ephone/ephone-dn info to JSON")
    sp.add_argument("-o", "--output", default="cme_snapshot.json", help="Output JSON path")
    sp.add_argument("--dn-start", type=int, default=None, help="Configure DN start (stored in JSON config)")
    sp.add_argument("--dn-end", type=int, default=None, help="Configure DN end (stored in JSON config)")
    sp.set_defaults(func=cmd_collect)

    # add-phone
    sp2 = sub.add_parser("add-phone", help="Add a new ephone-dn + ephone")
    sp2.add_argument("--json", default="cme_snapshot.json", help="Snapshot JSON path")
    sp2.add_argument("--mac", required=True, help="Phone MAC (e.g., 4444.5555.6666)")
    sp2.add_argument("--model", required=True, help="Phone type/model (e.g., 7970, CIPC)")
    sp2.add_argument("--security-mode", default="none", help="device-security-mode (default: none)")
    sp2.add_argument("--dn-number", type=int, default=None, help="Preferred DN number (must be in range and free)")
    sp2.add_argument("--dn-start", type=int, default=None, help="Override DN start if not in JSON")
    sp2.add_argument("--dn-end", type=int, default=None, help="Override DN end if not in JSON")
    sp2.add_argument("--commit", action="store_true", help="Write memory after configuring")
    sp2.add_argument("--dry-run", action="store_true", help="Show config, do not push")
    sp2.add_argument("--no-update-json", action="store_true", help="Do not update JSON after run")
    sp2.set_defaults(func=cmd_add_phone)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (NetMikoTimeoutException, NetMikoAuthenticationException) as e:
        print(f"[netmiko] {e}", file=sys.stderr)
        sys.exit(2)
    except DeviceError as e:
        print(f"[device] {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
