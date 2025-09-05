import struct
from dispatcher import get_message_name
import os
import string
import logging
logger = logging.getLogger(__name__)


SOFTKEY_TEMPLATE_INDEXES = {
    0: "Undefined",
    1: "Redial",
    2: "NewCall",
    3: "Hold",
    4: "Transfer",
    5: "CfwdAll",
    6: "CfwdBusy",
    7: "CfwdNoAnswer",
    8: "BackSpace",
    9: "EndCall",
    10: "Resume",
    11: "Answer",
    12: "Info",
    13: "Confrn",
    14: "Park",
    15: "Join",
    16: "MeetMe",
    17: "Pickup",
    18: "GrpPickup",
    19: "Monitor",
    20: "CallBack",
    21: "Select",
    22: "Page",
    23: "Exit",
    24: "DirTrfr",
    25: "EditDial",
    26: "TrnsfVM",
    27: "Intrude",
    28: "Private",
    29: "RmLstC",
    30: "Save",
    31: "Delete",
    32: "Dial",
    33: "ConfList",
    34: "SelectList",
    35: "Barge",
    36: "cBarge",
    37: "ReDial",
    38: "DND",
    39: "DivAll",
    40: "CallInfo",
    41: "Update",
    42: "Cancel",
    43: "CallSelect",
}


SOFTKEY_INFO_INDEXES = {
    0: "Undefined",
    301: "Redial",
    302: "NewCall",
    303: "Hold",
    304: "Transfer",
    305: "CfwdAll",
    306: "CfwdBusy",
    307: "CfwdNoAnswer",
    308: "BackSpace",
    309: "EndCall",
    310: "Resume",
    311: "Answer",
    312: "Info",
    313: "Confrn",
    314: "Park",
    315: "Join",
    316: "MeetMe",
    317: "Pickup",
    318: "GrpPickup",
    319: "ToVoicemail",
    320: "Select",
    321: "Barge",
    322: "cBarge",
    323: "DND",
    324: "DivAll",
    325: "CallInfo",
    326: "Update",
    327: "Cancel",
    328: "Immediate Divert",
    329: "Video Mode",
    330: "Intercept",
    331: "Record",
    332: "TrnsfVM",
    333: "Conference Barge",
}


KEY_SET_INDEX_NAMES = {
    0: "On Hook",
    1: "Connected",
    2: "On Hold",
    3: "Ring In",
    4: "Off Hook",
    5: "Connected Transferable",
    6: "Digits Following",
    7: "Connected Conference",
    8: "Ring Out",
    9: "Off Hook with Features",
    10: "In Transfer",
    11: "Connected Conference Join",
    12: "Connected Monitored",
    13: "Call Park",
    14: "Call Pickup",
}


DEVICE_TYPE_MAP = {
    6: "Cisco 7910",
    7: "Cisco 7960",
    8: "Cisco 7940",
    9: "Cisco 7935",
    115: "Cisco 7941",
    119: "Cisco 7971",
    302: "Cisco 7985",
    307: "Cisco 7911",
    308: "Cisco 7961G-GE",
    309: "Cisco 7941G-GE",
    335: "Motorola CN622",
    336: "Third-party SIP Device (Basic)",
    348: "Cisco 7931",
    358: "Cisco Unified Personal Communicator",
    365: "Cisco 7921",
    369: "Cisco 7906",
    374: "Third-party SIP Device (Advanced)",
    404: "Cisco 7962",
    412: "Cisco 3951",
    431: "Cisco 7937",
    434: "Cisco 7942",
    435: "Cisco 7945",
    436: "Cisco 7965",
    437: "Cisco 7975",
    484: "Cisco 7925",
    493: "Cisco 9971",
    495: "Cisco 6921",
    496: "Cisco 6941",
    497: "Cisco 6961",
    537: "Cisco 9951",
    540: "Cisco 8961",
    20000: "Cisco 7905",
    30002: "Cisco 7920",
    30006: "Cisco 7970",
    30007: "Cisco 7912",
    30008: "Cisco 7902",
    30016: "Cisco IP Communicator",
    30018: "Cisco 7961",
    30019: "Cisco 7936",
    30027: "Analog Phone",
    30032: "SCCP Gateway Virtual Phone",
}


STIMULUS_NAMES = {
    1: "Headset",
    2: "Mute",
    3: "Speaker",
    4: "Transfer",
    5: "Hold",
    6: "Redial",
    7: "NewCall",
    8: "CallBack",
    9: "Line",
    10: "Messages",
    11: "Directories",
    12: "Services",
    13: "Settings",
    14: "HeadsetHook",
    15: "MuteHook",
    16: "SpeakerHook",
    17: "CallForward",
    18: "Applications",
    19: "DoNotDisturb",
    20: "Broadcast",
    125: "Conference",
    126: "CallPark",
    127: "HeadsetLED",
}


CALL_STATE_NAMES = {
    0:  "Idle",          # No active call
    1:  "OffHook",       # Handset lifted / call initiated
    2:  "OnHook",        # Call ended / handset down
    3:  "RingOut",       # Outgoing call is ringing
    4:  "RingIn",        # Incoming call is ringing
    5:  "Connected",     # Call is active
    6:  "Busy",          # Remote party is busy
    7:  "Congestion",    # Network congestion
    8:  "Hold",          # Call is on hold
    9:  "CallWaiting",   # Incoming call while another is active
    10: "CallTransfer",  # Mid transfer
    11: "CallPark",      # Mid park
    12: "Proceed",       # Dialing in progress
    13: "CallRxOffer",   # Offer received (SIP interop, etc.)
}

