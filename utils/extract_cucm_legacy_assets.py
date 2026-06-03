"""One-off: extract legacy 7912 payloads from cm_cap.pcapng."""

from __future__ import annotations

import subprocess
from pathlib import Path

TSHARK = r"c:\Program Files\Wireshark\tshark.exe"
PCAP = Path(__file__).resolve().parents[1] / "cm_cap.pcapng"
OUT = Path(__file__).resolve().parents[1] / "simulator" / "cucm_legacy_assets.py"


def frame_bytes(n: int) -> bytes:
    out = subprocess.check_output(
        [TSHARK, "-r", str(PCAP), "-Y", f"frame.number=={n}", "-T", "fields", "-e", "tcp.payload"],
        text=True,
    ).strip()
    return bytes.fromhex(out.replace(":", ""))


def main() -> None:
    assets = {
        "LEGACY_SOFTKEY_TEMPLATE_RES": frame_bytes(40),
        "LEGACY_SOFTKEY_SET_RES": frame_bytes(43),
        "LEGACY_SELECT_SOFTKEYS_IDLE": frame_bytes(45),
        "LEGACY_DISPLAY_PROMPT_IDLE": frame_bytes(46),
        "LEGACY_DISPLAY_PROMPT_READY": frame_bytes(63),
        "LEGACY_SELECT_SOFTKEYS_ONHOOK": frame_bytes(94),
        "LEGACY_FEATURE_STAT_RES": frame_bytes(50),
    }
    lines = [
        '"""CUCM-captured Skinny payloads for Cisco 7912 (from cm_cap.pcapng)."""',
        "from __future__ import annotations",
        "",
    ]
    for name, blob in assets.items():
        lines.append(f"{name} = bytes.fromhex(")
        lines.append(f'    "{blob.hex()}"')
        lines.append(")")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT} ({', '.join(f'{k}={len(v)}' for k, v in assets.items())})")


if __name__ == "__main__":
    main()
