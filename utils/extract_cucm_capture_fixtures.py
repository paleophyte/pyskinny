"""Regenerate tests/fixtures/cucm_frames.json from repo-root pcaps (requires tshark)."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "cucm_frames.json"
TSHARK = os.environ.get("TSHARK", r"c:\Program Files\Wireshark\tshark.exe")

# frame.number -> hex (single-frame groups, CM4.1 lab pcaps)
FRAME_GROUPS: dict[str, tuple[str, list[int]]] = {
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

# CM3.x registration: extract by message id from reassembled CM->phone TCP stream
CM3X_REG_GROUPS: dict[str, tuple[str, str, dict[str, int]]] = {
    "cm31_reg": (
        "cm31_register.pcapng",
        "10.0.0.181",
        {
            "config_stat": 0x0093,
            "button_template": 0x0097,
            "softkey_template": 0x0108,
            "line_stat": 0x0092,
            "time_date": 0x0094,
            "select_softkeys": 0x0110,
            "display": 0x0112,
        },
    ),
    "cm33_reg": (
        "cm33_register.pcapng",
        "10.0.0.182",
        {
            "config_stat": 0x0093,
            "button_template": 0x0097,
            "softkey_template": 0x0108,
            "line_stat": 0x0092,
            "time_date": 0x0094,
            "select_softkeys": 0x0110,
            "display": 0x0112,
        },
    ),
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


def reassemble_tcp_stream(pcap: Path, src_ip: str) -> bytes:
    out = subprocess.check_output(
        [
            TSHARK,
            "-r",
            str(pcap),
            "-Y",
            f"tcp.port==2000 && ip.src=={src_ip}",
            "-T",
            "fields",
            "-e",
            "tcp.seq",
            "-e",
            "tcp.payload",
        ],
        text=True,
    )
    chunks: list[tuple[int, bytes]] = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[1]:
            continue
        chunks.append((int(parts[0]), bytes.fromhex(parts[1].replace(":", ""))))
    if not chunks:
        return b""
    chunks.sort(key=lambda item: item[0])
    stream = bytearray()
    base = chunks[0][0]
    for seq, data in chunks:
        pos = seq - base
        end = pos + len(data)
        if end > len(stream):
            stream.extend(b"\x00" * (end - len(stream)))
        stream[pos : pos + len(data)] = data
    return bytes(stream)


def first_skinny_packet(stream: bytes, msg_id: int) -> bytes:
    for start in range(max(0, len(stream) - 12)):
        data_len, version, mid = struct.unpack_from("<III", stream, start)
        total = 4 + data_len
        if version != 0 or data_len < 4 or mid != msg_id:
            continue
        if start + total > len(stream):
            continue
        return stream[start : start + total]
    raise ValueError(f"message 0x{msg_id:04X} not found in stream ({len(stream)} bytes)")


def extract_cm3x_reg(pcap: Path, cm_ip: str, keys: dict[str, int]) -> dict[str, str]:
    stream = reassemble_tcp_stream(pcap, cm_ip)
    return {name: first_skinny_packet(stream, mid).hex() for name, mid in keys.items()}


def main() -> int:
    if not Path(TSHARK).is_file():
        print(f"tshark not found at {TSHARK}", file=sys.stderr)
        return 1

    out: dict[str, dict[str, str]] = {}

    for group, (pcap_name, frames) in FRAME_GROUPS.items():
        pcap = ROOT / pcap_name
        if not pcap.is_file():
            print(f"missing {pcap}", file=sys.stderr)
            return 1
        out[group] = {str(n): frame_hex(pcap, n) for n in frames}

    for group, (pcap_name, cm_ip, keys) in CM3X_REG_GROUPS.items():
        pcap = ROOT / pcap_name
        if not pcap.is_file():
            print(f"missing {pcap}", file=sys.stderr)
            return 1
        out[group] = extract_cm3x_reg(pcap, cm_ip, keys)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    count = sum(len(v) for v in out.values())
    print(f"Wrote {OUT} ({count} frames across {len(out)} groups)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
