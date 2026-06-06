# pyskinny — project TODO

Living backlog for lab work, protocol gaps, tests, and polish.  
**Last reviewed:** 2026-06-03 (consult xfer regression; TODO blocked/unblocked pass).

For how to run things today, see [README.md](README.md) and the lab docs linked there. Always git add / commit when making any changes!

---

## Current status (what’s in good shape)

| Area | Status |
|------|--------|
| **Live integration** (cm2, cm31, cm33, cm41, cm43) | Register, connect/hangup, blind transfer, consulted transfer green on cm2/cm31/cm33; **hold skips cm31/cm33**; **consult skips cm41/cm43** |
| **CM2 button phones** | Stimulus hold (3), transfer (4), SetLamp tracking, synthetic `cm2-N` refs |
| **Softkey phones** (79xx) | SoftKey hold/resume/transfer, template diagnostics |
| **Simulator** | Calls, IVR macro, blind/consult transfer, conference, admin UI, capture regressions |
| **Console** | `h` hold, `t` transfer, default RX monitor / silent TX, `--rtp-mic` for real mic |
| **CI** | Unit tests on push (Py 3.11/3.12); integration workflow is manual `workflow_dispatch` on self-hosted runner |

---

## Must — correctness / lab blockers

- [x] Fix sounddevice.PortAudioError: Error querying device -1 when running pyskinny with default options (such as python -m examples.run_console -vvvv --server 10.0.0.181 --device 222233334444 --model 7960). Should log error or warning and only send silence.
- [x] Tested on CM31, could affect other versions. I don't see the extension number printed on the screen. This should be shown somewhere since it would normally show up on the actual screen. This would obviously not apply to like first gen phones that didn't show this on the screen.
- [x] Tested on CM31, could affect other versions. With run_console, using softkey to get a new line, and then pressing space (hook), the call appears to hang up, but still shows "Call: ACTIVE"
- [x] **P3 / cm31 call teardown:** `CloseReceiveChannel (0x0106)` with **8-byte** payload crashes parse (`struct.unpack` expects 12 bytes). Log/traceback in `P3.debug.txt`; wire in `P3.pcapng`.
- [x] **P4 / cm33 inbound ring:** On **RingIn**, CM sends `SelectSoftKeys` but `run_console` still shows only `EndCall` (no **Answer**). Template has Answer (T7). See `P4.debug.txt` / `cm33_call.pcapng`.
- [ ] **(blocked — you)** **T1/T2 cm31+cm33 hold:** `test_hold_and_resume` skips — SoftKey Hold sent, prompt becomes `Hold`, but `call_state` stays **Connected** (last update `SetLamp`). Need **hold pcap** (during Hold/Resume) or SetLamp `lamp_mode` trace on cm31/cm33. Ref: `T1.debug.txt`, `T2.debug.txt`.
- [ ] **(blocked — you)** **T1 cm41+cm43 consulted transfer:** `test_consulted_transfer` skips — consult leg does not complete on SEP222233334444. cm31/cm33/cm2 pass. Need live debug or **79xx consult xfer pcap** on cm41/cm43 (P6 was CM2 Stimulus only). Ref: `T1.debug.txt`.

### Skinny messages still incomplete on the **client**

These show up as `Unhandled message ID` in logs (`dispatcher.py`) or are mis-wired.

| ID | Name | Notes |
|----|------|--------|
| ~~**0x011F**~~ | ~~FeatureStatRes~~ | **Done** — recv handler in `messages/capabilities.py`; client sends **FeatureStatReq (0x0034)** in registration. |
| ~~**0x0034**~~ | ~~FeatureStatReq decorator bug~~ | **Done** — bogus `@register_handler(0x0034)` removed from `send_open_receive_channel_ack()`. |
| **0x0105** | OpenReceiveChannel | **Parse fix (done)** for CM3.x short payloads. **Open:** do not store `compression_type` for RTP RX — decoder auto-detects PT 0/8. **(blocked — you, optional)** explicit PT only if we need it beyond auto-detect; `P3.pcapng` exists. |
| **0x0000** | KeepAliveReq | CM may send keepalive; client has **KeepAliveAck** recv (**0x0100**) but no recv on **0x0000** (usually benign). **Unblocked** — add recv → reply with KeepAliveAck. |

