"""Regenerate tests/fixtures/cucm_frames.json from repo-root pcaps (requires tshark)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "cucm_frames.json"
TSHARK = os.environ.get("TSHARK", r"c:\Program Files\Wireshark\tshark.exe")

GROUPS: dict[str, tuple[str, list[int]]] = {
    "cm_cap_new_call": ("cm_cap.pcapng", [80, 81, 82, 83, 84, 85, 86, 87]),
    "cm_cap_reg_idle": ("cm_cap.pcapng", [45, 46]),
    "cm_cap_reg_ready": ("cm_cap.pcapng", [63]),
    "cm_cap_assets": ("cm_cap.pcapng", [40, 43, 50]),
    "cm_call_ring": ("cm_call_from_pyskinny_to_7912.pcapng", [132, 133, 134, 135, 137, 138]),
    "cm_call_answer": (
        "cm_call_from_pyskinny_to_7912.pcapng",
        [141, 142, 143, 144, 145, 146, 147, 150, 151],
    ),
    "cm_call_open_rx": ("cm_call_from_pyskinny_to_7912.pcapng", [148]),
    "cm_call_media": ("cm_call_from_pyskinny_to_7912.pcapng", [154, 155]),
}


def frame_hex(pcap: Path, number: int) -> str:
    out = subprocess.check_output(
        [
            TSHARK,
            "-r",
            str(pcap),
            "-Y",
            f"frame.number=={number}",
            "-T",
            "fields",
            "-e",
            "tcp.payload",
        ],
        text=True,
    ).strip()
    return out.replace(":", "")


def main() -> int:
    if not Path(TSHARK).is_file():
        print(f"tshark not found at {TSHARK}", file=sys.stderr)
        return 1

    out: dict[str, dict[str, str]] = {}
    for group, (pcap_name, frames) in GROUPS.items():
        pcap = ROOT / pcap_name
        if not pcap.is_file():
            print(f"missing {pcap}", file=sys.stderr)
            return 1
        out[group] = {str(n): frame_hex(pcap, n) for n in frames}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    count = sum(len(v) for v in out.values())
    print(f"Wrote {OUT} ({count} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
