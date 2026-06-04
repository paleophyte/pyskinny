"""RTP packet counters for media troubleshooting."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class RTPStats:
    rx_packets: int = 0
    tx_packets: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_seq_gaps: int = 0
    rx_pt_unknown: int = 0
    last_rx_pt: int | None = None
    last_tx_pt: int | None = None
    last_rx_ssrc: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    _last_rx_seq: int | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def note_rx(self, pt: int, seq: int, ssrc: int, payload_len: int, *, known_codec: bool) -> None:
        with self._lock:
            self.rx_packets += 1
            self.rx_bytes += payload_len
            self.last_rx_pt = pt
            self.last_rx_ssrc = ssrc
            if not known_codec:
                self.rx_pt_unknown += 1
            if self._last_rx_seq is not None:
                expected = (self._last_rx_seq + 1) & 0xFFFF
                if seq != expected:
                    self.rx_seq_gaps += 1
            self._last_rx_seq = seq

    def note_tx(self, pt: int, payload_len: int) -> None:
        with self._lock:
            self.tx_packets += 1
            self.tx_bytes += payload_len
            self.last_tx_pt = pt

    def summary(self) -> str:
        with self._lock:
            elapsed = max(time.monotonic() - self.started_at, 0.001)
            rx_rate = self.rx_packets / elapsed
            tx_rate = self.tx_packets / elapsed
            return (
                f"rx={self.rx_packets} pkts ({self.rx_bytes} B, {rx_rate:.1f}/s) "
                f"tx={self.tx_packets} pkts ({self.tx_bytes} B, {tx_rate:.1f}/s) "
                f"seq_gaps={self.rx_seq_gaps} unknown_pt={self.rx_pt_unknown} "
                f"last_rx_pt={self.last_rx_pt} last_tx_pt={self.last_tx_pt}"
            )


class RTPStatsMonitor:
    """Optional periodic RTP stats logging while media is active."""

    def __init__(self, stats: RTPStats, log, interval: float = 5.0):
        self.stats = stats
        self.log = log
        self.interval = max(float(interval), 0.0)
        self._stop = threading.Event()
        self._thr: threading.Thread | None = None

    def start(self) -> None:
        if self.interval <= 0:
            return
        self._thr = threading.Thread(target=self._run, name="RTPStatsMonitor", daemon=True)
        self._thr.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=1.0)
        self._thr = None

    def log_final(self) -> None:
        self.log.info("[RTP stats] %s", self.stats.summary())

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.log.info("[RTP stats] %s", self.stats.summary())
