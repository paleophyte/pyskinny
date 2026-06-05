"""Print ButtonTemplateRes from a live CM registration (CM2 / button-phone diagnostic)."""

from __future__ import annotations

import argparse
import logging
import time

import messages  # noqa: F401

from client import SCCPClient
from utils.buttons import hold_resume_hints, iter_template_buttons
from utils.cli_media import add_connection_cli_args, init_phone_state_from_args
from utils.logs import configure_logging_from_verbose


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register and dump button template from CM (CM2 / 79xx button layout)",
    )
    add_connection_cli_args(parser, required=True)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args(argv)

    configure_logging_from_verbose(args.verbose)
    state = init_phone_state_from_args(args)
    state.enable_audio = False
    client = SCCPClient(state)
    client.get_tftp_config = False
    client.start()

    if not state.is_registered.wait(timeout=60):
        print(f"FAILED: {state.device_name} did not register on {state.server}")
        client.stop()
        return 1

    time.sleep(1.5)

    print(f"device={state.device_name} model={state.model_name}")
    if state.softkey_template:
        print(
            "NOTE: This phone has SoftKeyTemplateRes — use python -m utils.dump_softkeys instead."
        )

    if not state.button_template:
        print("WARNING: No ButtonTemplateRes received (empty button_template)")
        client.stop()
        return 1

    print(
        f"button_template: offset={state.button_offset} "
        f"count={state.button_count} total={state.total_button_count}"
    )
    buttons = list(iter_template_buttons(state))
    print(f"defined_buttons ({len(buttons)}):")
    for pos, meta, label in buttons:
        btn_type = int(meta.get("type", 0))
        instance = int(meta.get("instance", 0))
        print(
            f"  [{pos}] {label!r}  type={btn_type} instance={instance}  "
            f"(Stimulus: type={btn_type}, instance={instance})"
        )

    hints = hold_resume_hints(state)
    print()
    if hints["uses_softkeys"]:
        print("hold/resume: use SoftKey Hold/Resume (see dump_softkeys).")
    else:
        print(
            f"hold/resume (button phone): Stimulus type {hints['hold_stimulus']} "
            f"on line {hints['default_line_instance']} (Virtual30 hold toggle; "
            f"see vphone_hold_unhold.pcap)."
        )
        print("  client.press_hold()   # or press_resume()")
        if hints["line_buttons"]:
            print("line_buttons:")
            for pos, inst, label in hints["line_buttons"]:
                print(f"  pos {pos}: {label} -> press_stimulus(9, {inst})  # Line")

    client.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
