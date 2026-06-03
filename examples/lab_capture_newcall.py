"""
Lab helper: capture Skinny to the physical phone, then trigger New Call.

Prerequisites:
  - simulator running (port 2000, TFTP 6969 + relay on 69)
  - PHONE_IP / PHONE_USER / PHONE_PASS for HTTP remote (optional)

  python -m examples.lab_capture_newcall --host 10.102.10.209 --iface 2
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time


def _run_capture(host: str, iface: str, seconds: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "utils.skinny_capture",
            "--host",
            host,
            "--iface",
            iface,
            "--seconds",
            str(seconds),
        ],
    )


def _run_newcall(host: str, delay: float) -> None:
    time.sleep(delay)
    ip = host
    user = os.environ.get("PHONE_USER", "Administrator")
    password = os.environ.get("PHONE_PASS", "")
    if not password:
        print("(skip newcall — set PHONE_PASS for HTTP remote)")
        return
    subprocess.run(
        [
            sys.executable,
            "-m",
            "utils.phone_remote",
            "--ip",
            ip,
            "--user",
            user,
            "--password",
            password,
            "newcall",
        ],
        check=False,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.environ.get("PHONE_IP", "10.102.10.209"))
    p.add_argument("--iface", default=os.environ.get("TSHARK_IFACE", "2"))
    p.add_argument("--seconds", type=int, default=18)
    p.add_argument("--delay", type=float, default=3.0, help="Seconds before newcall")
    args = p.parse_args(argv)

    print(f"Capturing {args.seconds}s; New Call at +{args.delay}s …")
    cap = _run_capture(args.host, args.iface, args.seconds)
    t = threading.Thread(target=_run_newcall, args=(args.host, args.delay), daemon=True)
    t.start()
    return cap.wait()


if __name__ == "__main__":
    sys.exit(main())
