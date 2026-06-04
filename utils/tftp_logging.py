"""Normalize tftpy log noise for pyskinny sim / client runs."""

from __future__ import annotations

import logging
import re

_TFTPY_LOGGERS = ("tftpy", "tftpy.TftpServer", "tftpy.TftpStates", "tftpy.TftpContexts")

_RESEND = re.compile(
    r"Resending packet (.+?) on sessions ",
    re.DOTALL,
)
_DAT_BLOCK = re.compile(
    r"DAT packet:\s*block\s*(\d+)\s*data:\s*(\d+)\s*bytes",
    re.IGNORECASE,
)


class TftpyLogFilter(logging.Filter):
    """Compact tftpy resend lines and downgrade routine missing-file requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        flat = " ".join(msg.split())

        m = _RESEND.search(flat)
        if m:
            pkt = m.group(1).strip()
            dm = _DAT_BLOCK.search(pkt)
            if dm:
                block, nbytes = dm.group(1), dm.group(2)
                record.msg = "Resending DAT block %s (%s bytes)"
                record.args = (block, nbytes)
            else:
                record.msg = "Resending %s"
                record.args = (pkt,)
            return True

        if "Fatal exception thrown from session" in flat and "File not found:" in flat:
            path = flat.rsplit("File not found:", 1)[-1].strip()
            path = re.split(r"[/\\]", path)[-1]
            record.msg = "TFTP request for missing file: %s"
            record.args = (path,)
            record.levelno = logging.INFO
            record.levelname = "INFO"
            return True

        return True


def configure_tftpy_logging(*, level: int = logging.WARNING) -> None:
    """Attach compacting filter to tftpy loggers (idempotent)."""
    filt = TftpyLogFilter()
    for name in _TFTPY_LOGGERS:
        log = logging.getLogger(name)
        log.setLevel(level)
        if not any(isinstance(f, TftpyLogFilter) for f in log.filters):
            log.addFilter(filt)
