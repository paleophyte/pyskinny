"""Macro script parser tests."""

from utils.macro_script import parse_macro_script, parse_switch_cases


def test_parse_macro_skips_comments_and_labels():
    script = """
# comment
TOP:
WAIT 1
GOTO MENU
MENU:
END
"""
    instructions, labels = parse_macro_script(script)
    assert labels["TOP"] == 0
    assert labels["MENU"] == 2
    assert instructions[0].command == "WAIT"
    assert instructions[2].command == "END"


def test_parse_switch_cases():
    labels = {"A": 10, "B": 20, "FALLBACK": 30}
    cases, default = parse_switch_cases("1:A;2:B;DEFAULT:FALLBACK", labels)
    assert cases["1"] == 10
    assert cases["2"] == 20
    assert default == 30
