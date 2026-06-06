# pyskinny — project TODO

Living backlog for lab work, protocol gaps, tests, and polish.  
**Last reviewed:** 2026-06-03 (TODO user checklist + `docs/lab-cm3x.md`).

For how to run things today, see [README.md](README.md) and the lab docs linked there. Always git add / commit when making any changes!

---

## Your checklist (lab — you only)

One list, priority order. Check off here when done; note the date or filename inline.

- [ ] **Hold pcap (cm31 or cm33)** — During a live call: SoftKey **Hold**, wait ~3 s, **Resume**, hang up. Filter `host <CM_IP> and tcp port 2000`. Unblocks `test_hold_and_resume` skip (prompt shows `Hold` but `call_state` stays Connected). Suggested name: `cm31_hold.pcapng` / `cm33_hold.pcapng`.
- [ ] **Fresh register captures (cm31 + cm33)** — Re-grab registration with **current pyskinny** (sends **FeatureStatReq `0x0034`**). Existing `cm31_register.pcapng` / `cm33_register.pcapng` predate that change (phone sent `0x002D` on the wire; no **FeatureStatRes `0x011F`** in fixtures). Capture while `run_console` registers, through **TimeDateRes**, then run `python -m utils.extract_cucm_capture_fixtures` to refresh `cm31_reg` / `cm33_reg` groups. See [docs/lab-cm3x.md](docs/lab-cm3x.md#registration-captures).
- [ ] **Conference (T3 + P7)** — Manual: CLI `phone conference <dn>` or macro on a lab CM. Report which lab works. Optional pcap: `cm41_conference.pcapng` (A–B connected → Confrn → dial C → answer → Confrn). Unblocks live `test_conference`.
- [ ] **Full integration sweep (T1 + F3)** — `pytest tests/test_integration_live.py -m integration -v --no-audio` (no consoles on same MACs). Save output to `logs/integration_all_labs.log`; note pass/fail/skip per lab.
- [ ] **Console hangup (T4)** — On a live call: **F1/e** vs **Space** vs **q** on cm2 and cm41. Which clears the CM call cleanly?
- [ ] **Multi-call (T5)** — Connect → **h** hold → second call to third DN → swap with ↑↓ → hang up each. Any stale call refs in the console log?
- [ ] **cm41/cm43 consulted transfer** — Only if you care about 79xx consult (cm2/cm31/cm33 already pass). Debug why consult leg stalls, or capture softkey consult xfer on cm41/cm43 (`consult_xfer.pcap` was CM2 Stimulus only).
- [ ] **Park (P8)** — Configure call park on a lab CM, then park + retrieve; capture `cm*_park.pcapng`.
- [ ] **CM2 two-way audio (P9, optional)** — Call with `--rtp-tone` or `--rtp-mic`; note if you heard remote party. `cm2_media.pcapng`.
- [ ] **Inbound ring / SetRinger (P10, optional)** — Ring-in to 79xx with lamps + ringer messages for sim ring path work.
- [ ] **RTP note (F4, optional)** — UDP pcap for same call as P3, or confirm “hear remote OK with default RX monitor”.
- [ ] **`git push`** — When `main` is ahead of origin after a lab session.
- [ ] **Integration workflow (optional)** — Run GitHub **Integration (lab CallManager)** on self-hosted runner after T1 passes locally.

**Already done (no action):** T6/T7/T8 diagnostics; P3/P4 call pcaps + fixes; P6 consult regression; register fixtures from older pcaps; A1 endpoints; A5 cm43 reachability; A4 licenses.

Drop new pcaps in repo root or `tools/` (gitignored by default).

---

## Current status (what’s in good shape)

| Area | Status |
|------|--------|
| **Live integration** (cm2, cm31, cm33, cm41, cm43) | Register, connect/hangup, blind transfer, consulted transfer green on cm2/cm31/cm33; **hold skips cm31/cm33**; **consult skips cm41/cm43** |
| **CM2 button phones** | Stimulus hold (3), transfer (4), SetLamp tracking, synthetic `cm2-N` refs |
| **Softkey phones** (79xx) | SoftKey hold/resume/transfer, template diagnostics |
| **CM3.x** (cm31, cm33) | FeatureStat, OpenReceiveChannel parse, register capture fixtures — see [docs/lab-cm3x.md](docs/lab-cm3x.md) |
| **Simulator** | Calls, IVR macro, blind/consult transfer, conference, admin UI, capture regressions |
| **Console** | `h` hold, `t` transfer, default RX monitor / silent TX, `--rtp-mic` for real mic |
| **CI** | Unit tests on push (Py 3.11/3.12); integration workflow is manual `workflow_dispatch` on self-hosted runner |

---

## Quick reference — CM labs

| Lab | IP | Model | Identity | Notes |
|-----|-----|-------|----------|--------|
| cm2 | 10.0.0.11 | Virtual30SPplus | pyskinny01–03 | [lab-cm2-buttons.md](docs/lab-cm2-buttons.md) |
| cm31 | 10.0.0.181 | **7960** | SEP + MAC 444–446 | CM 3.1 — [lab-cm3x.md](docs/lab-cm3x.md) |
| cm33 | 10.0.0.182 | **7970** | SEP + MAC 444–446 | CM 3.3 — same family as cm31 |
| cm41 | 10.0.0.180 | 7970 | SEP + MAC 444–446 | CM 4.1 |
| cm43 | 100.69.0.100 | 7970 | SEP + MAC 444–446 | CM 4.3 |

```powershell
pytest tests/test_integration_live.py -m "integration and cm31" -v --no-audio
python -m utils.dump_softkeys --server 10.0.0.181 --mac 222233334444 --model 7960
python -m utils.dump_buttons --server 10.0.0.11 --device-name pyskinny01 --model Virtual30SPplus
```

---

## Agent backlog (repo / code — not blocked on you)

### Must — correctness

- [ ] **cm31/cm33 hold integration** — blocked on **hold pcap** in your checklist.
- [ ] **cm41/cm43 consult integration** — blocked on your checklist.
- [x] PortAudio device -1 / silent default TX
- [x] Extension DN in console header (LineStatRes)
- [x] On-hook stale `Call: ACTIVE`
- [x] CloseReceiveChannel 8-byte payload (P3)
- [x] Ring-in Answer softkeys (P4)
- [x] FeatureStatReq / FeatureStatRes registration
- [x] Consult xfer pcap regression (`test_consult_xfer_capture.py`)
- [x] CM3.x register fixtures (`cm31_reg` / `cm33_reg` in `cucm_frames.json`)

**Protocol gaps (code):**

| ID | Name | Status |
|----|------|--------|
| ~~0x011F~~ | FeatureStatRes | Done |
| ~~0x0034~~ | FeatureStatReq decorator bug | Done |
| 0x0105 | OpenReceiveChannel | Parse done; optional `compression_type` → RTP RX |
| 0x0000 | KeepAliveReq | Add recv → reply KeepAliveAck |
| 0x0130 | CallSelectStatRes | Logs only; state update needs multi-call pcap (T5) |

### Should — tests, docs, hygiene

- [x] `docs/lab-softkey-hold.md` — cm2 Stimulus 3 + cm31/cm33 hold note
- [x] `docs/lab-cm3x.md` — CM3.x quirks
- [ ] Periodic full-lab run script or README one-liner
- [ ] Unhandled message log dedup (once per ID per session)
- [ ] Fail vs skip policy for integration tests
- [ ] README roadmap sync
- [ ] Conference console shortcut (`c`) after T3 validates flow
- [ ] CM31 profile in simulator (optional)

### Could — later

- SIP phone support; G.729 TX; park/pickup (P8); MOH; Windows TTS; Wireshark dissector alignment; Python 3.14 in CI matrix; self-hosted runner docs.

---

## Capture & log reference

| ID | Item | Status |
|----|------|--------|
| P1/P2 | cm31/cm33 register (older) | Received — fixtures extracted; **re-capture with current pyskinny** in your checklist |
| P3/P4 | cm31/cm33 connect call | Received + fixed |
| P5 | FeatureStat clip | Superseded by fresh register re-capture |
| P6 | CM2 consult xfer | Done → `test_consult_xfer_capture.py` |
| P7 | Conference | Open — your checklist |
| P8–P10 | Park, CM2 media, SetRinger | Open / optional — your checklist |
| T6–T8 | Register logs, dump_softkeys/buttons | Done |
| F1–F2 | FeatureStat logs, consult pcap | Done |
| F3–F4 | Integration sweep log, RTP | Open — your checklist |

**Fixtures in repo:** `tests/fixtures/cucm_frames.json` (regen: `python -m utils.extract_cucm_capture_fixtures`).  
**Local/gitignored pcaps:** `blind_xfer.pcap`, `consult_xfer.pcap`, `vphone_hold_unhold.pcap`, `cm31_register.pcapng`, `cm33_register.pcapng`, etc.

---

## How to update this file

- Check off **Your checklist** when you complete lab work.
- Move agent items to done when merged.
- Add unknown `Unhandled message ID: 0x....` from `-vvv` logs to the protocol table.
- After a full lab sweep, bump **Last reviewed** and note T1 results at the top of your checklist.
