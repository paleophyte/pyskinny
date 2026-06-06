"""Print SoftKeyTemplate / SoftKeySet from a live CM registration (lab diagnostic)."""

from __future__ import annotations

import argparse
import logging
import time

import messages  # noqa: F401

from client import SCCPClient
from state import PhoneState
from utils.cli_media import add_connection_cli_args, init_phone_state_from_args
from utils.logs import add_logging_cli_args, configure_logging_from_verbose
from utils.softkeys import connected_softkey_labels, template_label_set


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register and dump softkey template from CM")
    add_connection_cli_args(parser, required=True)
    add_logging_cli_args(parser)
    args = parser.parse_args(argv)

    configure_logging_from_verbose(args.verbose, log_file=args.log_file)
    state = init_phone_state_from_args(args)
    state.enable_audio = False
    client = SCCPClient(state)
    client.get_tftp_config = False
    client.start()

    if not state.is_registered.wait(timeout=60):
        print(f"FAILED: {state.device_name} did not register on {state.server}")
        client.stop()
        return 1

    time.sleep(1.0)
    labels = sorted(template_label_set(state.softkey_template or {}))
    print(f"device={state.device_name} model={state.model_name}")
    print(f"template_labels ({len(labels)}): {labels}")
    for pos, entry in sorted(state.softkey_template.items(), key=lambda x: int(x[0])):
        print(f"  [{pos}] {entry.get('label')!r} event={entry.get('event')}")

    for set_idx in sorted(state.softkey_set_definition.keys(), key=int):
        name = {
            "0": "On Hook",
            "1": "Connected",
            "2": "On Hold",
            "3": "Ring In",
        }.get(set_idx, f"set {set_idx}")
        keys = state.get_current_softkeys(int(set_idx))
        print(f"set {set_idx} ({name}): {[lab for lab, ev in keys]}")

    connected = connected_softkey_labels(
        state.softkey_set_definition or {},
        state.softkey_template or {},
    )
    print(f"connected_set_labels: {connected}")
    if "Hold" not in labels:
        print("WARNING: Hold not in SoftKeyTemplate — assign Standard SCCP softkey template in CUCM")

    client.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
