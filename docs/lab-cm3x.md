# Lab: CallManager 3.x (cm31, cm33)

pyskinny targets **CM 3.1** (`cm31`, `10.0.0.181`) and **CM 3.3** (`cm33`, `10.0.0.182`) with **7960** and **7970** softkey phones. Same SCCP stack as CM 4.x, but a few wire-format and registration differences matter when debugging.

**Related docs**

| Topic | Doc |
|-------|-----|
| Softkey hold / resume | [lab-softkey-hold.md](lab-softkey-hold.md) |
| CM2 button phones (not cm31/cm33) | [lab-cm2-buttons.md](lab-cm2-buttons.md) |
| Multi-console scenarios | [lab-cookbook.md](lab-cookbook.md) |

---

## Models and registration

| Lab | CM | Phone model | Skinny enum (`--model`) |
|-----|-----|-------------|-------------------------|
| cm31 | 3.1 | Cisco 7960 | `7960` |
| cm33 | 3.3 | Cisco 7970 | `7970` |

Use **SEP + MAC** device names (e.g. `SEP222233334444`), not CM2-style `pyskinny01`.

```powershell
$env:PYSKINNY_SKIP_TFTP = "1"
python -m examples.run_console --server 10.0.0.181 --mac 222233334444 --model 7960 --skip_tftp
python -m utils.dump_softkeys --server 10.0.0.181 --mac 222233334444 --model 7960
```

Registration completes when CM sends **TimeDateRes (`0x0094`)**; pyskinny then marks the client registered.

### FeatureStat (registration)

After button/line stat requests, pyskinny sends **FeatureStatReq (`0x0034`, line 1)**. CM answers with **FeatureStatRes (`0x011F`)**. Handlers live in `messages/capabilities.py`.

Older lab pcaps (`debugs/cm31_register.pcapng`, `debugs/cm33_register.pcapng`) were captured **before** the client sent `0x0034` (the phone sent `0x002D` on the wire instead). Those captures are still useful for SoftKeyTemplate, LineStat, etc., but they do **not** include FeatureStat on the wire. For fixture regression of the current sequence, re-capture registration with today's pyskinny (see [Registration captures](#registration-captures) below).

### LineStatRes and extension display

CM3.x **LineStatRes (`0x0092`)** carries the directory number (e.g. `1003`). cm33 payloads are **longer** than cm31 (extra label fields). The console header shows `L1: <DN>` from this message.

---

## OpenReceiveChannel (CM3.x payloads)

**OpenReceiveChannel (`0x0105`)** payloads on CM 3.1/3.3 are often **shorter** than on CM 4.x. Strict `struct.unpack` of the full CM4 layout used to crash; parsing now uses `Buf` with defaults for missing tail fields (`messages/phone.py`).

**CloseReceiveChannel (`0x0106`)** on cm31 can arrive with an **8-byte** body (no call ref tail). That path is handled separately from the 12-byte CM4.x form.

RTP RX still **auto-detects G.711** (PT 0/8) from incoming packets. `compression_type` from OpenReceiveChannel is not yet applied to the decoder unless we see a lab case where auto-detect fails.

---

## Hold (known integration skip)

On cm31/cm33, **SoftKey Hold** can update the display prompt to `Hold` while `call_state` stays **Connected** (last update from **SetLamp** only). Integration `test_hold_and_resume` may **skip** for that reason.

To debug: capture Skinny during Hold and Resume on a connected call ([lab-softkey-hold.md](lab-softkey-hold.md)). Compare **SoftKeyEvent**, **CallState**, **SetLamp**, and **StopMedia** / **StartMedia** to what pyskinny expects.

```powershell
pytest tests/test_integration_live.py -m "integration and cm31" -k hold -v --no-audio
```

---

## Integration tests

```powershell
$env:PYSKINNY_INTEGRATION_LABS = "cm31,cm33"
$env:PYSKINNY_SKIP_TFTP = "1"
pytest tests/test_integration_live.py -m integration -v --no-audio
```

Only one SCCP client per MAC at a time — stop consoles before running tests.

| Scenario | cm31 / cm33 typical result |
|----------|----------------------------|
| Register / unregister | Pass |
| Outbound connect / hangup | Pass |
| Blind transfer | Pass (three endpoints …444–446) |
| Consulted transfer | Pass |
| Hold / resume | May **skip** — see above |

---

## Capture regression fixtures

Committed wire hex from registration pcaps lives in `tests/fixtures/cucm_frames.json`:

- `cm31_reg` — from `debugs/cm31_register.pcapng`
- `cm33_reg` — from `debugs/cm33_register.pcapng`

Tests: `tests/test_cm3x_register_capture.py`.

Regenerate after new pcaps (requires tshark):

```powershell
# pcaps under debugs/
python -m utils.extract_cucm_capture_fixtures
pytest tests/test_cm3x_register_capture.py -v
```

The extractor reassembles the CM→phone TCP stream and pulls messages by Skinny ID (needed because **SoftKeyTemplateRes** spans multiple TCP segments).

### Registration captures

Grab a fresh registration when you change the client registration sequence or want FeatureStat on the wire:

```text
tshark -i <iface> -f "host 10.0.0.181 and tcp port 2000" -w cm31_register.pcapng
```

(or `10.0.0.182` for cm33)

1. Stop any console on that MAC.
2. Start the capture.
3. Run `run_console` (or pytest register test) through **TimeDateRes**.
4. Stop capture; save as `debugs/cm31_register.pcapng` / `debugs/cm33_register.pcapng`.
5. Run `python -m utils.extract_cucm_capture_fixtures` and commit the updated JSON + tests if bytes changed.

In Wireshark, confirm phone→CM **FeatureStatReq `0x0034`** and CM→phone **FeatureStatRes `0x011F`** appear before **TimeDateReq**.

---

## cm31 vs cm33 (quick diff)

| | cm31 (7960) | cm33 (7970) |
|---|-------------|-------------|
| CM IP | 10.0.0.181 | 10.0.0.182 |
| LineStatRes size | 76-byte wire example in fixtures | 116-byte (includes line label) |
| SoftKeyTemplateRes | Distinct blob in `cm31_reg` | Distinct blob in `cm33_reg` |
| Behavior in pyskinny | Same code path | Same code path |

For CM 4.x labs (cm41, cm43), use the same softkey docs; OpenReceiveChannel payloads are usually the longer CM4.x form.
