import requests
import time
from xml.etree import ElementTree as ET


def send_keypress(phone_ip, key_uri, username=None, password=None, priority="0"):
    """
    Send a single keypress to the Cisco 7912.

    Common key_uris:
        Key:KeyPad0, Key:KeyPad1, ..., Key:KeyPad9
        Key:KeyPadStar, Key:KeyPadPound
        Key:Soft1, Key:Soft2, Key:Soft3, Key:Soft4
        Key:Settings, Key:Services, Key:Directories, Key:Applications (or Messages)
        Key:VolumeUp, Key:VolumeDown
        Key:Headset, Key:Speaker, Key:Mute
        Key:NavUp, Key:NavDown, Key:NavLeft, Key:NavRight, Key:Select
    """
    xml = f'''<CiscoIPPhoneExecute>
    <ExecuteItem Priority="{priority}" URL="{key_uri}"/>
</CiscoIPPhoneExecute>'''

    url = f"http://{phone_ip}/CGI/Execute"

    try:
        if username and password:
            auth = (username, password)
            response = requests.post(url, data={"XML": xml}, auth=auth, timeout=5)
        else:
            response = requests.post(url, data={"XML": xml}, timeout=5)

        print(f"Sent {key_uri} → Status: {response.status_code}")
        if response.status_code == 200:
            print("Response:", response.text[:500])  # Show response
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending to {phone_ip}: {e}")
        return False


def send_multiple_keys(phone_ip, key_list, delay=0.3, username=None, password=None):
    """Send multiple keypresses in sequence with delay."""
    for key in key_list:
        send_keypress(phone_ip, key, username, password)
        time.sleep(delay)


def get_screenshot(phone_ip, username="admin", password="admin"):
    url = f"http://{phone_ip}/CGI/Screenshot"

    try:
        response = requests.get(url, auth=(username, password), timeout=10)

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            if response.headers.get('Content-Type') in ['image/png', 'image/bmp']:
                with open("phone_screenshot.png", "wb") as f:
                    f.write(response.content)
                print("✅ Screenshot saved as phone_screenshot.png")
            else:
                print("Response type:", response.headers.get('Content-Type'))
                print(response.text[:500])  # in case it's XML error
        else:
            print(response.text)

    except Exception as e:
        print("Error:", e)


# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    PHONE_IP = "10.102.10.209"  # ← Change to your phone's IP
    USER = "Administrator"  # Set if authentication required, e.g. "admin"
    PASS = "Anderj12!"

    # send_keypress(PHONE_IP, "Key:Soft2", USER, PASS)

    # Example 2: Navigate and press softkeys (e.g. go to network settings)
    keys = [
        "Key:Soft2",
        "Key:KeyPad1",
        "Key:KeyPad0",
        "Key:KeyPad0",
        "Key:KeyPad0",
    ]
    send_multiple_keys(PHONE_IP, keys, delay=0.6, username=USER, password=PASS)

    get_screenshot(PHONE_IP, USER, PASS)
