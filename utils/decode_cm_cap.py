"""Decode key Skinny frames from cm_cap.pcapng (CUCM New Call reference)."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

from utils.skinny_messages import get_message_name

PCAP = Path(__file__).resolve().parents[1] / "cm_cap.pcapng"
TSHARK = r"c:\Program Files\Wireshark\tshark.exe"


def payload(frame: int) -> tuple[str, bytes | None]:
    out = subprocess.check_output(
        [
            TSHARK,
            "-r",
            str(PCAP),
            "-Y",
            f"frame.number=={frame}",
            "-T",
            "fields",
            "-e",
            "_ws.col.Info",
            "-e",
            "tcp.payload",
        ],
        text=True,
    ).strip()
    parts = out.split("\t")
    info = parts[0] if parts else ""
    if len(parts) < 2 or not parts[1]:
        return info, None
    return info, bytes.fromhex(parts[1].replace(":", ""))


def decode(frame: int) -> None:
    info, raw = payload(frame)
    if not raw:
        print(f"frame {frame}: {info} (no payload)")
        return
    dl, _ver, mid = struct.unpack("<III", raw[:12])
    body = raw[12:]
    name = get_message_name(mid)
    print(f"=== frame {frame} {info} ({name}) total={len(raw)} body={len(body)} ===")
    print(f"  body_hex: {body.hex()}")
    if mid == 0x0026 and len(body) >= 12:
        sk, line, ref = struct.unpack("<III", body[:12])
        print(f"  softkey={sk} line={line} ref={ref}")
    elif mid == 0x0111 and len(body) >= 12:
        st, line, ref = struct.unpack("<III", body[:12])
        print(f"  state={st} line={line} ref={ref} privacy={body[12:24].hex() if len(body)>=24 else ''}")
    elif mid == 0x0082:
        tone = struct.unpack("<I", body[:4])[0]
        print(f"  tone={tone} (0x{tone:x})")
        if len(body) >= 16:
            t, d, l, r = struct.unpack("<IIII", body[:16])
            print(f"  full: tone={t} dir={d} line={l} ref={r}")
    elif mid == 0x0088:
        print(f"  mode={struct.unpack('<I', body[:4])[0]}")
    elif mid == 0x0085 and len(body) >= 16:
        rm, rd, li, ref = struct.unpack("<IIII", body[:16])
        print(f"  ring_mode={rm} duration={rd} line={li} ref={ref}")
    elif mid == 0x0086 and len(body) >= 12:
        st, inst, lamp = struct.unpack("<III", body[:12])
        print(f"  stimulus={st} instance={inst} lamp_mode={lamp}")
    elif mid == 0x0110 and len(body) >= 16:
        li, ref, idx, mask = struct.unpack("<IIII", body[:16])
        print(f"  line={li} ref={ref} set_idx={idx} mask=0x{mask:08x}")
    elif mid == 0x0116:
        print(f"  line={struct.unpack('<I', body[:4])[0]}")
    print()


def main() -> int:
    frames = [79, 80, 81, 82, 83, 84, 85, 86, 87, 89, 90, 93]
    if len(sys.argv) > 1:
        frames = [int(x) for x in sys.argv[1:]]
    for f in frames:
        decode(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