### CM3.x–specific (cm31 = 7960, cm33 = 7970)

- [x] **Add `FeatureStatRes` handler** — no-op or parse; suppress unhandled warnings during registration.
- [x] **Send `FeatureStatReq (0x0034)`** after softkey/button stats (match `cm_cap.pcapng` registration order); confirm on cm31 + cm33.
- [ ] **Capture regression fixtures** for cm31/cm33 — **P1/P2 register pcaps received** (`cm31_register.pcapng`, `cm33_register.pcapng` at repo root); still need **call/hold** clips for full fixture set. **Unblocked:** extract register frames into `tests/fixtures/` like `cm2_register`.
- [ ] **Document CM3.x quirks** — short `docs/lab-cm3x.md` or section in README (OpenReceiveChannel length, FeatureStat, 7960 vs 7970 model enum). **Unblocked** (can draft from existing pcaps + T6 logs).

### Protocol / state

- [x] **Remove `@register_handler(0x0034)` from `send_open_receive_channel_ack`** — it is a send helper, not an inbound handler.
- [ ] **`CallSelectStatRes (0x0130)`** — handler logs only; does not update call state. **(blocked — you)** needs multi-call or transfer pcap showing state impact (T5 may surface this).
- [ ] **`OpenReceiveChannel` → RTP RX** — optionally apply `compression_type` from message instead of inferring PT from first packets. **(blocked — you, optional)** unless RX decode misbehaves on a specific lab call.

---

## Should — tests, docs, lab hygiene

### Integration tests

- [ ] **(blocked — you)** **Live conference test** — `client.conference()` works in sim; no `test_conference` in `test_integration_live.py` yet. Needs **T3** manual run + **P7** conference pcap to automate confidently.
- [ ] **Periodic full-lab run** — script or CI note: `pytest tests/test_integration_live.py -m integration -v --no-audio` (all five labs; stop consoles first). **Unblocked** (docs/script only).
- [x] **Consult transfer pcap regression** — `tests/test_consult_xfer_capture.py` (wire hex from local `consult_xfer.pcap`).
- [ ] **Fail vs skip** — integration helpers use `pytest.skip` when CM doesn’t complete transfer/hold; consider hard `fail` for labs you expect green every run.

### Documentation drift

- [ ] **`docs/lab-softkey-hold.md`** — still says *“integration tests skip hold on cm2”*; cm2 now uses Stimulus 3 (update or cross-link `lab-cm2-buttons.md`). **Unblocked.**
- [ ] **README roadmap** — keep in sync with this file when closing items.
- [ ] **PowerShell env var note** — already in README; worth one line in `test_integration_live.py` docstring (done).

### Simulator / captures

- [ ] **CM31 profile in simulator** — optional distinct template payloads (today: `modern` vs `legacy7912` vs `cm2`; cm31 uses 7960 enum).
- [ ] **(blocked — you)** **Ring path** — CUCM uses `SetRinger` + lamps; sim still leans on `StartTone`; needs **P10** inbound-ring pcap if hardware ring matters.

### UX / console

- [ ] **(blocked — you)** **EndCall (F1 / `e`) vs Space (on-hook)** — verify on live CM after hangup fixes (**T4**).
- [ ] **(blocked — you)** **Multi-call UI** — second call while held works in code; needs guided live test (**T5**).
- [ ] **Conference softkey / F-key** — no console shortcut (CLI `phone conference` exists). **Unblocked** once conference flow is validated (**T3**); can add `c` binding without pcap.

### Code quality

