"""Shared Skinny message name registry and tftpy log filter."""

from __future__ import annotations

import logging

from utils.skinny_messages import get_message_name
from utils.tftp_logging import TftpyLogFilter, configure_tftpy_logging


def test_skinny_message_names_without_importing_handlers():
    assert get_message_name(0x0026) == "SoftKeyEvent"
    assert get_message_name(0x008B) == "StopMediaTransmission"
    assert get_message_name(0x011F) == "FeatureStatRes"
    assert get_message_name(0x9999) == "Unknown (0x9999)"


def test_tftpy_filter_resend_dat():
    filt = TftpyLogFilter()
    record = logging.LogRecord(
        name="tftpy.TftpStates",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg=(
            "Resending packet DAT packet: block 2\n"
            "    data: 506 bytes on sessions <TftpStateExpectACK>"
        ),
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert record.getMessage() == "Resending DAT block 2 (506 bytes)"


def test_tftpy_filter_missing_file_downgrade():
    filt = TftpyLogFilter()
    record = logging.LogRecord(
        name="tftpy.TftpServer",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=(
            "Fatal exception thrown from session 127.0.0.1:58551: "
            r"File not found: C:\temp\pyskinny-tftp\gkdefault.cfg"
        ),
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert record.levelno == logging.INFO
    assert record.getMessage() == "TFTP request for missing file: gkdefault.cfg"


def test_configure_tftpy_logging_idempotent():
    configure_tftpy_logging(level=logging.WARNING)
    log = logging.getLogger("tftpy.TftpStates")
    assert any(isinstance(f, TftpyLogFilter) for f in log.filters)
