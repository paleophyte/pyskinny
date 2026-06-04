"""Shared macro runtime: prompt playback with DTMF barge-in (sim + client)."""

from __future__ import annotations

import logging
import time
import wave
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def wav_duration_sec(path: str | Path) -> float:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate() or 8000
        return wf.getnframes() / float(rate)


def play_prompt_with_barge_in(
    *,
    path: str | Path,
    start: Callable[[str], None],
    stop: Callable[[], None],
    poll_digit: Callable[[], str | None],
    should_abort: Callable[[], bool] | None = None,
    log: logging.Logger | None = None,
    log_ctx: str = "",
) -> bool:
    """
    Play a WAV until it finishes or a digit is pressed (peek, not consume).

    Returns True if the caller pressed a key during the prompt (barge-in).
    """
    log = log or logger
    resolved = Path(path)
    if not resolved.is_file():
        log.warning("PLAY missing file %s %s", log_ctx, resolved)
        return False

    p = str(resolved)
    start(p)
    delay = wav_duration_sec(p)
    log.info("PLAY %s %s (%.1fs)", log_ctx, resolved.name, delay)
    end = time.time() + delay
    abort = should_abort or (lambda: False)

    while time.time() < end and not abort():
        digit = poll_digit()
        if digit is not None:
            stop()
            log.info(
                "IVR barge-in %s key=%r (after %.2fs)",
                log_ctx,
                digit,
                delay - (end - time.time()),
            )
            return True
        time.sleep(0.05)

    return False


def peek_dtmf_digit(client) -> str | None:
    """Return next queued DTMF digit without removing it (for barge-in during PLAY)."""
    with client.dtmf.lock:
        if client.dtmf.buf:
            return client.dtmf.buf[0]
    return None
