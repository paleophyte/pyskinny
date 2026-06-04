# pyskinny lab cookbook (Skinny simulator)

End-to-end recipes for the **Skinny CallManager simulator** — no Windows CUCM VM required. Assumes you are in the repo root with dependencies installed:

```powershell
pip install -r requirements.txt -r requirements-dev.txt
```

Replace `<LAB_IP>` with an address other phones can reach (your LAN IP). On a single PC, `127.0.0.1` is fine for pyskinny clients only.

---

## 1. Start the simulator + admin UI

```powershell
python -m examples.run_simulator -vv `
  --advertise-host <LAB_IP> `
  --tftp-port 6969 `
  --ivr-dn 9999 `
  --admin-port 8090
```

| Flag | Purpose |
|------|---------|
| `--advertise-host` | IP written into TFTP XML (required when binding `0.0.0.0`) |
| `--tftp-port 6969` | Avoids needing Administrator/root for port 69 |
| `--ivr-dn 9999` | Virtual auto-answer IVR DN (uses `simulator/ivr_assets/ivr.macro`) |
| `--admin-port 8090` | Web admin: Reset, Restart, bulk actions, end call |

**Admin UI:** `http://<LAB_IP>:8090/` — select phones with checkboxes, use bulk **Restart** / **Reset** at top or bottom, or per-row buttons.

**Hardware phones on port 69:** run `python -m simulator.tftp_relay` elevated in a second terminal (see [README](../README.md#tftp-configs)).

---

## 2. Three-console lab (DNs 1000–1002)

With default `--dn-start 1000`, MACs are assigned DNs in registration order:

| Terminal | MAC | DN | Role |
|----------|-----|-----|------|
| 2 | `AABBCCDDEE01` | 1000 | Caller (console A) |
| 3 | `AABBCCDDEE02` | 1001 | Callee (console B) |
| 4 | `AABBCCDDEE03` | 1002 | Transfer / second-call target (console C) |

Each console (skip TFTP — sim already served config on register):

```powershell
python -m examples.run_console --server <LAB_IP> --mac AABBCCDDEE01 --model 7970 --skip_tftp
python -m examples.run_console --server <LAB_IP> --mac AABBCCDDEE02 --model 7970 --skip_tftp
python -m examples.run_console --server <LAB_IP> --mac AABBCCDDEE03 --model 7970 --skip_tftp
```

### Console keys (quick reference)

| Input | Action |
|-------|--------|
| `0-9`, `*`, `#` | Keypad |
| **Space** | Off-hook / on-hook toggle |
| **F1–F12** | Softkeys (Hold, EndCall, Transfer, …) |
| **h** | Hold / resume toggle |
| **e** | EndCall |
| **q** | Quit |
| Header | **Registered** vs **Reconnecting…** after admin Reset/Restart |

### Basic call

1. On **A**: Space (off-hook) or **NewCall** softkey, dial `1001`, `#` if needed.
2. On **B**: **Answer** when ringing.
3. Header shows **Connected**; **F1: Hold**, **F2: EndCall**, etc.

---

## 3. Callee IVR with `run_macro` (transfer + barge-in)

Uses `examples/ivr.macro` — a **fourth** registration acts as the IVR auto-attendant (not the virtual `9999` DN).

**DN plan** (add a fourth client or use `--dn-start 1000` and register IVR before others if you want 1000):

| MAC | DN | Role |
|-----|-----|------|
| `AABBCCDDEE04` | 1003 | IVR callee (`run_macro`) |

Ensure `examples/ivr.macro` destination DNs match your lab (`SET service_dn=1001`, `SET support_dn=1002` for the table above).

```powershell
python -m examples.run_macro --server <LAB_IP> --mac AABBCCDDEE04 --model 7970 `
  --skip_tftp --macro-file examples/ivr.macro -vv
```

**Caller flow:**

1. **A** dials `1003` → macro auto-answers → main menu WAV.
2. Press **1** (service) or **2** (support) → prompt → **blind transfer** to 1001 / 1002.
3. **B** or **C** answers; **A** drops off after transfer completes.

**Barge-in:** during `PLAY`, any DTMF stops the prompt (shared with sim virtual IVR).

**Extension dial:** press **3**, enter 4 digits, `#` — transfers to that DN.

---

## 4. Virtual IVR (`--ivr-dn 9999`)

Separate from the macro IVR — built into the simulator, script at `simulator/ivr_assets/ivr.macro`:

1. Any registered phone dials `9999`.
2. Sim auto-answers; menu: **1** loopback, **2** tone test, **9** / `#` hang up.

Useful for RTP / loopback experiments without running `run_macro`.

---

## 5. Admin Reset / Restart (console auto-reconnect)

1. Open `http://<LAB_IP>:8090/`.
2. Check one or more phones → **Restart** (soft, re-register) or **Reset** (hard, longer).
3. Consoles show **Reconnecting…** then **Registered**; softkeys return without restarting `run_console`.

Same behavior as CUCM **Restart** / **Reset** Skinny messages (`0x0030` / `0x0029`).

---

## 6. Second call while on hold

On **A** with an active call to **B**:

1. **Hold** (softkey or **h**).
2. **NewCall** → dial **C** (`1002`) → **C** answers.
3. **EndCall** on the active (second) call — focus returns to held call on **B**.
4. **Resume** — back with **B**.

Requires multi-call ref tracking (sim + client); covered by `tests/test_simulator_calls.py::test_second_call_while_on_hold`.

---

## 7. Blind transfer (sim)

On **A** connected to **B**:

1. **Transfer** → dial **C** → **Transfer** again (or `#` on sim).
2. **A** goes on-hook; **C** rings; **C** answers → connected to **B**.

---

## 8. Verify with tests

```powershell
# Simulator call flows (no audio device needed)
pytest tests/test_simulator_calls.py tests/test_console_reregister.py `
  tests/test_call_lifecycle.py tests/test_call_management.py -v

# Full unit suite (exclude live CUCM)
pytest -m "not integration" -v
```

---

## 9. Troubleshooting

| Symptom | Check |
|---------|--------|
| Phone never registers | `--advertise-host`, firewall on TCP **2000**, TFTP port in XML |
| Wrong DN on transfer | `SET service_dn` / `support_dn` in `examples/ivr.macro` vs `show config` / sim log |
| Console stuck **Reconnecting…** | Sim running? Admin Restart sent? Client log for RegisterReject |
| No IVR audio | Macro needs RTP TX for `PLAY`; use `-vv` on `run_macro` |
| Port 69 / TFTP fails | Use `--tftp-port 6969` + relay, or run sim elevated |
| Unregister hangs on exit | Fixed in recent builds — `client.stop()` ends calls first; update and retry |

---

## Related files

| Path | Purpose |
|------|---------|
| `examples/run_simulator.py` | Simulator entry |
| `examples/run_console.py` | Curses softphone |
| `examples/run_macro.py` | Macro / IVR callee |
| `examples/ivr.macro` | Callee auto-attendant script |
| `simulator/admin_http.py` | Admin web UI |
| `utils/call_management.py` | Call state / multi-call tracking |
