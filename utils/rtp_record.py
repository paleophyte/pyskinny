"""Record decoded RTP PCM to WAV files (RX / TX legs)."""

from __future__ import annotations

import os
import threading
import wave
from datetime import datetime

import numpy as np


class RTPRecorder:
    """Thread-safe float32 mono recorder; writes 16-bit PCM WAV on close()."""

    def __init__(
        self,
        base_path: str,
        *,
        sr: int = 8000,
        record_rx: bool = True,
        record_tx: bool = True,
        log=None,
    ):
        self.sr = sr
        self.log = log
        self.rx_path = f"{base_path}_rx.wav" if record_rx else None
        self.tx_path = f"{base_path}_tx.wav" if record_tx else None
        self._lock = threading.Lock()
        self._rx_frames: list[np.ndarray] = []
        self._tx_frames: list[np.ndarray] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def write_rx(self, pcm: np.ndarray) -> None:
        if self._closed or self.rx_path is None or pcm.size == 0:
            return
        with self._lock:
            self._rx_frames.append(pcm.astype(np.float32, copy=True))

    def write_tx(self, pcm: np.ndarray) -> None:
        if self._closed or self.tx_path is None or pcm.size == 0:
            return
        with self._lock:
            self._tx_frames.append(pcm.astype(np.float32, copy=True))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            rx_path = self._write_wav(self.rx_path, self._rx_frames) if self.rx_path else None
            tx_path = self._write_wav(self.tx_path, self._tx_frames) if self.tx_path else None
        if self.log:
            self.log.info("[RTP record] saved rx=%s tx=%s", rx_path, tx_path)

    def _write_wav(self, path: str, frames: list[np.ndarray]) -> str | None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not frames:
            return None
        f32 = np.clip(np.concatenate(frames), -1.0, 1.0)
        pcm = (f32 * 32767.0).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sr)
            wf.writeframes(pcm.tobytes())
        return path


def rtp_record_base_path(state, call_ref: int) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ref = f"{call_ref:08X}" if call_ref else "00000000"
    device = getattr(state, "device_name", None) or "phone"
    record_dir = getattr(state, "rtp_record_dir", None) or "logs/rtp"
    return os.path.join(record_dir, f"{device}_{ref}_{ts}")
