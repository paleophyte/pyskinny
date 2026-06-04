"""Extract CM2 Skinny payloads from a live-registration pcap (tshark + tcp.payload).

Capture example (interface 2 = Ethernet0 on lab PC):

  tshark -i 2 -f "host <CM2_IP> and tcp port 2000" -w tools/cm2_register.pcapng

While pyskinny registers:

  python -c "from client import SCCPClient; from state import PhoneState; ..."

Then:

  python -m utils.extract_cm2_assets tools/cm2_register.pcapng
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

TSHARK = r"c:\Program Files\Wireshark\tshark.exe"
OUT = Path(__file__).resolve().parents[1] / "simulator" / "cm2_assets.py"

MSG_NAMES = {
    0x0081: "CM2_REGISTER_ACK",
    0x0093: "CM2_CONFIG_STAT_RES",
    0x0092: "CM2_LINE_STAT_RES",
    0x0094: "CM2_TIME_DATE_RES",
    0x0097: "CM2_BUTTON_TEMPLATE_RES",
}


def _tshark_payloads(pcap: Path, *, from_server: str | None = None) -> list[bytes]:
    filt = "tcp.port==2000 && tcp.payload"
    if from_server:
        filt += f" && ip.src=={from_server}"
    out = subprocess.check_output(
        [
            TSHARK,
            "-r",
            str(pcap),
            "-Y",
            filt,
            "-T",
            "fields",
            "-e",
            "frame.number",
            "-e",
            "tcp.payload",
        ],
        text=True,
    )
    chunks: list[tuple[int, bytes]] = []
    for line in out.strip().splitlines():
        frame_s, hexpayload = line.split("\t", 1)
        if not hexpayload:
            continue
        chunks.append((int(frame_s), bytes.fromhex(hexpayload.replace(":", ""))))
    chunks.sort(key=lambda item: item[0])
    return [blob for _, blob in chunks]


def _iter_skinny_packets(chunks: list[bytes]) -> list[tuple[int, bytes]]:
    found: list[tuple[int, bytes]] = []
    for chunk in chunks:
        off = 0
        while off + 12 <= len(chunk):
            data_length, version, msg_id = struct.unpack_from("<III", chunk, off)
            if version != 0 or data_length < 4 or data_length > 4096:
                off += 1
                continue
            total = 4 + data_length
            if off + total > len(chunk):
                break
            found.append((msg_id, chunk[off : off + total]))
            off += total
    return found


def _dedupe_by_msg_id(packets: list[tuple[int, bytes]]) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for msg_id, blob in packets:
        out.setdefault(msg_id, blob)
    return out


def _write_assets(assets: dict[int, bytes], *, source: Path) -> None:
    lines = [
        f'"""Skinny payloads captured from Selsius CM2 ({source.name})."""',
        "from __future__ import annotations",
        "",
    ]
    for msg_id, blob in sorted(assets.items(), key=lambda item: MSG_NAMES.get(item[0], hex(item[0]))):
        name = MSG_NAMES.get(msg_id)
        if not name:
            continue
        lines.append(f"{name} = bytes.fromhex(")
        lines.append(f'    "{blob.hex()}"')
        lines.append(")")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")
    for msg_id, blob in sorted(assets.items(), key=lambda item: item[0]):
        label = MSG_NAMES.get(msg_id, hex(msg_id))
        print(f"  {label}: {len(blob)} bytes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract CM2 Skinny blobs from a pcap")
    parser.add_argument("pcap", type=Path, help="pcap/pcapng from tshark")
    parser.add_argument(
        "--server",
        default="10.0.0.11",
        help="CM2 server IP (only frames from this host are scanned)",
    )
    args = parser.parse_args(argv)

    if not args.pcap.is_file():
        print(f"Missing pcap: {args.pcap}", file=sys.stderr)
        return 1

    chunks = _tshark_payloads(args.pcap, from_server=args.server)
    packets = _iter_skinny_packets(chunks)
    assets = _dedupe_by_msg_id(packets)
    if 0x0097 not in assets:
        print("No ButtonTemplateRes (0x0097) found in server payloads", file=sys.stderr)
        return 1
    _write_assets(assets, source=args.pcap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
