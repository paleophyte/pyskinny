import socket
import struct
import string
import re
import json
import os
import math


_PRIMITIVES = (str, int, float, bool, type(None))


def get_local_ip(cucm_host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((cucm_host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def ip_to_int(ip_str):
    return struct.unpack("!I", socket.inet_aton(ip_str))[0]


def clean_bytes(b: bytes) -> str:
    # Truncate at first null, decode only up to that point
    b = b.split(b'\x00', 1)[0]
    return ''.join(chr(c) for c in b if chr(c) in string.printable).strip()


def normalize_mac_address(mac: str) -> str:
    """Normalize a MAC address to a 12-character uppercase hex string without separators."""
    # Remove colons, dots, hyphens, and spaces
    cleaned = re.sub(r'[^0-9a-fA-F]', '', mac)
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address format: {mac}")
    return cleaned.upper()


def _is_json_number(x):
    # json allows inf/NaN only if allow_nan=True (default). If you want strict, flag them.
    return isinstance(x, (int, float)) and (math.isfinite(x) or True)


def find_unserializable(obj, path="root"):
    """
    Yield (path, value, reason) for fields that the standard json module can't serialize.
    """
    # Primitive ok?
    if isinstance(obj, _PRIMITIVES):
        # If you run with allow_nan=False later, flag NaN/inf here:
        # if isinstance(obj, float) and not math.isfinite(obj):
        #     yield (path, obj, "non-finite float (NaN/Inf)")
        return

    # bytes-like?
    if isinstance(obj, (bytes, bytearray, memoryview)):
        yield (path, obj, "bytes-like value")
        return

    # dict: keys must be str; values checked recursively
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                yield (f"{path}[{repr(k)}]", k, "non-string dict key")
            yield from find_unserializable(v, f"{path}.{k}")
        return

    # list/tuple
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from find_unserializable(v, f"{path}[{i}]")
        return

    # anything else (set, Decimal, custom objects, datetime, etc.)
    yield (path, obj, f"unsupported type {type(obj).__name__}")


# def write_json_to_file(filename, content, indent=4):
#     """
#     Write a dictionary or list to a JSON file.
#
#     Args:
#         filename (str): The full path of the file to write.
#         content (dict | list): The JSON-serializable content to write.
#         indent (int): Indentation level for pretty printing. Default is 2.
#     """
#     try:
#         os.makedirs(os.path.dirname(filename), exist_ok=True)
#         with open(filename, 'w', encoding='utf-8') as f:
#             json.dump(content, f, indent=indent, ensure_ascii=False)
#         # print(f"[INFO] Wrote JSON to: {filename}")
#     except Exception as e:
#         print(f"[ERROR] Failed to write JSON to file: {e}")


def write_json_to_file(filename, content, indent=4, strict=False, encode_bytes=None):
    """
    encode_bytes: None | 'base64' | 'hex'  -> convert bytes-like automatically.
    strict: if True, disallow NaN/Inf.
    """
    try:
        # Optional preflight to print offenders with paths
        offenders = list(find_unserializable(content))
        if offenders:
            print("[ERROR] Found non-serializable fields:")
            for p, v, why in offenders[:10]:
                preview = v if isinstance(v, str) else repr(v)
                if len(preview) > 120: preview = preview[:117] + "..."
                print(f"  - {p}: {why}; value={preview}")
            # If you want to fail early, raise:
            # raise TypeError("Content contains non-serializable values.")
            # Or fall through to auto-convert below.

        def default(obj):
            if encode_bytes and isinstance(obj, (bytes, bytearray, memoryview)):
                b = bytes(obj)
                if encode_bytes == 'base64':
                    return {"__type__":"bytes","encoding":"base64","data": base64.b64encode(b).decode("ascii")}
                if encode_bytes == 'hex':
                    return {"__type__":"bytes","encoding":"hex","data": b.hex()}
            # Last resort: tell json we can't handle it (will raise TypeError)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                content, f,
                indent=indent,
                ensure_ascii=False,
                allow_nan=not strict,
                default=default if encode_bytes else None,
            )
        # print(f"[INFO] Wrote JSON to: {filename}")
    except Exception as e:
        print(f"[ERROR] Failed to write JSON to file: {e}")


def _keypad_code_to_char(code: int) -> str | None:
    if 0 <= code <= 9: return str(code)
    if code == 0x0E:   return '*'
    if code == 0x0F:   return '#'
    return None


def hexdump(data, width=16):
    def is_printable(b):
        return 32 <= b <= 126

    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_bytes = " ".join(f"{b:02X}" for b in chunk)
        ascii_bytes = "".join(chr(b) if is_printable(b) else "." for b in chunk)
        lines.append(f"{i:04X}  {hex_bytes:<{width*3}}  {ascii_bytes}")
    return "\n".join(lines)
