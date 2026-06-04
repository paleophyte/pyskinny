"""Keypad-driven virtual IVR menu (Skinny KeypadButton, not in-band DTMF)."""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from simulator import payloads

if TYPE_CHECKING:
    from simulator.call_hub import CallHub, SimCall
    from simulator.media_hub import SimMediaHub

logger = logging.getLogger(__name__)

DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent / "ivr_assets"


class IvrMenu:
    """
    Plays bundled WAV prompts over sim RTP, then accepts keypad choices.

    Keys (during connected IVR call):
      1 — loopback echo
      2 — test tone
      9 / # — hang up
    """

    def __init__(self, assets_dir: Path | str | None = None):
        self.assets_dir = Path(assets_dir) if assets_dir else DEFAULT_ASSETS_DIR

    def asset_path(self, name: str) -> Path | None:
        path = self.assets_dir / name
        return path if path.is_file() else None

    def welcome_path(self) -> Path | None:
        return self.asset_path("welcome.wav")

    @staticmethod
    def wav_duration_sec(path: Path) -> float:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate() or 8000
            return wf.getnframes() / float(rate)

    def on_media_started(self, call: SimCall, hub: SimMediaHub) -> None:
        welcome = self.welcome_path()
        if welcome:
            logger.info(
                "IVR welcome prompt ref=%s path=%s (%.1fs)",
                call.call_ref,
                welcome.name,
                self.wav_duration_sec(welcome),
            )
        call.caller.send(
            payloads.display_prompt_status(
                "IVR: 1=loop 2=tone 9=exit",
                call.line,
                call.call_ref,
            )
        )

    def on_keypad(self, call: SimCall, digit: str, hub: CallHub) -> None:
        media = hub.media_hub
        if not media:
            logger.warning("IVR keypad %r ignored ref=%s (no media hub)", digit, call.call_ref)
            return

        line, ref = call.line, call.call_ref
        caller = call.caller

        if digit == "1":
            media.set_loopback(ref)
            caller.send(payloads.display_prompt_status("Loopback", line, ref))
            logger.info("IVR menu ref=%s selected loopback", ref)
            return

        if digit == "2":
            media.set_tone(ref)
            caller.send(payloads.display_prompt_status("Tone test", line, ref))
            logger.info("IVR menu ref=%s selected tone", ref)
            return

        if digit in ("9", "#"):
            logger.info("IVR menu ref=%s hangup key %r", ref, digit)
            hub.end_call(call_ref=ref)
            return

        logger.debug("IVR menu ref=%s ignored key %r", ref, digit)
