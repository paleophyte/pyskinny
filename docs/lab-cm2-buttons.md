# Lab: CM2 button template and hold

CM2-era phones (**Virtual30SPplus**, 7910-class) use **ButtonTemplateRes** (message `0x0097`) and **Stimulus** (`0x0005`), not LCD softkeys.

## Dump live template from CM

```bash
pip install -e ".[dev]"

python -m utils.dump_buttons --server 10.0.0.11 --device-name pyskinny01 --model Virtual30SPplus
# or from examples/cli.config:
python -m utils.dump_buttons --config
```

You should see four **Line** buttons plus feature keys (Call Park, Redial, Speed Dials, etc.).

## Hold on button phones

The template usually does **not** include a dedicated Hold button. pyskinny sends **HookFlash** (Skinny message `0x0008`) via `press_hold()` / `press_resume()` — a toggle on CM2 / Virtual30 builds:

```python
client.press_hold()
client.press_resume()
```

Compare with softkey phones: `python -m utils.dump_softkeys` and [lab-softkey-hold.md](lab-softkey-hold.md).

## Hold in code

`SCCPClient.press_hold()` / `press_resume()` send **HookFlash** when `uses_physical_buttons()` is true. Integration accepts CallState 8, a hold prompt, stopped media, or callee “remote hold” prompt.

```powershell
$env:PYSKINNY_INTEGRATION_LABS = "cm2"
$env:PYSKINNY_SKIP_TFTP = "1"
pytest tests/test_integration_live.py -k "hold and cm2" -v --no-audio
```

If the test **skips**, CM may not be sending hold signals this client recognizes (CallState 8, hold prompt, or stopped RTP). Capture Skinny during a manual hold on a real 7910 against the same CM, or confirm hold/MOH is enabled on the line in CM administration.
