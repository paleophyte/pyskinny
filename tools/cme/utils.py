from .data_models import Snapshot
from dataclasses import asdict
import json
from typing import Optional, Tuple


# ========= Utility: JSON IO, allocation =========
def save_snapshot(path: str, snap: Snapshot):
    data = {
        "device": {
            "host": snap.device_host,
            "hostname": snap.device_hostname,
            "collected_at": snap.collected_at,
        },
        "config": asdict(snap.config),
        "dns": [asdict(d) for d in snap.dns],
        "ephones": [
            {
                "id": e.id,
                "mac": e.mac,
                "type": e.type,
                "security_mode": e.security_mode,
                "description": e.description,
                "buttons": [asdict(b) for b in (e.buttons or [])],
                "raw_config": e.raw_config,
            }
            for e in snap.ephones
        ],
        "telephony_service": (asdict(snap.telephony_service) if snap.telephony_service else None),
        "dial_peers": [asdict(dp) for dp in (snap.dial_peers or [])],
        "translation_rules": [asdict(r) for r in (snap.translation_rules or [])],
        "translation_profiles": [asdict(p) for p in (snap.translation_profiles or [])],
        "translation_refs": [asdict(ref) for ref in (snap.translation_refs or [])],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote snapshot to {path}")


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def current_ids(json_data: dict) -> Tuple[set, set, set]:
    dn_ids = {int(d["id"]) for d in json_data.get("dns", []) if "id" in d}
    ephone_ids = {int(e["id"]) for e in json_data.get("ephones", []) if "id" in e}
    used_dn_numbers = set()
    for d in json_data.get("dns", []):
        num = str(d.get("number") or "").strip()
        if num.isdigit():
            used_dn_numbers.add(int(num))
    return dn_ids, ephone_ids, used_dn_numbers


def next_available_int(used: set, start_from: int = 1) -> int:
    i = max(start_from, 1)
    while i in used:
        i += 1
    return i


def pick_next_dn_number(used_numbers: set, start: int, end: int, prefer: Optional[int] = None) -> int:
    if prefer is not None:
        if not (start <= prefer <= end):
            raise ValueError(f"Preferred DN number {prefer} not in range {start}-{end}.")
        if prefer in used_numbers:
            raise ValueError(f"Preferred DN number {prefer} already in use.")
        return prefer
    for n in range(start, end + 1):
        if n not in used_numbers:
            return n
    raise ValueError("No free DN numbers in configured range.")

