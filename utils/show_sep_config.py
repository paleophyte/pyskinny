"""Show the SEP*.cnf.xml a phone would receive from simulator TFTP (after patching)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from simulator.tftp_config import is_cucm_sep_config, patch_sep_config_for_sim


def _web_access_note(value: str) -> str:
    if value == "0":
        return "web enabled (normal when CUCM Web Access checkbox is on)"
    if value == "1":
        return "WEB DISABLED — set to 0 and reboot phone to restore HTTP/CGI"
    if value == "2":
        return "web read-only"
    return "unknown value"


def materialize_sep(
    device_name: str,
    *,
    tftp_root: Path,
    cm_host: str,
    directory_number: str,
    skinny_port: int,
    cip_port: int,
) -> tuple[str, Path | None]:
    device_name = device_name.upper()
    if not device_name.startswith("SEP"):
        device_name = f"SEP{device_name}"
    path = tftp_root / f"{device_name}.cnf.xml"
    if not path.is_file():
        return "", None
    raw = path.read_text(encoding="utf-8", errors="replace")
    if is_cucm_sep_config(raw):
        text = patch_sep_config_for_sim(
            raw,
            cm_host=cm_host,
            directory_number=directory_number,
            skinny_port=skinny_port,
            cip_port=cip_port,
        )
    else:
        text = raw
    return text, path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Print patched SEP config as served by simulator TFTP",
    )
    p.add_argument("device", help="SEP MAC e.g. SEP001380AD9E5F or 001380AD9E5F")
    p.add_argument(
        "--tftp-root",
        type=Path,
        default=Path("simulator/tftp_assets"),
        help="TFTP root directory",
    )
    p.add_argument("--cm-host", default="10.102.172.11", help="Advertised CM/TFTP host")
    p.add_argument("--dn", default="1000", help="Directory number for line block")
    p.add_argument("--skinny-port", type=int, default=2000)
    p.add_argument("--cip-port", type=int, default=8088)
    args = p.parse_args(argv)

    text, path = materialize_sep(
        args.device,
        tftp_root=args.tftp_root,
        cm_host=args.cm_host,
        directory_number=args.dn,
        skinny_port=args.skinny_port,
        cip_port=args.cip_port,
    )
    if not path:
        print(f"No {args.device.upper()}.cnf.xml under {args.tftp_root}", file=sys.stderr)
        return 1

    print(f"# source: {path}")
    print(f"# patched for CM {args.cm_host}, DN {args.dn}")
    m = re.search(r"<webAccess>(\d+)</webAccess>", text)
    if m:
        print(f"# webAccess={m.group(1)} -> {_web_access_note(m.group(1))}")
    else:
        print("# webAccess tag not found")
    print()
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
