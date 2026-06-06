# pyskinny — project TODO

Living backlog for lab work, protocol gaps, tests, and polish.  
**Last reviewed:** 2026-06-03 (after cm2 hold/transfer/consult + codec noise fixes).

For how to run things today, see [README.md](README.md) and the lab docs linked there.

---

## Current status (what’s in good shape)

| Area | Status |
|------|--------|
| **Live integration** (cm2, cm31, cm33, cm41, cm43) | Register, connect/hangup, hold/resume, blind transfer, consulted transfer |
| **CM2 button phones** | Stimulus hold (3), transfer (4), SetLamp tracking, synthetic `cm2-N` refs |
| **Softkey phones** (79xx) | SoftKey hold/resume/transfer, template diagnostics |
| **Simulator** | Calls, IVR macro, blind/consult transfer, conference, admin UI, capture regressions |
| **Console** | `h` hold, `t` transfer, default RX monitor / silent TX, `--rtp-mic` for real mic |
| **CI** | Unit tests on push (Py 3.11/3.12); integration workflow is manual `workflow_dispatch` on self-hosted runner |

---

## Must — correctness / lab blockers

- [x] Fix sounddevice.PortAudioError: Error querying device -1 when running pyskinny with default options (such as python -m examples.run_console -vvvv --server 10.0.0.181 --device 222233334444 --model 7960). Should log error or warning and only send silence.

### Skinny messages still incomplete on the **client**

These show up as `Unhandled message ID` in logs (`dispatcher.py`) or are mis-wired.

| ID | Name | Notes |
|----|------|--------|
| **0x011F** | **FeatureStatRes** | **Likely what you remember for CM31/CM33.** Named in `utils/skinny_messages.py` and handled on the **simulator**, but the **pyskinny client has no recv handler**. Real phones send **FeatureStatReq (0x0034)** during registration; CM answers with **FeatureStatRes**. Registration often still completes (we mark registered on `TimeDateRes`), but logs may warn and behavior may differ from a real 7960/7970. |
| **0x0034** | FeatureStatReq vs OpenReceiveChannelAck | **Bug:** `send_open_receive_channel_ack()` in `messages/phone.py` is incorrectly decorated with `@register_handler(0x0034, ...)`. That ID is **FeatureStatReq** (phone→CM), not a CM→phone message. Actual ack wire id is **0x0022**. Remove the bogus decorator; optionally add client **send** of FeatureStatReq in the registration sequence. |
| **0x0105** | OpenReceiveChannel | **CM3.1 / CM3.3 fix (done):** shorter payloads than CM4.x broke strict `struct.unpack`; now uses `Buf` + `skinny_wire_call_ref()`. **Still open:** we parse the message but **do not store `compression_type`** for RTP RX — decoder auto-detects PT 0/8 from wire. Capture cm31/cm33 OpenReceiveChannel pcaps if we need explicit PT. |
| **0x0000** | KeepAliveReq | CM may send keepalive; client has **KeepAliveAck** handler for **0x0100** but not recv on **0x0000** (usually benign). |

### CM3.x–specific (cm31 = 7960, cm33 = 7970)

- [ ] **Add `FeatureStatRes` handler** — no-op or parse; suppress unhandled warnings during registration.
- [ ] **Send `FeatureStatReq (0x0034)`** after softkey/button stats (match `cm_cap.pcapng` registration order); confirm on cm31 + cm33.
- [ ] **Capture regression fixtures** for cm31/cm33 (today: `cm_cap.pcapng` / `cm_call_*.pcapng` are CM4.1-oriented; CM2 has `tools/cm2_register.pcapng`).
- [ ] **Document CM3.x quirks** — short `docs/lab-cm3x.md` or section in README (OpenReceiveChannel length, FeatureStat, 7960 vs 7970 model enum).

### Protocol / state

- [ ] **Remove `@register_handler(0x0034)` from `send_open_receive_channel_ack`** — it is a send helper, not an inbound handler.
- [ ] **`CallSelectStatRes (0x0130)`** — handler logs only; does not update call state (may matter for multi-call / transfer on some CM builds).
- [ ] **`OpenReceiveChannel` → RTP RX** — optionally apply `compression_type` from message instead of inferring PT from first packets.

---

## Should — tests, docs, lab hygiene

### Integration tests

- [ ] **Live conference test** — `client.conference()` works in sim; no `test_conference` in `test_integration_live.py` yet.
- [ ] **Periodic full-lab run** — script or CI note: `pytest tests/test_integration_live.py -m integration -v --no-audio` (all five labs; stop consoles first).
- [ ] **Consult transfer pcap regression** — `xfer.pcap` exists locally (gitignored); add `tests/test_consult_xfer_capture.py` like blind xfer.
- [ ] **Fail vs skip** — integration helpers use `pytest.skip` when CM doesn’t complete transfer/hold; consider hard `fail` for labs you expect green every run.

