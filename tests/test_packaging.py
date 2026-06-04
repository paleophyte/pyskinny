"""Packaging and bundled asset checks."""

from __future__ import annotations

import json

from utils.paths import read_package_data, read_text_file_or_bundle


def test_bundled_cli_commands_json():
    raw = read_package_data("ui", "cli_commands.json")
    spec = json.loads(raw)
    assert isinstance(spec, list)
    assert spec[0]["command"]


def test_read_text_file_or_bundle_cli_spec():
    raw = read_text_file_or_bundle("ui/cli_commands.json")
    assert "command" in raw


def test_bundled_example_ivr_macro():
    raw = read_package_data("examples", "ivr.macro")
    assert "WAIT_CALL" in raw or "CALL" in raw
