import time
import inspect as _inspect
from utils.topology import summarize_meraki_status
import json
from messages.generic import handle_keypad_press
from datetime import datetime, timezone


# Utility: send digits like your macro
def _send_digits(client, digits: str, sleep=0.2):
    for d in digits:
        if d == "*":
            code = chr(0x0e)
        elif d == "#":
            code = chr(0x0f)
        else:
            code = d
        # assumes you have handle_keypad_press(client, line, code)
        try:
            handle_keypad_press(client, 1, code)
        except Exception:
            client.logger.warning("handle_keypad_press not available; sending soft DTMF not implemented")
        try:
            client.play_beep()
        except Exception:
            pass
        time.sleep(sleep)


def _human_elapsed(iso_ts, now=None) -> str:
    """
    < 60s       -> "n seconds"
    60s .. <1h  -> "m:ss"
    >= 1h       -> "h:mm:ss"
    Accepts iso_ts as ISO 8601 string or {"current_time": <iso>}.
    `now` can be None, ISO string, or datetime.
    """
    try:
        # Accept dict input like {"current_time": "..."}
        if isinstance(iso_ts, dict) and "current_time" in iso_ts:
            iso_ts = iso_ts["current_time"]

        # Parse target timestamp
        ts = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Parse/compute 'now'
        if now is None:
            now_dt = datetime.now(timezone.utc)
        elif isinstance(now, str):
            now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        elif isinstance(now, datetime):
            now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        else:
            raise TypeError(f"'now' must be None, str, or datetime, not {type(now)}")

        # Elapsed (absolute) seconds as int
        total = int((now_dt - ts).total_seconds())
        if total < 0:
            total = -total

        # Split safely as ints
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)

        if total < 60:
            return f"{seconds} seconds"
        if hours == 0:
            return f"{minutes}:{seconds:02d}"
        return f"{hours}:{minutes:02d}:{seconds:02d}"

    except Exception as e:
        # Helpful context if something weird sneaks in
        raise RuntimeError(
            f"human_elapsed failed for iso_ts={iso_ts!r} (type={type(iso_ts).__name__}), "
            f"now={now!r} (type={type(now).__name__})"
        ) from e


def _is_exec_handler(name, obj):
    if not (name.startswith("exec_") and _inspect.isfunction(obj)):
        return False
    if getattr(obj, "__module__", None) != __name__:
        return False  # don't pick up imported exec_* from other modules (optional)
    # Optional: enforce (client_or_ctx, clitext, argv, log) arity
    try:
        params = list(_inspect.signature(obj).parameters.values())
        return len(params) == 4
    except Exception:
        return True  # be forgiving if you don't want arity checks

def _truncate(s, length):
    return s[:length] if len(s) > length else s


def exec_exit(client, clitext, argv, log):
    # signal to caller loop to exit
    raise SystemExit

def exec_call_number(client, clitext, argv, log):
    if not argv:
        log("% Missing number")
        return
    number = argv[2]
    log(f"Calling {number} ...")
    client.press_softkey("NewCall")
    time.sleep(0.3)
    _send_digits(client, number)

def exec_send_digit(client, clitext, argv, log):
    if not argv:
        log("% Missing digit")
        return
    number = argv[3]
    log(f"Sending {number} ...")
    _send_digits(client, number)

def exec_send_softkeyevent(client, clitext, argv, log):
    # argv: [softkey, line, call_id]
    if len(argv) < 4:
        log("% Usage: phone send softkeyevent <Softkey> <Line> <CallRef>")
        return
    else:
        softkey = argv[3]
        line = int(argv[4]) if len(argv) >= 5 else 1
        callref = int(argv[5]) if len(argv) >= 6 else 0
        log(f"Softkey {softkey} (line {line}, call {callref})")
        client.press_softkey(softkey, line, callref)

