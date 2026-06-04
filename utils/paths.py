"""Resolve files shipped inside the installed pyskinny package."""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def read_package_data(package: str, *parts: str) -> str:
    """Read UTF-8 text from a file bundled with *package*."""
    ref = files(package)
    for part in parts:
        ref = ref / part
    if hasattr(ref, "read_text"):
        return ref.read_text(encoding="utf-8")
    with as_file(ref) as path:
        return path.read_text(encoding="utf-8")


def read_text_file_or_bundle(path: str) -> str:
    """
    Read a repo-relative path (e.g. ui/cli_commands.json) from disk or,
    when installed, from package data.
    """
    p = Path(path)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    normalized = path.replace("\\", "/")
    if "/" in normalized:
        package, rel = normalized.split("/", 1)
        return read_package_data(package, rel)
    raise FileNotFoundError(path)
