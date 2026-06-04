"""Keypad-driven virtual IVR menu (Skinny KeypadButton, not in-band DTMF)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from simulator.ivr_macro_runner import DEFAULT_IVR_SCRIPT, SimIvrMacroRunner

if TYPE_CHECKING:
    from simulator.call_hub import CallHub, SimCall

logger = logging.getLogger(__name__)

DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent / "ivr_assets"
DEFAULT_MACRO_FILE = "ivr.macro"


class IvrMenu:
    """
    Virtual IVR driven by a .macro script (same format as examples/ivr.macro).

    Default script: simulator/ivr_assets/ivr.macro or built-in DEFAULT_IVR_SCRIPT.
    Sim-only commands: LOOPBACK, TONE, PROMPT, END/HANGUP.
    """

    def __init__(self, assets_dir: Path | str | None = None, macro_file: str | None = None):
        self.assets_dir = Path(assets_dir) if assets_dir else DEFAULT_ASSETS_DIR
        self.macro_file = macro_file or DEFAULT_MACRO_FILE
        self._runners: dict[int, SimIvrMacroRunner] = {}

    def script_text(self) -> str:
        path = self.assets_dir / self.macro_file
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return DEFAULT_IVR_SCRIPT

    def on_media_started(self, call: SimCall, hub: CallHub) -> None:
        media = hub.media_hub
        if media is None:
            return
        runner = SimIvrMacroRunner(
            call,
            hub,
            media,
            assets_dir=self.assets_dir,
            script_text=self.script_text(),
        )
        self._runners[call.call_ref] = runner
        runner.start()
        logger.info(
            "IVR macro started ref=%s script=%s",
            call.call_ref,
            self.macro_file if (self.assets_dir / self.macro_file).is_file() else "(built-in)",
        )

    def on_keypad(self, call: SimCall, digit: str, hub: CallHub) -> None:
        runner = self._runners.get(call.call_ref)
        if runner is not None:
            runner.submit_digit(digit)
            return
        logger.debug("IVR keypad %r ignored ref=%s (no runner)", digit, call.call_ref)

    def on_call_ended(self, call_ref: int) -> None:
        runner = self._runners.pop(call_ref, None)
        if runner is not None:
            runner.stop()
