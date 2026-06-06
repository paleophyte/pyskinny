"""Logging helpers."""

from __future__ import annotations

import logging

from utils.logs import attach_log_file, configure_logging_from_verbose


def test_configure_logging_writes_to_log_file(tmp_path):
    log_path = tmp_path / "T6.debug.txt"
    configure_logging_from_verbose(3, log_file=log_path)
    logging.getLogger("test.logs").info("registration trace")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "registration trace" in text
    assert "test.logs" in text


def test_attach_log_file_creates_parent_dirs(tmp_path):
    log_path = tmp_path / "nested" / "run.debug.txt"
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    attach_log_file(log_path, level=logging.INFO)
    logging.getLogger("test.logs").info("nested path ok")
    for handler in root.handlers:
        handler.flush()
    assert log_path.read_text(encoding="utf-8").strip()
