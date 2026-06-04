"""Decode CUCM ring-in frames from cm_call_from_pyskinny_to_7912.pcapng."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

from utils.skinny_messages import get_message_name

PCAP = Path(__file__).resolve().parents[1] / "cm_call_from_pyskinny_to_7912.pcapng"
TSHARK = r"c:\Program Files\Wireshark\tshark.exe"


def main() -> None:
    for n in range(130, 156):
        out = subprocess.check_output(
            [
                TSHARK,
                "-r",
                str(PCAP),
                "-Y",
                f"frame.number=={n}",
                "-T",
                "fields",
                "-e",
                "ip.dst",
                "-e",
                "tcp.payload",
            ],
            text=True,
        ).strip()
        parts = out.split("\t")
        if len(parts) < 2 or not parts[1]:
            continue
        raw = bytes.fromhex(parts[1].replace(":", ""))
        if len(raw) < 12:
            continue
        mid = struct.unpack("<I", raw[8:12])[0]
        body = raw[12:]
        name = get_message_name(mid)
        dst = parts[0].rsplit(".", 1)[-1]
        extra = ""
        if mid == 0x0111 and len(body) >= 12:
            st, line, ref = struct.unpack("<III", body[:12])
            extra = f"state={st} line={line} ref={ref}"
        elif mid == 0x0085 and len(body) >= 16:
            extra = repr(struct.unpack("<IIII", body[:16]))
        elif mid == 0x0086 and len(body) >= 12:
            extra = repr(struct.unpack("<III", body[:12]))
        elif mid == 0x0088 and len(body) >= 4:
            extra = f"mode={struct.unpack('<I', body[:4])[0]}"
        elif mid == 0x0110 and len(body) >= 12:
            extra = repr(struct.unpack("<III", body[:12]))
        print(f"{n} -> {dst} {name} {extra}")


if __name__ == "__main__":
    main()