### Documentation drift

- [ ] **`docs/lab-softkey-hold.md`** — still says *“integration tests skip hold on cm2”*; cm2 now uses Stimulus 3 (update or cross-link `lab-cm2-buttons.md`).
- [ ] **README roadmap** — keep in sync with this file when closing items.
- [ ] **PowerShell env var note** — already in README; worth one line in `test_integration_live.py` docstring (done).

### Simulator / captures

- [ ] **CM31 profile in simulator** — optional distinct template payloads (today: `modern` vs `legacy7912` vs `cm2`; cm31 uses 7960 enum).
- [ ] **Ring path** — CUCM uses `SetRinger` + lamps; sim still leans on `StartTone`; capture-driven improvement if hardware ring matters.

### UX / console

- [ ] **EndCall (F1 / `e`) vs Space (on-hook)** — historically inconsistent on sim; verify on live CM after hangup fixes.
- [ ] **Multi-call UI** — console has up/down to select call ref; second call while held works in code but little guided testing on live CM.
- [ ] **Conference softkey / F-key** — no console shortcut (CLI `phone conference` exists).

### Code quality

- [ ] **Unhandled message policy** — log once per ID per session at WARNING, or aggregate at end of call, instead of per-packet spam.
- [ ] **`HookFlash (0x0008)`** — named, no handler; CM2 may use it on some builds (we use Stimulus 3 for hold).
- [ ] **Python 3.14** — you run 3.14 locally; CI is 3.11/3.12 — add 3.14 to classifiers/matrix when convenient.

---

## Could — features & improvements

### Telephony

- [ ] **SIP phone support** (README “Later”) — separate stack from SCCP.
- [ ] **G.729 / GSM / wideband encode-decode** — registry entries exist; TX is silence, RX limited to G.711 today.
- [ ] **Park, pickup, directed transfer** — not implemented; need captures + softkey/button mapping.
- [ ] **MOH / announce** — hold works; music/announce streams not modeled.

### IVR / audio lab

- [ ] **Windows TTS helper** — one-shot script using `System.Speech` → 8 kHz WAV for `PLAY` / `--rtp-wav` (discussed in chat; not in repo).
- [ ] **IVR prompt library** — checked-in `media/` samples + macro examples for sim `--ivr-dn`.
- [ ] **Two-way RTP on CM2** — default silent TX; confirm `--rtp-tone` / loopback on Virtual30 if needed for IVR.

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
| cm31 | 10.0.0.181 | **7960** | SEP + MAC 444–446 | CM3.x OpenReceiveChannel; FeatureStatRes TBD |
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

## Suggested next steps (priority order)

1. **FeatureStatRes + FeatureStatReq** — fixes the CM31/CM33 message gap you remembered; removes bogus `0x0034` handler.
2. **cm31/cm33 pcap fixtures** — one registration + one call capture each.
3. **Live conference integration test**.
4. **Consult xfer pcap regression** + doc touch-ups (`lab-softkey-hold.md`).

---

## Your action items — captures, tests, and lab work

Things only you can do in the lab. Each item points back to the backlog line(s) it unblocks.  
Drop pcaps in repo root or `tools/` (they are gitignored — share via path name or attach to a commit if you want them in-tree).

### Packet captures to grab

| # | Capture | How | Unblocks (TODO lines) |
|---|---------|-----|------------------------|
| P1 | **cm31 registration** — pyskinny register through `TimeDateRes` | `tshark -i <iface> -f "host 10.0.0.181 and tcp port 2000" -w cm31_register.pcapng` while `pyskinny-console` registers (MAC …444, model 7960) | L31, L38–L40, L141 |
| P2 | **cm33 registration** — same as P1 on **10.0.0.182** (7970) | `cm33_register.pcapng` | L31, L38–L40, L141 |
| P3 | **cm31 connect call** — A calls B, answer, 5 s connected, hang up | Filter CM IP + port 2000; include **OpenReceiveChannel (0x0105)** and **StartMediaTransmission** | L33, L47, L119 |
| P4 | **cm33 connect call** — same on cm33 | `cm33_call.pcapng` | L33, L47, L119 |
| P5 | **FeatureStat only** — if P1/P2 are huge, a short clip from register showing **0x0034** (phone→CM) and **0x011F** (CM→phone) is enough | Note frame numbers or Skinny message list from Wireshark | L31–L32, L38–L39 |
| P6 | **Consult transfer (softkey)** — you already have `xfer.pcap` locally; confirm it is **consult** (answer C before 2nd Transfer), not blind | Add to repo or tell us the filename if different from `blind_xfer.pcap` | L57, L144 |
| P7 | **Conference** — A connected to B → Confrn → dial C → answer → Confrn again (3-way) | `cm41_conference.pcapng` or any lab | L55, L75 |
| P8 | **Park** (optional) — if your CM has Call Park configured | Park + retrieve from another phone | L91 |
| P9 | **CM2 IVR / two-way audio** (optional) — call with `--rtp-tone` or `--rtp-mic` if you care about TX on Virtual30 | `cm2_media.pcapng` (+ note if you heard remote party) | L98 |
| P10 | **Ring / SetRinger** (optional) — inbound ring to 79xx; include lamps + ringer messages | Compare to sim `StartTone`-only path | L69 |

