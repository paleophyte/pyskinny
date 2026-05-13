import datetime
import logging
logger = logging.getLogger(__name__)


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


def next_synthetic_call_reference(client):
    client._call_epoch += 1
    client.state.last_call_epoch = client._call_epoch
    return f"cm2-{client._call_epoch}"


def update_call_state(
    client,
    *,
    call_reference=None,
    line_instance=0,
    call_state=None,
    call_state_name=None,
    source="unknown",
    calling_party_name="",
    calling_party="",
    called_party_name="",
    called_party="",
    remote_name="",
    remote_number="",
):
    now = datetime.datetime.now(datetime.timezone.utc)

    # CM2 may not provide call_reference. Pick a stable fallback.
    if not call_reference:
        call_reference = (
            getattr(client.state, "selected_call_reference", None)
            or getattr(client.state, "active_call_reference", None)
            or line_instance
            or 1
        )

    key = str(call_reference)

    existing = client.state.calls.get(key, {})

    call_started = existing.get("call_started")
    call_ended = existing.get("call_ended")

    if call_state_name is None and call_state is not None:
        call_state_name = CALL_STATE_NAMES.get(call_state, "UNKNOWN")

    if call_state is None:
        call_state = existing.get("call_state", 0)

    client.state.calls[key] = {
        **existing,
        "call_state": call_state,
        "call_state_name": call_state_name or existing.get("call_state_name", "UNKNOWN"),
        "line_instance": line_instance or existing.get("line_instance", 0),
        "call_reference": call_reference,
        "current_time": now,
        "call_started": call_started,
        "call_ended": call_ended,
        "last_update_source": source,
        "calling_party_name": calling_party_name or existing.get("calling_party_name", ""),
        "calling_party": calling_party or existing.get("calling_party", ""),
        "called_party_name": called_party_name or existing.get("called_party_name", ""),
        "called_party": called_party or existing.get("called_party", ""),
        "remote_name": remote_name or existing.get("remote_name", ""),
        "remote_number": remote_number or existing.get("remote_number", ""),
    }

    if key not in client.state.calls_list:
        client.state.calls_list.append(key)

    return key


def mark_call_ringing(client, call_reference, line_instance=0):
    key = update_call_state(
        client,
        call_reference=call_reference,
        line_instance=line_instance,
        call_state=4,
        call_state_name="RingIn",
        source="inferred",
    )

    if key not in client.state.active_calls_list:
        client.state.active_calls_list.append(key)

    client.state.call_active = True
    client.state.active_call = True
    client._call_epoch += 1
    client.state.last_call_epoch = client._call_epoch
    client.events.call_ringing.set()
    client.events.call_ended.clear()

    return key


def mark_call_connected(client, call_reference, line_instance=0, source="inferred"):
    key = update_call_state(
        client,
        call_reference=call_reference,
        line_instance=line_instance,
        call_state=5,
        call_state_name="Connected",
        source=source,
    )

    call = client.state.calls[key]

    if call.get("call_started") is None or call.get("call_ended") is not None:
        call["call_started"] = datetime.datetime.now(datetime.timezone.utc)
        call["call_ended"] = None

    if key not in client.state.active_calls_list:
        client.state.active_calls_list.append(key)

    client.state.call_active = True
    client.state.active_call = True
    client.state.call_connected = True
    client.events.call_connected.set()
    client.events.call_ended.clear()

    return key


def mark_call_ended(client, call_reference=None, source="inferred"):
    now = datetime.datetime.now(datetime.timezone.utc)

    keys = []

    if call_reference:
        keys = [str(call_reference)]
    else:
        keys = list(client.state.active_calls_list or [])

    if not keys:
        selected = getattr(client.state, "selected_call_reference", None)
        if selected:
            keys = [str(selected)]

    for key in keys:
        if key in client.state.calls:
            client.state.calls[key]["call_state"] = 2
            client.state.calls[key]["call_state_name"] = "OnHook"
            client.state.calls[key]["call_ended"] = now
            client.state.calls[key]["last_update_source"] = source

        if key in client.state.active_calls_list:
            client.state.active_calls_list.remove(key)

    if not client.state.active_calls_list:
        client.state.active_call = False
        client.state.call_active = False
        client.state.call_connected = False
        client.state.media_active = False

    client.events.call_ringing.clear()
    client.events.call_connected.clear()
    client.events.media_started.clear()
    client.events.call_ended.set()

    logger.debug(
        f"mark_call_ended "
        f"call_reference={call_reference}"
    )