def exec_show_calls(client, clitext, argv, log):
    lf = client.state.callinfo
    li = client.state.calls
    log(
        f"{'Line':<6} {'CallId':<9} {'CallType':<13} {'CallState':<14} {'Time':<11} {'FromNum':<12} {'FromName':<15} {'ToNum':<12} {'ToName':<15}"    )

    call_ids = []
    for call_id, _ in lf.items():
        if call_id not in call_ids and str(call_id).strip() != "":
            call_ids.append(call_id)
    for call_id, _ in li.items():
        if call_id not in call_ids and str(call_id).strip() != "":
            call_ids.append(call_id)

    for call_id in call_ids:
        ci_mi_data = li.get(call_id, {})
        call_state = ci_mi_data.get("call_state_name", "")
        call_time_started = ci_mi_data.get("current_time", "")
        call_dur = _human_elapsed(call_time_started)

        ci_md_data = lf.get(call_id, {})
        call_line = ci_md_data.get("line_instance", ci_mi_data.get("line_instance", "?"))
        call_type = ci_md_data.get("call_type_name", "")
        calling_num = ci_md_data.get("calling_party", "")
        calling_name = ci_md_data.get("calling_party_name", "")
        called_num = ci_md_data.get("called_party", "")
        called_name = ci_md_data.get("called_party_name", "")
        # call_dur = 0 # calculate_duration(state, call_ref)

        log(
            f"{call_line:<6} {call_id:<9} {call_type:<13} {call_state:<14} {call_dur:<11} {calling_num:<12} {calling_name:<15} {called_num:<12} {called_name:<15}"
        )


def exec_show_state_obj(client, clitext, argv, log):
    if not argv:
        log("% Usage: show state <ObjectName>")
        return

    if len(argv) == 2:
        if client.state:
            log(json.dumps(client.state.to_dict(), indent=4))
    elif len(argv) == 3:
        name = argv[-1]
        s = getattr(client.state, name, None)
        if s is None:
            log(f"% state has no '{name}'")
        else:
            if type(s) in (list, dict, tuple):
                log(f"{name} = {json.dumps(s, indent=4)}")
            else:
                log(f"{name} = {s}")

# def exec_command_topology(client, clitext, argv, log):
#     # Placeholder; stitch to your CDP/LLDP if/when you expose it on state
#     topo = getattr(client.state, "topology", None)
#     if topo is None:
#         log("% topology unavailable")
#     else:
#         log(str(topo))


def exec_command_topology(client, clitext, argv, log):
    log("TOPOLOGY INFORMATION")

    if not client.state:
        log("")
        return

    cdp_neighbor = client.state.topology.get("cdp", {})
    lldp_neighbor = client.state.topology.get("lldp", {})
    meraki_neighbor = client.state.topology.get("meraki", {})

    if not cdp_neighbor and not lldp_neighbor and not meraki_neighbor:
        log("  No CDP or LLDP neighbors discovered.\n")

    if cdp_neighbor:
        log("\nCDP Neighbor:")
        if argv[-1].lower() == "detail":
            log(json.dumps(cdp_neighbor, indent=4))
        log(f"{'Device ID':<22} {'Port ID':<12} {'Platform':<16} {'Mgmt IP':<15}")
        log("-" * 68) # 65 characters + 3 spaces
        n = cdp_neighbor
        blank = ""
        log(f"{_truncate(n.get('device_id',''), 22):<22} {_truncate(n.get('port_id',''), 12):<12} {_truncate(n.get('platform',''), 16):<16} {_truncate(n.get('mgmt_address',''), 15):<15}")

    if lldp_neighbor:
        log("\nLLDP Neighbor:")
        if argv[-1].lower() == "detail":
            log(json.dumps(lldp_neighbor, indent=4))
        log(f"{'Chassis ID':<22} {'Port ID':<12} {'Platform':<16} {'Mgmt IP':<15} {'System Name':<15}")
        log("-" * 84) # 80 characters + 4 spaces
        n = lldp_neighbor
        log(f"{_truncate(n.get('chassis_id', ''), 22):<22} {_truncate(n.get('port_id', ''), 12):<12} {_truncate(n.get('system_desc', ''), 16):<16} {_truncate(n.get('mgmt_address', ''), 15):<15} {_truncate(n.get('system_name', ''), 15):<15}")

    if meraki_neighbor:
        if argv[-1].lower() == "detail":
            log(json.dumps(meraki_neighbor, indent=4))
        summarize_meraki_status(meraki_neighbor, log)

    if True:
        log(f"CALLMANAGER CONNECTION")
        log(f"  Server IP : {client.state.server}")
        log(f"  Client IP : {client.state.client_ip}")
        log(f"  Interface : {client.state.interface}")
        log(f"MAC Address : {client.state.interface_mac}")


def exec_show_config(ctx, clitext, argv, log):
    cfg = ctx.config
    log(f"server: {cfg.get('server')}")
    log(f"mac:    {cfg.get('mac')}")
    log(f"model:  {cfg.get('model')}")
    log(f"auto_connect: {cfg.get('auto_connect')}")


