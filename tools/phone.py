import os
import time
import requests
from xml.etree import ElementTree as ET
import argparse
from PIL import Image


# ---------- core HTTP helpers ----------
def _try_get(urls, auth=None, timeout=6, verify=False):
    last = None
    for u in urls:
        try:
            r = requests.get(u, auth=auth, timeout=timeout, verify=verify)
            if r.status_code == 401:
                raise PermissionError("HTTP 401 Unauthorized")
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
    raise RuntimeError(f"GET failed: {last}")


def _try_post(urls, data=None, headers=None, auth=None, timeout=6, verify=False):
    last = None
    for u in urls:
        try:
            r = requests.post(u, data=data, headers=headers or {}, auth=auth, timeout=timeout, verify=verify)
            if r.status_code == 401:
                raise PermissionError("HTTP 401 Unauthorized")
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
    raise RuntimeError(f"POST failed: {last}")


# ---------- screenshot ----------
def fetch_screenshot(ip, auth=None, use_https=False, timeout=6, verify=False, save_as=None):
    """
    Returns (bytes, ext) and saves to file if save_as is given (ext appended if missing).
    Tries HTTP first unless use_https=True.
    """
    schemes = (["https"] if use_https else ["http", "https"])
    urls = []
    for s in schemes:
        # Some firmwares only accept exactly /CGI/Screenshot
        urls.append(f"{s}://{ip}/CGI/Screenshot")
        # A few odd builds need a dummy query to bypass caches
        urls.append(f"{s}://{ip}/CGI/Screenshot?ts={int(time.time())}")

    r = _try_get(urls, auth=auth, timeout=timeout, verify=verify)
    data = r.content
    ext = _guess_image_ext(data, r.headers.get("Content-Type"))
    if save_as:
        base, e = os.path.splitext(save_as)
        path = save_as if e else f"{base}.{ext}"
        with open(path, "wb") as f:
            f.write(data)
        return data, ext, path
    return data, ext, None


def _guess_image_ext(data, content_type=None):
    if content_type:
        if "png" in content_type.lower(): return "png"
        if "bmp" in content_type.lower(): return "bmp"
    # Magic
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "png"
    if data.startswith(b"BM"): return "bmp"
    return "bin"


# ---------- button presses / actions ----------
def _execute(ip, execute_items, auth=None, use_https=False, timeout=6, verify=False):
    """
    execute_items: list of URLs, e.g., ["Key:Speaker", "Key:KeyPad5"] or ["Dial:1001"]
    """
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<CiscoIPPhoneExecute>
  {''.join(f'<ExecuteItem Priority="0" URL="{_xml_escape(u)}"/>' for u in execute_items)}
