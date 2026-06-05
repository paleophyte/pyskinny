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

The template usually does **not** include a dedicated Hold button. Hold is sent as **Stimulus type 5** on the active line instance (toggle on many CM2 builds):

```python
client.press_stimulus(5, line_instance=1)
```

Compare with softkey phones: `python -m utils.dump_softkeys` and [lab-softkey-hold.md](lab-softkey-hold.md).

## Next: integration test

Once hold works manually on cm2 (`connect` + `press_stimulus(5, line)` + CallState 8), enable `test_hold_and_resume[cm2]` in `tests/test_integration_live.py` (today it is skipped).