def exec_auto_answer(ctx, clitext, argv, log):
    if not argv:
        return log("% Usage: set auto_answer <true|false>")

    val = argv[2].lower()
    truthy = {"true", "t", "yes", "y", "1", "on"}
    falsy  = {"false", "f", "no", "n", "0", "off"}

    if val in truthy:
        ctx.config["auto_answer"] = True
    elif val in falsy:
        ctx.config["auto_answer"] = False
    else:
        return log("% Invalid value. Expected true/false (or yes/no, on/off).")

    log(f"auto_answer = {ctx.config['auto_answer']}")


def exec_auto_connect(ctx, clitext, argv, log):
    if not argv:
        return log("% Usage: set auto_connect <true|false>")

    val = argv[2].lower()
    truthy = {"true", "t", "yes", "y", "1", "on"}
    falsy  = {"false", "f", "no", "n", "0", "off"}

    if val in truthy:
        ctx.config["auto_connect"] = True
    elif val in falsy:
        ctx.config["auto_connect"] = False
    else:
        return log("% Invalid value. Expected true/false (or yes/no, on/off).")

    log(f"auto_connect = {ctx.config['auto_connect']}")


def exec_set_server(ctx, clitext, argv, log):
    if not argv: return log("% Usage: set server <host>")
    ctx.config["server"] = argv[2]
    log(f"server = {ctx.config['server']}")

def exec_set_mac(ctx, clitext, argv, log):
    if not argv: return log("% Usage: set mac <hexmac>")
    ctx.config["mac"] = argv[2]
    log(f"mac = {ctx.config['mac']}")

def exec_set_model(ctx, clitext, argv, log):
    if not argv: return log("% Usage: set model <model>")
    ctx.config["model"] = argv[2]
    log(f"model = {ctx.config['model']}")

def exec_save(ctx, clitext, argv, log):
    ctx.save()

def exec_load(ctx, clitext, argv, log):
    ctx.load()

def exec_connect(ctx, clitext, argv, log):
    # Import here to avoid circulars in module top-level
    from client import SCCPClient
    from state import PhoneState
    ok = ctx.connect(PhoneState, SCCPClient)
    if not ok:
        log("% connect failed")

def exec_disconnect(ctx, clitext, argv, log):
    ctx.disconnect()
    log("Disconnected.")

def exec_set_cdp(ctx, clitext, argv, log):
    if not argv:
        return log("% Usage: set enable_cdp <true|false>")

    val = argv[2].lower()
    truthy = {"true", "t", "yes", "y", "1", "on"}
    falsy  = {"false", "f", "no", "n", "0", "off"}

    if val in truthy:
        ctx.config["enable_cdp"] = True
    elif val in falsy:
        ctx.config["enable_cdp"] = False
    else:
        return log("% Invalid value. Expected true/false (or yes/no, on/off).")

    log(f"enable_cdp = {ctx.config['enable_cdp']}")


def exec_set_lldp(ctx, clitext, argv, log):
    if not argv:
        return log("% Usage: set enable_lldp <true|false>")

    val = argv[2].lower()
    truthy = {"true", "t", "yes", "y", "1", "on"}
    falsy  = {"false", "f", "no", "n", "0", "off"}

    if val in truthy:
        ctx.config["enable_lldp"] = True
    elif val in falsy:
        ctx.config["enable_lldp"] = False
    else:
        return log("% Invalid value. Expected true/false (or yes/no, on/off).")

    log(f"enable_lldp = {ctx.config['enable_lldp']}")


def exec_set_lsp(ctx, clitext, argv, log):
    if not argv:
        return log("% Usage: set enable_lsp <true|false>")

    val = argv[2].lower()
    truthy = {"true", "t", "yes", "y", "1", "on"}
    falsy  = {"false", "f", "no", "n", "0", "off"}

    if val in truthy:
        ctx.config["enable_lsp"] = True
    elif val in falsy:
        ctx.config["enable_lsp"] = False
    else:
        return log("% Invalid value. Expected true/false (or yes/no, on/off).")

    log(f"enable_lsp = {ctx.config['enable_lsp']}")


FUNCTIONS = {
    name: obj
    for name, obj in list(globals().items())
    if _is_exec_handler(name, obj)
}