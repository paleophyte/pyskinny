import argparse
import time
from client import SCCPClient
from config import load_config
from state import PhoneState
from messages.generic import handle_keypad_press
import threading
import logging
logger = logging.getLogger(__name__)


def _parse_cases(spec: str, labels: dict[str,int]):
    # print(spec)
    # print(labels)
    cases = {}
    default = None
    for tok in spec.split(";"):
        tok = tok.strip()
        if not tok: continue
        k, v = tok.split(":")
        if k.strip().upper() == "DEFAULT":
            default = labels.get(v.strip().upper())
        else:
            cases[k.strip()] = labels.get(v.strip().upper())
    return cases, default


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (len(s) >= 2) and ((s[0] == s[-1]) and s[0] in ("'", '"')):
        return s[1:-1]
    return s


def _coerce_literal(s):
    """Try to coerce a string to int/float/bool/None; fall back to original string."""
    if s is None:
        return None
    if isinstance(s, (int, float, bool)):
        return s
    xs = str(s).strip()
    # bools
    low = xs.lower()
    if low in ("true", "false"):
        return low == "true"
    # none/null
    if low in ("none", "null"):
        return None
    # int
    try:
        return int(xs)
    except ValueError:
        pass
    # float
    try:
        return float(xs)
    except ValueError:
        pass
    return xs


def sleep_interruptible(seconds: float, stop_event: threading.Event, call_end_event: threading.Event) -> bool:
    """Sleep up to `seconds` in small chunks; return False if interrupted."""
    end = time.time() + seconds
    while not stop_event.is_set() or call_end_event.is_set():
        remain = end - time.time()
        if remain <= 0:
            return True
        stop_event.wait(min(0.1, remain))
    return False


class MacroInstruction:
    def __init__(self, command, args=None, label=None):
        self.command = command
        self.args = args or []
        self.label = label