</CiscoIPPhoneExecute>"""
    schemes = (["https"] if use_https else ["http", "https"])
    urls = [f"{s}://{ip}/CGI/Execute" for s in schemes]
    r = _try_post(urls, data=body.encode("utf-8"),
                  headers={"Content-Type": "text/xml"}, auth=auth,
                  timeout=timeout, verify=verify)
    # Successful returns are tiny XML docs with <CiscoIPPhoneResponse> or empty;
    # surface any explicit errors:
    try:
        root = ET.fromstring(r.text.strip() or "<ok/>")
        err = root.find(".//ResponseItem/Status")
        if err is not None and err.text and err.text.strip() not in ("0","OK"):
            raise RuntimeError(f"Phone Execute error: {err.text.strip()}")
    except ET.ParseError:
        pass
    return True


def press_keys(ip, sequence, auth=None, use_https=False, timeout=6, verify=False):
    """
    Press key sequence via KeyPad: '123#*' etc.
    """
    keymap = {
        "0":"Key:KeyPad0", "1":"Key:KeyPad1", "2":"Key:KeyPad2", "3":"Key:KeyPad3",
        "4":"Key:KeyPad4", "5":"Key:KeyPad5", "6":"Key:KeyPad6", "7":"Key:KeyPad7",
        "8":"Key:KeyPad8", "9":"Key:KeyPad9", "*":"Key:KeyPadStar", "#":"Key:KeyPadPound"
    }
    items = []
    for ch in str(sequence):
        if ch in keymap: items.append(keymap[ch])
        else: raise ValueError(f"Unsupported key: {ch!r}")
    return _execute(ip, items, auth, use_https, timeout, verify)


def dial(ip, digits, auth=None, use_https=False, timeout=6, verify=False):
    """
    Initiate a call: many firmwares support Dial:<digits>. If not, falls back to keypad.
    """
    try:
        return _execute(ip, [f"Dial:{digits}"], auth, use_https, timeout, verify)
    except Exception:
        return press_keys(ip, str(digits), auth, use_https, timeout, verify)


def softkey(ip, index, auth=None, use_https=False, timeout=6, verify=False):
    """
    Press a softkey: index 1..4 maps to Soft1..Soft4 (older 79xx).
    """
    idx = int(index)
    if idx < 1 or idx > 4:
        raise ValueError("softkey index must be 1..4")
    return _execute(ip, [f"Key:Soft{idx}"], auth, use_https, timeout, verify)


def nav(ip, direction, auth=None, use_https=False, timeout=6, verify=False):
    """
    direction: one of up/down/left/right/select/back
    """
    d = direction.lower()
    mapping = {
        "up":"Key:NavUp", "down":"Key:NavDown", "left":"Key:NavLeft",
        "right":"Key:NavRight", "select":"Key:NavSelect", "back":"Key:NavBack"
    }
    if d not in mapping: raise ValueError("direction must be up/down/left/right/select/back")
    return _execute(ip, [mapping[d]], auth, use_https, timeout, verify)


def hardkey(ip, key, auth=None, use_https=False, timeout=6, verify=False):
    """
    Common hard keys: speaker, headset, mute, messages, services, directories, settings
    """
    k = key.lower()
    mapping = {
        "speaker":"Key:Speaker", "headset":"Key:Headset", "mute":"Key:Mute",
        "messages":"Key:Messages", "services":"Key:Services",
        "directories":"Key:Directories", "settings":"Key:Settings"
    }
    if k not in mapping:
        raise ValueError(f"unsupported hard key: {key}")
    return _execute(ip, [mapping[k]], auth, use_https, timeout, verify)


def _xml_escape(s):
    return (s.replace("&","&amp;").replace("<","&lt;")
             .replace(">","&gt;").replace('"',"&quot;").replace("'","&apos;"))


def decode_cip_data(hex_data, width=160, height=100, reverse_bits=False, reverse_bytes=False, flip_horizontal=False):
    """
    Decode Cisco CIP format data to pixel values.
    The CIP format uses a compressed format where each byte represents pixel data.
    """
    # Remove any whitespace and convert hex string to bytes
    hex_data = hex_data.replace('\n', '').replace('\r', '').replace(' ', '')

    try:
        # Convert hex string to bytes
        data_bytes = bytes.fromhex(hex_data)
    except ValueError as e:
        raise ValueError(f"Invalid hex data: {e}")

    if reverse_bytes:
        data_bytes = data_bytes[::-1]

    # The Cisco 7940 uses a 2-bit grayscale format (4 levels of gray)
    # Each byte contains 4 pixels (2 bits per pixel)
    pixels = []

    for byte in data_bytes:
        # Extract 4 pixels from each byte (2 bits per pixel)
        if reverse_bits:
            # Process from LSB to MSB (reverse bit order)
            bit_shifts = [0, 2, 4, 6]
        else:
            # Process from MSB to LSB (normal order)
            bit_shifts = [6, 4, 2, 0]

        for shift in bit_shifts:
            pixel_value = (byte >> shift) & 0x03  # Extract 2 bits
            # Convert 2-bit value (0-3) to 8-bit grayscale (0-255)
            gray_value = pixel_value * 85  # 0->0, 1->85, 2->170, 3->255
            pixels.append(gray_value)

    # Ensure we have enough pixels for the image dimensions
    expected_pixels = width * height
    if len(pixels) < expected_pixels:
        # Pad with black pixels if needed
        pixels.extend([0] * (expected_pixels - len(pixels)))
    elif len(pixels) > expected_pixels:
        # Truncate if we have too many pixels
        pixels = pixels[:expected_pixels]

    # If we need to flip horizontally, rearrange pixels row by row
    if flip_horizontal:
        flipped_pixels = []
        for row in range(height):
            row_start = row * width
            row_end = row_start + width
            row_pixels = pixels[row_start:row_end]
            flipped_pixels.extend(row_pixels[::-1])  # Reverse this row
        pixels = flipped_pixels

    return pixels


def parse_cisco_xml_response(xml_content):
    """
    Parse the XML response from Cisco phone to extract image data and dimensions.
    """
    try:
        root = ET.fromstring(xml_content)

        # Look for image data - it might be in different elements depending on firmware
        image_data = None
        width = 160  # Default for 7940
        height = 100  # Default for 7940

        # Try different possible element names
        for element in root.iter():
            if element.text and len(element.text.replace('\n', '').replace(' ', '')) > 1000:
                # This is likely our hex image data
                image_data = element.text
                break

        # Try to find width/height attributes or elements
        for element in root.iter():
            if 'width' in element.tag.lower() or 'width' in element.attrib:
                try:
                    width = int(element.text or element.attrib.get('width', width))
                except (ValueError, TypeError):
                    pass
            if 'height' in element.tag.lower() or 'height' in element.attrib:
                try:
                    height = int(element.text or element.attrib.get('height', height))
                except (ValueError, TypeError):
                    pass

        if not image_data:
            raise ValueError("No image data found in XML response")

        return image_data, width, height

    except ET.ParseError as e:
        raise ValueError(f"Invalid XML format: {e}")


def create_image_from_pixels(pixels, width, height):
    """
    Create a PIL Image from decoded pixel data.
    """
    # Create grayscale image
    img = Image.new('L', (width, height))
    img.putdata(pixels)
    return img


def decode_cisco_screenshot(xml_content, reverse_bits=True, reverse_bytes=False, flip_horizontal=False):
    """
    Convenience function to decode Cisco screenshot XML and return PIL Image.

    Args:
        xml_content (str): XML content from Cisco phone /CGI/Screenshot endpoint
        reverse_bits (bool): Reverse bit order within bytes
        reverse_bytes (bool): Reverse byte order in data
        flip_horizontal (bool): Flip image horizontally

    Returns:
        PIL.Image: Decoded screenshot image
    """
    hex_data, width, height = parse_cisco_xml_response(xml_content)
    pixels = decode_cip_data(hex_data, width, height, reverse_bits, reverse_bytes, flip_horizontal)
    return create_image_from_pixels(pixels, width, height)


def main():
    ap = argparse.ArgumentParser(description="AXL v1 phone lister")
    ap.add_argument("--phoneip", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--pass", dest="pwd", required=True)
    ap.add_argument('-o', '--output', default='screenshot.png', help='Output image file (default: screenshot.png)')

    args = ap.parse_args()

    data, ext, path = fetch_screenshot(args.phoneip, auth=(args.user, args.pwd), use_https=False)
    img = decode_cisco_screenshot(data, reverse_bits=True, reverse_bytes=False, flip_horizontal=False)
    img.save(args.output)

    print(f"Image format: {img.format}")
    print(f"Image mode: {img.mode}")
    print(f"Image size: {img.size}")


if __name__ == "__main__":
    main()