CALL_STAT_STATE_NAMES = {
    1: "RingOut",
    2: "RingIn",
}

TONE_NAMES = {
    0x00: "Silence",
    0x01: "Dtmf0",
    0x02: "Dtmf1",
    0x03: "Dtmf2",
    0x04: "Dtmf3",
    0x05: "Dtmf4",
    0x06: "Dtmf5",
    0x07: "Dtmf6",
    0x08: "Dtmf7",
    0x09: "Dtmf8",
    0x0A: "Dtmf9",
    0x0B: "DtmfStar",
    0x0C: "DtmfPound",

    0x20: "DialTone",
    0x21: "InsideDialTone",
    0x22: "OutsideDialTone",
    0x23: "LineBusyTone",
    0x24: "AlertingTone",
    0x25: "ReorderTone",
    0x26: "RecorderWarningTone",
    0x27: "RecorderDetectedTone",
    0x28: "ReorderToneFast",
    0x29: "BusyVerificationTone",
    0x2A: "CallWaitingTone",
    0x2B: "StutterDialTone",
    0x2C: "HowlerTone",
    0x2D: "ManagerBargeTone",
    0x2E: "ForcedAuthorizationTone",
    0x2F: "PriorityCallTone",
    0x30: "AutoAnswerTone",
    0x31: "ZipZip",                # Paging
    0x32: "BeepBonk",              # Error
    0x33: "InsideDialTone",        # Duplicate of 0x21 (used by some firmware)
    0x34: "DistinctiveRing1",
    0x35: "DistinctiveRing2",
    0x36: "DistinctiveRing3",
    0x37: "MultilineRingingTone",
    0x38: "PickupTone",
    0x39: "RemindTone",
    0x3A: "HoldTone",
    0x3B: "RemoteHoldTone",
    0x3C: "SharedLineAlert",
    0x3D: "CoachingTone",
    0x3E: "SilentMonitorTone",
}
TONE_OUTPUT_DIRECTION_NAMES = {
    0: "User",
    1: "Speaker",
    2: "Both",
}

TONE_FOLDER = os.path.join(os.getcwd(), "cisco_tones")
TONE_LOOKUP = {
    0: "key_beep.wav",
    1: "phone_ring.wav",
    2: "busy_tone.wav",
    4: "outside_dial_tone.wav",
    6: "call_waiting_tone.wav",
    33: "inside_dial_tone.wav",
    37: "reorder_tone.wav",
    36: "alerting_tone.wav",
}

CALL_TYPE_NAMES = {
    1: "InBoundCall",
    2: "OutBoundCall",
}

UNREGISTER_STATUS_NAMES = {
    0: "Ok",
    2: "NAK",
}


# Reverse map
DEVICE_NAME_TO_ENUM = {}
for enum, name in DEVICE_TYPE_MAP.items():
    lower_name = name.lower()
    DEVICE_NAME_TO_ENUM[lower_name] = enum  # e.g., "cisco 7970" → 30006

    # Also add short version if name starts with "Cisco"
    if name.lower().startswith("cisco "):
        short_model = name.lower().split("cisco ")[1]
        DEVICE_NAME_TO_ENUM[short_model] = enum  # e.g., "7970" → 30006


def get_device_enum(model_name: str) -> int | None:
    return DEVICE_NAME_TO_ENUM.get(model_name.lower())


def get_skinny_message(msg_id, trailing_data=b""):
    length = len(trailing_data)
    # log(str(msg_id) + "::" + str(trailing_data) + "::" + str(len(trailing_data)))
    header = struct.pack("<I I I", length + 4, 0, msg_id)
    packet = header + trailing_data
    return packet


def send_skinny_message(client, msg_id, trailing_data=b"", silent=False):
    packet = get_skinny_message(msg_id, trailing_data)
    client.sock.sendall(packet)

    msg_txt = get_message_name(msg_id)

    if not silent:
        # logger.info(f"[SEND] {msg_txt} ({len(packet)} bytes)")
        logger.info(f"({client.state.device_name}) [SEND] {msg_txt}")


def clean_bytes(b: bytes) -> str:
    # Truncate at first null, decode only up to that point
    b = b.split(b'\x00', 1)[0]
    return ''.join(chr(c) for c in b if chr(c) in string.printable).strip()


def handle_softkey_press(client, line_number, softkey_id, call_reference=0):
    # if not call_reference:
    #     call_reference = get_active_call_reference_from_db(line_number, shared_state, log=log)

    logger.info(f"[SEND] SoftKeyEvent lineNumber={line_number} callReference={call_reference} softKeyId={softkey_id}")
    send_skinny_message(client, 0x0026, struct.pack("<III", softkey_id, line_number, call_reference), silent=True)


def handle_keypad_press(client, line_number, keypad_btn, call_reference=0):
    # call_reference = int(shared_state.get("CallInfo", {}).get(str(line_number), {}).get("callReference", "0"))
    # call_reference = get_active_call_reference(1, shared_state, log=log)

    logger.info(f"[SEND] KeypadButton lineNumber={line_number} callReference={call_reference} keyPadBtn={keypad_btn}")
    send_skinny_message(client, 0x0003, struct.pack("<III", int(keypad_btn), line_number, call_reference), silent=True)
