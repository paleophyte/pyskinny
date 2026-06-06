# Lab: Hold / Resume softkeys on live CallManager

pyskinny sends **SoftKeyEvent** (message `0x0026`) using the event id from **SoftKeyTemplateRes**. Hold only works when CUCM gives the phone a template that includes **Hold** and **Resume** and maps them on the **Connected** / **On Hold** sets.

## Quick check from the repo

```bash
pip install -e ".[dev]"

# After configuring examples/cli.config or flags:
python -m utils.dump_softkeys --config
# or:
python -m utils.dump_softkeys --server 10.0.0.180 --mac 222233334444 --model 7970
```

You should see `Hold` and `Resume` in `template_labels`, and `Hold` in `connected_set_labels`.

## CUCM / CallManager (typical)

1. Open the **device** or **device profile** for the lab phone (e.g. SEP222233334444).
2. Set **Softkey Template** to a standard template (e.g. *Standard 7940/7960/7970* or your site default) — not a minimal custom template with only EndCall.
3. Ensure the **Hold** feature is available on the line / device (no conflicting restriction).
4. Reset the phone or restart SCCP so it pulls an updated template after changes.

On **CM 2.x** (button phones, no softkeys), hold uses **Stimulus 3** on the line button, not SoftKeyEvent. pyskinny sends that from console `h` when no softkey template is present. See [lab-cm2-buttons.md](lab-cm2-buttons.md) for the Virtual30 button map and hold capture (`vphone_hold_unhold.pcap`).

**cm31 / cm33:** integration `test_hold_and_resume` may still **skip** if CM reports `Hold` in the display prompt but `call_state` stays Connected (SetLamp-only update). A hold pcap during SoftKey Hold helps debug that path.

## Run integration test

```powershell
$env:PYSKINNY_INTEGRATION_LABS = "cm41"
$env:PYSKINNY_SKIP_TFTP = "1"
pytest tests/test_integration_live.py -m "integration and cm41" -k hold -v --no-audio
```

If the template is correct but hold still fails, capture Skinny on the phone during Hold (tshark port 2000) and compare SoftKeyEvent + CallState to the simulator.

## In-app controls

- **Console:** `h` toggles hold/resume when softkeys exist.
- **CLI:** `phone hold` / `phone resume`
- **Web UI:** Hold/Resume buttons when the template exposes those labels (`--web-port` on console/CLI/macro).