- [ ] **Unhandled message policy** — log once per ID per session at WARNING, or aggregate at end of call, instead of per-packet spam. **Unblocked.**
- [ ] **`HookFlash (0x0008)`** — named, no handler; CM2 may use it on some builds (we use Stimulus 3 for hold).
- [ ] **Python 3.14** — you run 3.14 locally; CI is 3.11/3.12 — add 3.14 to classifiers/matrix when convenient.

---

## Could — features & improvements

### Telephony

- [ ] **SIP phone support** (README “Later”) — separate stack from SCCP.
- [ ] **G.729 / GSM / wideband encode-decode** — registry entries exist; TX is silence, RX limited to G.711 today.
- [ ] **(blocked — you)** **Park, pickup, directed transfer** — not implemented; **P8** park not configured on lab CMs yet.
- [ ] **MOH / announce** — hold works; music/announce streams not modeled.

### IVR / audio lab

- [ ] **Windows TTS helper** — one-shot script using `System.Speech` → 8 kHz WAV for `PLAY` / `--rtp-wav` (discussed in chat; not in repo).
- [ ] **IVR prompt library** — checked-in `media/` samples + macro examples for sim `--ivr-dn`.
- [ ] **(blocked — you)** **Two-way RTP on CM2** — default silent TX; confirm `--rtp-tone` / loopback on Virtual30 (**P9**).

### Tooling

- [ ] **`tools/probe_cm3_openrx.py`** — was written during cm31 debug; not in tree — restore or fold into `utils/dump_*` if still useful.
- [ ] **Wireshark plugin / dissector alignment** — compare unknown IDs against Skinny dissector for CM 3.1 vs 4.1.
- [ ] **AXL / AST / phone CGI** — mature; could use more examples in README for your lab DNs.

### Packaging / ops

- [ ] **Push `main`** after lab sessions (branch often ahead of origin).
- [ ] **Self-hosted integration runner** — document setup, MAC/device exclusivity, license exhaustion (50-device limit you hit).
- [ ] **Optional scheduled integration** — weekly `workflow_dispatch` or cron on lab runner.

---

## Quick reference — your CM labs

| Lab | IP | Model | Identity | Notes |
|-----|-----|-------|----------|--------|
| cm2 | 10.0.0.11 | Virtual30SPplus | pyskinny01–03 | Button template, Stimulus hold/xfer |
| cm31 | 10.0.0.181 | **7960** | SEP + MAC 444–446 | CM3.x OpenReceiveChannel; FeatureStat done; hold test skips |
| cm33 | 10.0.0.182 | 7970 | SEP + MAC 444–446 | Same CM3.x family as cm31 |
| cm41 | 10.0.0.180 | 7970 | SEP + MAC 444–446 | Primary dev lab historically |
| cm43 | 100.69.0.100 | 7970 | SEP + MAC 444–446 | CM 4.3 |

**Single-lab pytest:**

```powershell
pytest tests/test_integration_live.py -m "integration and cm31" -v --no-audio
```

**Diagnostics:**

```powershell
python -m utils.dump_softkeys --config    # 79xx
python -m utils.dump_buttons --config   # CM2
```

---

## Suggested next steps

### Unblocked — agent / repo work (no new pcaps required)

1. **`docs/lab-softkey-hold.md`** — fix outdated cm2 “skip hold” line; cross-link `lab-cm2-buttons.md`.
2. **cm31/cm33 register fixtures** — extract wire hex from `cm31_register.pcapng` / `cm33_register.pcapng` into `tests/fixtures/`.
3. **`docs/lab-cm3x.md`** — short CM3.x quirks doc (FeatureStat, OpenReceiveChannel, 7960 vs 7970).
4. **KeepAliveReq (0x0000) recv** — reply with KeepAliveAck (benign protocol hygiene).
5. **Unhandled message log dedup** — once per ID per session.
6. **Periodic full-lab run** — one-liner in README or small script under `tools/`.

