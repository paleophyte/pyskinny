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

The template usually does **not** include a dedicated Hold button. On Virtual30, the hold key sends **Stimulus type 3** on the line (toggle hold and resume). See `vphone_hold_unhold.pcap` at the repo root.

```python
client.press_hold()    # Stimulus(3, line) — same packet to resume
client.press_resume()  # alias for the same toggle
```

Compare with softkey phones: `python -m utils.dump_softkeys` and [lab-softkey-hold.md](lab-softkey-hold.md).

## Hold in code

`SCCPClient.press_hold()` sends **Stimulus(3, line)** when `uses_physical_buttons()` is true. CM2 often omits `CallState` Hold/OnHook; pyskinny tracks **SetLamp** on the line (mode 4 = hold, mode 1 = idle/end) so console/CLI stay in sync when the virtual phone hangs up.

```powershell
$env:PYSKINNY_INTEGRATION_LABS = "cm2"
$env:PYSKINNY_SKIP_TFTP = "1"
pytest tests/test_integration_live.py -k "hold and cm2" -v --no-audio
```

If the test **skips**, CM may not be sending hold signals this client recognizes (CallState 8, hold prompt, or stopped RTP). Capture Skinny during a manual hold on a real 7910 against the same CM, or confirm hold/MOH is enabled on the line in CM administration.

## Transfer (consult)

On Virtual30 there is no **Transfer** template button — use **Stimulus 4** (`press_transfer()`), not the **Conference** button (type 125).

**Consulted transfer** (what you described):

1. Connected to party A (e.g. 1099).
2. **Transfer** once → dial tone; original call held.
3. Dial consult target (e.g. 1091).
4. Answer on 1091.
5. **Transfer** again → completes bridge (1091 ↔ 1099); you drop.

**Blind transfer:** Transfer → dial → Transfer **without** waiting for answer.

Console: map an F-key to transfer via CLI `phone transfer 1091` after the first Transfer, or use macro `TRANSFER 1091` on a consult path. Digit keys during transfer dial the consult number.

**Blind transfer** (`blind_xfer.pcap`): Stimulus **4** → dial target (e.g. `1091`) → Stimulus **4** again → optional OnHook.

### Audio / console errors

Default `run_console` TX is **silence** (hear remote party via RX monitor). Use `--rtp-mic` only if you have a working microphone. Without it, PortAudio `device -1` errors came from the old default mic TX mode.

Codec warnings (`compression_type=160366308`) are noisy but usually non-fatal.

### Shutting down (`pgm_exit.pcap`)

Closing the virtual phone app sends **TCP FIN** on the Skinny socket — no extra Skinny message required. pyskinny should **`UnregisterReq`** on orderly quit (`q` in console); abrupt kill may leave a stale registration until CM times out.