def parse_macro_script(script):
    instructions = []
    labels = {}

    lines = [line.strip() for line in script.replace(",", "\n").splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line.endswith(":"):  # label definition
            label = line[:-1].strip().upper()
            labels[label] = len(instructions)
            continue

        parts = line.split()
        command = parts[0].upper()
        args = parts[1:]
        instructions.append(MacroInstruction(command, args))

    return instructions, labels


def run_macro(client: SCCPClient, instructions, labels, stop_event: threading.Event):
    on_disc = ("NONE", None)  # ("EXIT", None) or ("GOTO", "TOP")
    pc = 0

    def handle_disconnect():
        """Return 'exit' to break, 'jump' if we changed pc, or None to continue."""
        if not client.events.call_ended.is_set():
            return None
        # consume the event so we only react once per hangup
        client.events.call_ended.clear()
        action, arg = on_disc
        logger.debug(f"Disconnect Detected: {action}, {arg}")
        if action == "EXIT":
            return "exit"
        elif action == "GOTO":
            dest = labels.get(arg.upper())
            if dest is not None:
                nonlocal pc
                pc = dest
                return "jump"
        return None

    def after_blocking():
        if stop_event.is_set():
            return "exit"
        r = handle_disconnect()
        if r in ("exit", "jump"):
            return r
        return None

    while pc < len(instructions) and not stop_event.is_set():
        if stop_event.is_set():
            break

        # early-out if the call ended and policy says exit/jump
        r = handle_disconnect()
        if r == "exit":
            break
        if r == "jump":
            continue

        instr = instructions[pc]
        cmd = instr.command
        args = instr.args

        logger.message(f"Executing: {cmd} {args}")

        if cmd == "WAIT" or cmd == "SLEEP":
            # time.sleep(int(args[0]))
            secs = float(args[0])
            ok = sleep_interruptible(secs, stop_event, client.events.call_ended)
            if not ok:
                r = after_blocking()
                if r == "exit": break
                if r == "jump": continue
                # interrupted by something else? just continue to next step
                continue
        elif cmd == "WAIT_CALL":
            # Syntax: WAIT_CALL <seconds> [RING|CONNECTED|MEDIA]
            logger.message(f"Press 'q' to quit")
            secs = float(args[0])
            target = (args[1].upper() if len(args) > 1 else "RING")

            # timeout = None if secs == 0 else secs
            # ok = client.wait_for_call(timeout=timeout, until=target)
            # if not ok:
            #     logger.warning(f"WAIT_CALL timed out after {secs} seconds waiting for {target}")

            deadline = None if secs == 0 else (time.time() + secs)
            got = False
            while not stop_event.is_set() and not client.events.call_ended.is_set():
                slice_timeout = 0.25
                if deadline is not None:
                    remain = deadline - time.time()
                    if remain <= 0: break
                    slice_timeout = min(slice_timeout, max(0.01, remain))
                if client.wait_for_call(timeout=slice_timeout, until=target):
                    got = True
                    break
            r = after_blocking()
            if r == "exit": break
            if r == "jump": continue
            if not got and not stop_event.is_set() and not client.events.call_ended.is_set():
                logger.warning(f"WAIT_CALL timed out ({secs}s) waiting for {target}")
        # elif cmd == "WAIT_DIGIT":
        #     secs = float(args[0])
        #     ch = client.wait_for_digit(None if secs == 0 else secs)
        #     if ch is None:
        #         logger.warning("WAIT_DIGIT timeout")
        #     else:
        #         client.state.kv_dict["last_digit"] = ch
        # elif cmd == "GETDIGITS":
        #     var = args[0]
        #     max_len = int(args[1])
        #     secs = float(args[2])
        #     terms = args[3] if len(args) > 3 else "#"
        #     s = client.read_digits(max_len=max_len, timeout=None if secs == 0 else secs, terminators=terms)
        #     client.state.kv_dict[var] = s
        elif cmd == "WAIT_DIGIT":
            # Syntax: WAIT_DIGIT <secs>  (0 = forever)
            secs = float(args[0])
            deadline = None if secs == 0 else (time.time() + secs)
            ch = None
            while not stop_event.is_set() and not client.events.call_ended.is_set():
                slice_to = 0.25
                if deadline is not None:
                    remain = deadline - time.time()
                    if remain <= 0:
                        break
                    slice_to = min(slice_to, max(0.01, remain))
                ch = client.wait_for_digit(timeout=slice_to)  # or pass stop_event if you added it
                if ch is not None:
                    break
            # if stop_event.is_set() or client.events.call_ended.is_set():
            #     break
            r = after_blocking()
            if r == "exit": break
            if r == "jump": continue
            if ch is None:
                logger.warning("WAIT_DIGIT timeout")
            else:
                client.state.kv_dict["last_digit"] = ch
        elif cmd == "ON_DISCONNECT":
            # Syntax: ON_DISCONNECT EXIT | ON_DISCONNECT GOTO <LABEL> | ON_DISCONNECT NONE
            mode = args[0].upper() if args else "NONE"
            if mode == "EXIT":
                on_disc = ("EXIT", None)
            elif mode == "GOTO":
                if len(args) < 2:
                    logger.error("ON_DISCONNECT GOTO requires a label")
                else:
                    on_disc = ("GOTO", args[1])
            else:
                on_disc = ("NONE", None)
        elif cmd == "GETDIGITS":
            # Syntax: GETDIGITS <var> <max_len> <secs> [terminators]
            # Reads up to max_len digits within secs, stops early on any of terminators (default #). Saves into kv_dict[var].
            var = args[0]
            max_len = int(args[1])
            secs = float(args[2])
            terms = args[3] if len(args) > 3 else "#"

            # poll in slices so we can exit
            deadline = None if secs == 0 else (time.time() + secs)
            s = ""
            while (len(s) < max_len) and not stop_event.is_set() and not client.events.call_ended.is_set():
                r = handle_disconnect()
                if r == "exit": break
                if r == "jump": break

                slice_to = 0.25
                if deadline is not None:
                    remain = deadline - time.time()
                    if remain <= 0:
                        break
                    slice_to = min(slice_to, max(0.01, remain))
                ch = client.wait_for_digit(timeout=slice_to)
                if ch is None:
                    continue
                if ch in terms:
                    break
                s += ch

            # if stop_event.is_set() or client.events.call_ended.is_set():
            #     break
            r = after_blocking()
            if r == "exit": break
            if r == "jump": continue
            client.state.kv_dict[var] = s
        elif cmd == "SWITCH":
            var = args[0]
            spec = " ".join(args[1:])
            cases, default = _parse_cases(spec, labels)
            # print(cases, default)
            val = str(client.state.kv_dict.get(var, ""))
            dest = cases.get(val, default)
            if dest is None:
                logger.error(f"SWITCH no match for '{val}' and no DEFAULT")
            else:
                pc = dest
                continue
        elif cmd == "IF_EQ":
            # Syntax: IF_EQ <var> <value> <label>
            # Example: IF_EQ choice 1 SALES
            #          IF_EQ phrase "HELLO WORLD" NEXT
            if len(args) < 3:
                logger.error("IF_EQ requires: IF_EQ <var> <value> <label>")
            else:
                var = args[0]
                label = args[-1].upper()
                raw_value = " ".join(args[1:-1])
                expected = _strip_quotes(raw_value)

                actual = client.state.kv_dict.get(var)
                a = _coerce_literal(actual)
                b = _coerce_literal(expected)

                match = (a == b) or (str(a) == str(b))  # tolerant fallback compare

                if match:
                    if label not in labels:
                        logger.error(f"Label '{label}' not found")
                        break
                    pc = labels[label]
                    continue
        elif cmd == "SOFTKEY":
            softkey_name = " ".join(args[0:])
            client.press_softkey(softkey_name)
            sleep_interruptible(0.5, stop_event, client.events.call_ended)
        elif cmd == "SET":
            kv_pair = " ".join(args[0:])
            key, value = kv_pair.split("=")
            client.state.kv_dict[key] = value
        elif cmd == "DIAL" or cmd == "CALL":
            if cmd == "CALL":
                client.press_softkey("NewCall")
                sleep_interruptible(0.5, stop_event, client.events.call_ended)

            digit_string = "".join(args[0:])
            for d in digit_string:
                if d == "*":
                    d_code = chr(0x0e)
                elif d == "#":
                    d_code = chr(0x0f)
                else:
                    d_code = d

                handle_keypad_press(client, 1, d_code)
                client.play_beep()
                sleep_interruptible(0.5, stop_event, client.events.call_ended)
        elif cmd == "HOLD":
            client.press_softkey("Hold")
        elif cmd == "RESUME":
            client.press_softkey("Resume")
        elif cmd == "END":
            client.press_softkey("EndCall")
        elif cmd == "PLAY":
            filename = args[0]
            client.state._rtp_tx.send_wav(filename, loop=False)
        elif cmd == "GOTO":
            label = args[0].upper()
            if label not in labels:
                logger.error(f"Label '{label}' not found")
                break
            pc = labels[label]
            continue
        elif cmd == "IF":
            condition = args[0].upper()
            label = args[1].upper()
            # Simple conditions for now: CALL_ACTIVE, NO_CALL
            if condition == "CALL_ACTIVE" and client.state.call_active:
                pc = labels.get(label, pc + 1)
                continue
            elif condition == "NO_CALL" and not client.state.call_active:
                pc = labels.get(label, pc + 1)
                continue
        elif cmd == "EXIT":
            break
        else:
            logger.warning(f"Unknown instruction: {cmd}")

        pc += 1

        r = handle_disconnect()
        if r == "exit":
            break
        if r == "jump":
            continue