### Blocked — waiting on you (lab artifacts or manual runs)

| Item | What we need |
|------|----------------|
| cm31/cm33 **hold** fix | Hold pcap on cm31/cm33, or SetLamp trace during Hold (**T1/T2**) |
| cm41/cm43 **consult** integration | Why consult leg stalls on 79xx; optional cm41 consult pcap |
| **Conference** integration test | **T3** does it work? + **P7** 3-way pcap |
| **Park / pickup** | **P8** — configure call park on a lab CM first |
| **CM2 two-way audio** | **P9** media pcap + “heard remote?” note |
| **SetRinger / ring path** | **P10** optional inbound-ring pcap |
| **Multi-call / hangup UX** | **T4**, **T5** manual console reports |
| **Full integration sweep log** | **T1** → save **F3** `logs/integration_all_labs.log` |
| **RTP decode edge case** | **F4** only if G.711 auto-detect fails on a real call |

---

## Your action items — captures, tests, and lab work

Things only you can do in the lab. Each item points back to the backlog line(s) it unblocks.  
Drop pcaps in repo root or `tools/` (they are gitignored — share via path name or attach to a commit if you want them in-tree).

### Packet captures to grab

| # | Capture | How | Unblocks (TODO lines) | Ref File(s) / Notes |
|---|---------|-----|------------------------|------------------------------------------|
| P1 | **cm31 registration** | register through `TimeDateRes` | L48 | **Received** — `cm31_register.pcapng` (repo root). Fixtures not extracted yet. |
| P2 | **cm33 registration** | same on **10.0.0.182** (7970) | L48 | **Received** — `cm33_register.pcapng` (repo root). |
| P3 | **cm31 connect call** | OpenReceiveChannel + StartMedia | L41 | **Received + fixed** — `P3.pcapng`, `P3.debug.txt`; CloseReceiveChannel parse fixed. |
| P4 | **cm33 connect call** | inbound ring + answer | L29 | **Received + fixed** — `cm33_call.pcapng`, `P4.debug.txt`; ring-in Answer softkeys fixed. |
| P5 | **FeatureStat only** | 0x0034 + 0x011F clip | — | **Covered** by P1/P2 + FeatureStat code done. |
| P6 | **Consult transfer (CM2)** | answer C before 2nd Transfer | L65 | **Done** — `consult_xfer.pcap` → `tests/test_consult_xfer_capture.py`. |
| P7 | **Conference** | 3-way Confrn flow | L63 | **(blocked)** — need capture + **T3** |
| P8 | **Park** | park + retrieve | L99 | **(blocked)** — park not configured on lab CMs |
| P9 | **CM2 two-way audio** | `--rtp-tone` / `--rtp-mic` | L106 | **(blocked)** — planned |
| P10 | **Ring / SetRinger** (optional) | inbound ring lamps + ringer | L77 | **(blocked)** — optional |

**Existing captures we already use:** `tools/cm2_register.pcapng`, `blind_xfer.pcap`, `consult_xfer.pcap` (local), `vphone_hold_unhold.pcap`, `pgm_exit.pcap`, `cm_cap.pcapng` (CM4.1 register), `cm_call_from_pyskinny_to_7912.pcapng`.

---

### Tests for you to run and report back

Run with **no consoles** holding the same MAC/device names.

