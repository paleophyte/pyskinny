"""Shared IVR/macro script parser (client macro_cli and sim IVR runner)."""

from __future__ import annotations


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
