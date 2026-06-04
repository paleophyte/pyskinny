"""Shared IVR/macro script parser (client macro_cli and sim IVR runner)."""

from __future__ import annotations

import re

_MACRO_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class MacroInstruction:
    def __init__(self, command, args=None, label=None):
        self.command = command
        self.args = args or []
        self.label = label


def parse_macro_script(script: str) -> tuple[list[MacroInstruction], dict[str, int]]:
    instructions: list[MacroInstruction] = []
    labels: dict[str, int] = {}

    lines = [line.strip() for line in script.replace(",", "\n").splitlines() if line.strip()]
    for line in lines:
        if line.startswith("#"):
            continue
        if line.endswith(":"):
            label = line[:-1].strip().upper()
            labels[label] = len(instructions)
            continue

        parts = line.split()
        command = parts[0].upper()
        args = parts[1:]
        instructions.append(MacroInstruction(command, args))

    return instructions, labels


def parse_switch_cases(spec: str, labels: dict[str, int]) -> tuple[dict[str, int | None], int | None]:
    cases: dict[str, int | None] = {}
    default = None
    for tok in spec.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        key, value = tok.split(":", 1)
        if key.strip().upper() == "DEFAULT":
            default = labels.get(value.strip().upper())
        else:
            cases[key.strip()] = labels.get(value.strip().upper())
    return cases, default


def expand_macro_vars(values: dict, text: str) -> str:
    """Replace $name tokens from a kv dict (unknown names left as-is)."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return str(values[key])

    return _MACRO_VAR.sub(repl, text)


def resolve_macro_value(values: dict, raw: str) -> str:
    """
    Resolve a macro argument that may use $vars or name a kv entry directly.

    Examples: ``1001``, ``$service_dn``, ``extension`` (when extension is in values).
    """
    text = raw.strip()
    if not text:
        return ""
    expanded = expand_macro_vars(values, text)
    if "$" in text or expanded != text:
        return expanded
    if text in values:
        return str(values[text])
    return text