| # | Command / action | Report | Related (TODO lines) | Ref File(s) / Notes |
|---|----------------|--------|---------------------|------------------------------------------|
| T1 | Full integration sweep: `pytest tests/test_integration_live.py -m integration -v --no-audio` | Pass/fail/skip count **per lab** (cm2, cm31, cm33, cm41, cm43) | L14, L56–L57 | T1.debug.txt |
| T2 | Single lab sanity after CM changes: `pytest … -m "integration and cm31"` (repeat for cm33) | Green or paste skip reason | L119–L127, L38–L40 | T2.debug.txt |
| T3 | **Conference** manual: CLI `phone conference <dn>` or macro; then say if we should automate | Works? which lab? | L55, L75 | |
| T4 | **Console hangup**: on a live call, try **F1/e** vs **Space** vs **q** | Which clears CM call cleanly on cm2 and cm41? | L73 | |
| T5 | **Multi-call**: connect → **h** hold → place second call to third DN → swap with ↑↓ → hang up each | Any stale refs in console log pane? | L74 | |
| T6 | Register with `-vvv` on **cm31** and **cm33**; search log for `Unhandled message ID` | List any **0x….** hex IDs not in our table | L31, L87 | **Done** — `T6.CM31.debug.txt`, `T6.CM33.debug.txt` (no Unhandled) |
| T7 | `dump_softkeys` on cm31 | Hold/Resume/Transfer/Confrn in template | L16 | **Done** — `T7.debug.txt` |
| T8 | `dump_buttons` on cm2 | Virtual30 button map | L15 | **Done** — `T8.debug.txt` |
| T3 | **Conference** manual | Works? which lab? | L63 | **(blocked — you)** |
| T4 | **Console hangup** F1/e vs Space vs q | Which clears CM cleanly? | L81 | **(blocked — you)** |
| T5 | **Multi-call** hold → 2nd call → swap | Stale refs in log? | L82 | **(blocked — you)** |

---

### CM / device admin (one-time checks)

| # | Task | Related (TODO lines) | Ref File(s) / Notes |
|---|------|----------------------|------------------------------------------|
| A1 | Confirm **three endpoints** per lab (…444, …445, …446) exist and DNs are routable for transfer tests | L14, L56 | Checked all and confirmed. |
| A2 | **Hold/MOH** enabled on lab lines (cm31–cm43 softkey; cm2 line MOH if hold test ever skips) | L38, L62 | |
| A3 | **Softkey template** on 79xx: standard 7960/7970 template with Hold/Resume/Transfer | L16, L62 | |
| A4 | Note when **license exhaustion** happens (50 devices) — which CM, after how many clients | L109 | Added another 1000 licenses, so this shouldn't be a common problem now |
| A5 | cm43: confirm **100.69.0.100** reachable from your test PC (VPN/firewall) | L122 | Confirmed it's reachable from here |

---

### Files / logs to hand off

| # | What | Related (TODO lines) |
|---|------|----------------------|
| F1 | cm31/cm33 register log with FeatureStat / Unhandled | L46–L47 | **Done** — T6 logs clean |
| F2 | `consult_xfer.pcap` → regression test | L65 | **Done** — `test_consult_xfer_capture.py` |
| F3 | **T1** full sweep log | L64 | **(blocked — you)** |
| F4 | RTP pcap or “hear remote OK” note | L41, L55, L106 | **(blocked — you, optional)** |

---

### Ops (when you have time)

| # | Task | Related (TODO lines) |
|---|------|----------------------|
| O1 | `git push` after lab sessions if `main` is ahead of origin | L108 |
| O2 | Optional: run GitHub **Integration (lab CallManager)** workflow on self-hosted runner after T1 passes locally | L19, L110 |

---

### Suggested order for you (blocked items only)

1. **Hold pcap** on cm31 or cm33 (during Hold + Resume) — unblocks hold integration skip.  
2. **T3 + P7** — conference manual test + pcap if you want `test_conference` in integration.  
3. **T1 + F3** — full five-lab sweep log after next CM session.  
4. **T4 / T5** — console hangup and multi-call UX when you have two calls handy.  
5. **cm41/cm43 consult debug** — only if you care about consult on 79xx (cm2/cm31/cm33 already pass).  

---

## How to update this file

- Move items to done by striking through or deleting when merged.
- Add new rows to the message table when you see `Unhandled message ID: 0x....` in console logs (`-vvv`).
- After a full lab sweep, note date + pass/fail counts at the top.
- Check off **Your action items** (P/T/A/F/O) when done and note the date inline.
