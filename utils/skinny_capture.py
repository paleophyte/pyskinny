"""
Run a short tshark capture and print Skinny message summaries (Windows lab helper).

Example (from repo root, sim running, phone registered):

  python -m utils.skinny_capture --host 10.102.10.209 --iface 2 --seconds 15

In another window while capture runs:

  python -m utils.phone_remote newcall
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time


def _find_tshark() -> str:
    env = os.environ.get("TSHARK", r"c:\Program Files\Wireshark\tshark.exe")
    if os.path.isfile(env):
        return env
    raise SystemExit(f"tshark not found at {env}; set TSHARK=...")


def capture(host: str, iface: str, seconds: int, port: int = 2000) -> str:
    tshark = _find_tshark()
    pcap = os.path.join(tempfile.gettempdir(), f"pyskinny-{host.replace('.', '-')}.pcapng")
    filt = f"host {host} and tcp port {port}"
    print(f"Capturing {seconds}s on interface {iface} filter '{filt}' -> {pcap}")
    subprocess.run(
        [tshark, "-i", iface, "-f", filt, "-w", pcap, "-a", f"duration:{seconds}", "-q"],
        check=False,
    )
    return pcap


def print_summary(pcap: str) -> None:
    tshark = _find_tshark()
    # Protocol column + info works across Wireshark versions
    proc = subprocess.run(
        [
            tshark,
            "-r",
            pcap,
            "-Y",
            "tcp.port==2000",
            "-T",
            "fields",
            "-e",
            "frame.number",
            "-e",
            "frame.time_relative",
            "-e",
            "_ws.col.Protocol",
            "-e",
            "_ws.col.Info",
        ],
        capture_output=True,
        text=True,
    )
    if proc.stdout.strip():
        print(proc.stdout)
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)

    print("\nStartTone payloads (hex):")
    proc2 = subprocess.run(
        [
            tshark,
            "-r",
            pcap,
            "-Y",
            "skinny && skinny.msg == 0x0082",
            "-T",
            "fields",
            "-e",
            "frame.number",
            "-e",
            "data.data",
        ],
        capture_output=True,
        text=True,
    )
    print(proc2.stdout or "(no StartTone / dissector did not decode)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Capture and summarize Skinny to a phone")
    p.add_argument("--host", required=True, help="Phone IP")
    p.add_argument("--iface", default=os.environ.get("TSHARK_IFACE", "2"))
    p.add_argument("--seconds", type=int, default=12)
    p.add_argument("--port", type=int, default=2000)
    args = p.parse_args(argv)
    pcap = capture(args.host, args.iface, args.seconds, args.port)
    if not os.path.isfile(pcap):
        print("No capture file written.", file=sys.stderr)
        return 1
    time.sleep(0.2)
    print_summary(pcap)
    print(f"\nFull capture: {pcap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
