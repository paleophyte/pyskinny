"""Run .macro scripts on the sim virtual IVR (caller-side, keypad-driven)."""

from __future__ import annotations

import logging
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from simulator import payloads
from utils.macro_script import parse_macro_script, parse_switch_cases

if TYPE_CHECKING:
    from simulator.call_hub import CallHub, SimCall
    from simulator.media_hub import SimMediaHub

logger = logging.getLogger(__name__)

DEFAULT_IVR_SCRIPT = """
# Sim virtual IVR — caller dials --ivr-dn (same syntax as examples/ivr.macro)
ON_DISCONNECT END

START:
PLAY welcome.wav
GOTO MENU

MENU:
WAIT_DIGIT 0
SWITCH last_digit 1:LOOPBACK;2:TONE;9:HANGUP;#:HANGUP;DEFAULT:MENU

LOOPBACK:
LOOPBACK
PROMPT Loopback active
GOTO MENU

TONE:
TONE
PROMPT Tone test
GOTO MENU

HANGUP:
END
"""


def wav_duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate() or 8000
        return wf.getnframes() / float(rate)


class SimIvrMacroRunner:
    """Execute a macro script for one connected IVR call."""

    def __init__(
        self,
        call: SimCall,
        hub: CallHub,
        media: SimMediaHub,
        *,
        assets_dir: Path,
        script_text: str,
    ):
        self.call = call
        self.hub = hub
        self.media = media
        self.assets_dir = assets_dir
        self.instructions, self.labels = parse_macro_script(script_text)
        self.kv: dict[str, str] = {}
        self.pc = 0
        self.on_disc = ("END", None)
        self._stop = threading.Event()
        self._digit_event = threading.Event()
        self._digit_queue: deque[str] = deque()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"sim-ivr-{self.call.call_ref}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._digit_event.set()

    def submit_digit(self, digit: str) -> None:
        self.kv["last_digit"] = digit
        self._digit_queue.append(digit)
        self._digit_event.set()
        if self.media.stop_playback(self.call.call_ref):
            logger.info("IVR barge-in ref=%s key=%r", self.call.call_ref, digit)

    def _take_digit(self) -> str | None:
        if self._digit_queue:
            return self._digit_queue.popleft()
        return self.kv.get("last_digit")

    def _resolve_play_path(self, raw: str) -> Path | None:
        name = raw.replace("\\", "/").lstrip("/")
        if name.startswith("media/"):
            name = name[6:]
        for candidate in (self.assets_dir / name, self.assets_dir / "media" / name):
            if candidate.is_file():
                return candidate
        return None

    def _play(self, raw: str) -> None:
        path = self._resolve_play_path(raw)
        if path is None:
            logger.warning("IVR PLAY missing file %r ref=%s", raw, self.call.call_ref)
            return
        self.media.play_wav(self.call.call_ref, str(path))
        delay = wav_duration_sec(path)
        logger.info("IVR PLAY ref=%s %s (%.1fs)", self.call.call_ref, path.name, delay)
        end = time.time() + delay
        while time.time() < end and not self._stop.is_set():
            if self._digit_queue:
                logger.debug(
                    "IVR PLAY interrupted ref=%s after %.2fs (barge-in)",
                    self.call.call_ref,
                    delay - (end - time.time()),
                )
                break
            time.sleep(min(0.05, max(0.0, end - time.time())))

    def _wait_digit(self, secs: float) -> str | None:
        if self._digit_queue:
            return self._take_digit()
        self._digit_event.clear()
        deadline = None if secs <= 0 else (time.time() + secs)
        while not self._stop.is_set():
            if self._digit_event.wait(timeout=0.25):
                self._digit_event.clear()
                digit = self._take_digit()
                if digit is not None:
                    return digit
            if deadline is not None and time.time() >= deadline:
                return None
        return None

    def _prompt(self, text: str) -> None:
        self.call.caller.send(
            payloads.display_prompt_status(text, self.call.line, self.call.call_ref)
        )

    def _run(self) -> None:
        try:
            while self.pc < len(self.instructions) and not self._stop.is_set():
                instr = self.instructions[self.pc]
                cmd = instr.command
                args = instr.args
                logger.info("IVR ref=%s exec: %s %s", self.call.call_ref, cmd, args)

                if cmd == "ON_DISCONNECT":
                    mode = args[0].upper() if args else "NONE"
                    if mode == "END":
                        self.on_disc = ("END", None)
                    elif mode == "GOTO" and len(args) >= 2:
                        self.on_disc = ("GOTO", args[1].upper())
                    else:
                        self.on_disc = ("NONE", None)
                elif cmd == "PLAY":
                    self._play(" ".join(args))
                elif cmd == "WAIT_DIGIT":
                    secs = float(args[0]) if args else 0.0
                    ch = self._wait_digit(secs)
                    if self._stop.is_set():
                        break
                    if ch is None:
                        logger.warning("IVR WAIT_DIGIT timeout ref=%s", self.call.call_ref)
                    else:
                        self.kv["last_digit"] = ch
                elif cmd == "SWITCH":
                    var = args[0]
                    spec = " ".join(args[1:])
                    cases, default = parse_switch_cases(spec, self.labels)
                    val = str(self.kv.get(var, ""))
                    dest = cases.get(val, default)
                    if dest is None:
                        logger.error("IVR SWITCH no match %r ref=%s", val, self.call.call_ref)
                    else:
                        self.pc = dest
                        continue
                elif cmd == "GOTO":
                    label = args[0].upper()
                    dest = self.labels.get(label)
                    if dest is None:
                        logger.error("IVR GOTO unknown label %s", label)
                        break
                    self.pc = dest
                    continue
                elif cmd == "LOOPBACK":
                    self.media.set_loopback(self.call.call_ref)
                elif cmd == "TONE":
                    self.media.set_tone(self.call.call_ref)
                elif cmd == "PROMPT":
                    self._prompt(" ".join(args))
                elif cmd in ("END", "HANGUP", "EXIT"):
                    self.hub.end_call(call_ref=self.call.call_ref)
                    break
                else:
                    logger.warning("IVR unsupported command %s ref=%s", cmd, self.call.call_ref)

                self.pc += 1
        except Exception:
            logger.exception("IVR macro runner failed ref=%s", self.call.call_ref)
        finally:
            self._stop.set()