**Existing captures we already use:** `tools/cm2_register.pcapng`, `blind_xfer.pcap`, `vphone_hold_unhold.pcap`, `pgm_exit.pcap`, `cm_cap.pcapng` (CM4.1 register), `cm_call_from_pyskinny_to_7912.pcapng`.

---

### Tests for you to run and report back

Run with **no consoles** holding the same MAC/device names.

| # | Command / action | Report | Related (TODO lines) |
|---|----------------|--------|---------------------|
| T1 | Full integration sweep: `pytest tests/test_integration_live.py -m integration -v --no-audio` | Pass/fail/skip count **per lab** (cm2, cm31, cm33, cm41, cm43) | L14, L56–L57 |
| T2 | Single lab sanity after CM changes: `pytest … -m "integration and cm31"` (repeat for cm33) | Green or paste skip reason | L119–L127, L38–L40 |
| T3 | **Conference** manual: CLI `phone conference <dn>` or macro; then say if we should automate | Works? which lab? | L55, L75 |
| T4 | **Console hangup**: on a live call, try **F1/e** vs **Space** vs **q** | Which clears CM call cleanly on cm2 and cm41? | L73 |
| T5 | **Multi-call**: connect → **h** hold → place second call to third DN → swap with ↑↓ → hang up each | Any stale refs in console log pane? | L74 |
| T6 | Register with `-vvv` on **cm31** and **cm33**; search log for `Unhandled message ID` | List any **0x….** hex IDs not in our table (L29–L34) | L31, L79 |
| T7 | `python -m utils.dump_softkeys --server 10.0.0.181 --mac 222233334444 --model 7960` | Paste whether **Hold**, **Resume**, **Transfer**, **Confrn** appear | L16, L62 |
| T8 | After T6: same on cm2 with `dump_buttons` for pyskinny01 | Confirm button map still matches Virtual30 | L15, L134 |

---

### CM / device admin (one-time checks)

| # | Task | Related (TODO lines) |
|---|------|----------------------|
| A1 | Confirm **three endpoints** per lab (…444, …445, …446) exist and DNs are routable for transfer tests | L14, L56 |
| A2 | **Hold/MOH** enabled on lab lines (cm31–cm43 softkey; cm2 line MOH if hold test ever skips) | L38, L62 |
| A3 | **Softkey template** on 79xx: standard 7960/7970 template with Hold/Resume/Transfer | L16, L62 |
| A4 | Note when **license exhaustion** happens (50 devices) — which CM, after how many clients | L109 |
| A5 | cm43: confirm **100.69.0.100** reachable from your test PC (VPN/firewall) | L122 |

---

### Files / logs to hand off

| # | What | Related (TODO lines) |
|---|------|----------------------|
| F1 | Console log snippet (`-vvv`) showing **0x011F** or any **Unhandled** during cm31/cm33 **register** | L31, L38, L79 |
| F2 | `xfer.pcap` (consult transfer) — confirm consult vs blind; we can add regression bytes | L57, L144 |
| F3 | Output of **T1** saved to `logs/integration_all_labs.log` after a full sweep | L56 |
| F4 | If audio matters: one **RTP** pcap (UDP) for same call as P3, or note “hear remote OK with default RX monitor” | L33, L47, L98 |

---

### Ops (when you have time)

| # | Task | Related (TODO lines) |
|---|------|----------------------|
| O1 | `git push` after lab sessions if `main` is ahead of origin | L108 |
| O2 | Optional: run GitHub **Integration (lab CallManager)** workflow on self-hosted runner after T1 passes locally | L19, L110 |

---

### Suggested order for you

1. **T6 + F1** on cm31/cm33 (quick — confirms FeatureStat / unhandled IDs) → L31, L38–L39  
2. **P1 + P2** (or **P5** minimal) → L40, L141  
3. **T1** full sweep → L56  
4. **P6 / F2** consult `xfer.pcap` → L57, L144  
5. **T3 + P7** if you want conference in integration tests → L55, L75  

---

## How to update this file

- Move items to done by striking through or deleting when merged.
- Add new rows to the message table when you see `Unhandled message ID: 0x....` in console logs (`-vvv`).
- After a full lab sweep, note date + pass/fail counts at the top.
- Check off **Your action items** (P/T/A/F/O) when done and note the date inline.
