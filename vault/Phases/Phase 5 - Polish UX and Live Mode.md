---
title: Phase 5 - Polish UX and Live Mode
type: phase
phase: 5
status: done
tags: [phase, polish, restyle, responsive, live-mode]
updated: 2026-06-19
---

# Phase 5 — Polish, UX & Live Mode ✅

> Restyle + responsive + UX + model calibration **and live mode** are all done.
> Live runs on the host with a paid `OPENF1_TOKEN`; with no token the app stays
> strictly replay-only. Back to [[Home]].

## ✅ Done — premium F1 restyle
F1 racing-red accent on a **carbon** dark theme (hero) + **paddock-white** light
theme; Archivo + JetBrains Mono via Google Fonts; refined shadows, focus ring,
carbon-weave backdrop, red "timing-tower" tick on the status bar. Full details and
tokens in [[Design System]].

## ✅ Done — responsive (tablet + mobile)
Shell grid adapts; leaderboard drops to a **compact 6-col grid ≤1100px** and
becomes a **slide-in drawer ≤860px** (☰ toggle + tap-out backdrop, auto-closes on
driver select); Car Detail docks as a **bottom sheet ≤540px**; status bar
compacts/wraps; 3D overlay shrinks to icon-only. See [[Design System]].

## ✅ Done — UX additions
- **Two-dropdown race filter** — Year + Grand Prix (cascading), parsed client-side
  in `StatusBar.tsx` (`parseSession`/`RaceFilter`); no schema change.
- **Flag-change toast** — `FlagToast.tsx` (in `App.tsx`) replaces the always-on
  flag chip; fires only on flag transitions, auto-dismisses.
- **Car Detail "Car" tab** — `CarSchematic` in `CarPanel.tsx`: F1-TV-style top-down
  schematic, **real data only** (speed/gear/throttle/brake/DRS LIVE, tyre set LIVE,
  tyre-life AI, fuel EST). **No tyre/brake temps or ERS** — not in the feed (and
  rpm isn't either, so no shift lights). Honest-by-design per [[About Me]].

## ✅ Done — model calibration (full story in [[Calibration Log]])
- **Model B** anchor + σ: mean MAE 2.96 → ~1.86 (≈ persistence), up from clearly trailing.
- **Model C** SC hazard: per-circuit empirical-Bayes shrinkage + per-lap fit +
  mean-calibration; Brier beats no-skill baseline; reliable probabilities.
- **Kaggle priors** (1950–2024): correctly-keyed overtaking_difficulty, pit_loss_s,
  dnf_rate (0.171). Fixed the circuit-key bug — see [[Environment Gotchas]].

## ✅ Done — Live mode (June 2026)
Live ingest is now an **interchangeable producer** on the same event bus as
replay, so every feature (track map, leaderboard, predictions, Car/Track panels)
works identically live or replayed — the spec's "indistinguishable in features"
bar. **No WS schema change** was needed: `SessionMsg.mode`/`delay_s` already
existed in protocol v1.

**New backend modules**
- `backend/ingest/openf1_normalize.py` — turns raw OpenF1 rows (per endpoint)
  into the **same `(t_s, kind, payload)` events** the fixture path uses
  (`pos_frame, car_tel, interval, position, lap_start/done, stint, pit, weather,
  rc`). One mapping, two delivery shapes; reuses `DRS_OPEN`/`_gap` from
  `fixture_store` so live and recorded data can't drift.
- `backend/ingest/live_source.py` — transport seam. `OpenF1RestSource`
  (authenticated incremental **`date>` cursor** polling; `http_get` injected so
  it's unit-testable offline) + `OpenF1MqttSource` **stub** + `make_live_source()`
  factory (the **MQTT hook** to fill in later — chosen over adding `aiomqtt` now).
  `laps` is refetched whole each poll (a lap row gets `lap_duration` only at
  completion, so a strict cursor would miss it); `stints` deduped by
  (driver, stint_number).
- `backend/ingest/live_client.py` — `LiveClient`, mirrors `ReplayEngine`'s
  surface (`run/stop/snapshot/play/pause/set_speed/seek`; seek+speed are no-ops
  live). Drives `RaceState` + `Predictor` from polled rows, computes the **real
  data-delay** (`now − newest sample timestamp` → `delay_s`), GPS-gap retirement,
  reconnect/backoff, and an **empty "No live session"** state. Session-time
  origin = `date_start`; total laps from `circuit_facts/<key>.json` (else 0 → UI
  shows `/–`, never faked).

**Wiring** — `app.py` reads `OPENF1_TOKEN` (+ optional `OPENF1_TRANSPORT`,
default `rest`); `switch_session("live")` builds a `LiveClient`, else a
`ReplayEngine`. `rest.py /api/sessions` prepends a **`● LIVE SESSION`** entry
**only when a token is set** (degrade to replay-only otherwise). `ws.py`
unchanged — it treats both producers identically. `RaceState.session()` gained
`mode`/`delay_s` kwargs (defaults preserve replay; **not** a wire change).

**Frontend** (`StatusBar.tsx` + `shell.css`, no new deps) — a pulsing **● LIVE**
pill in the race picker (sends `select_session:"live"`); live-aware transport
(**no scrub/speed** when live, only freeze/resume); a prominent **`broadcast
+Ns`** delay readout; lap shows `/–` when total unknown; an **empty-state** line
when no race is live.

**Tests** — `backend/tests/test_live.py`, **20 tests, all green** (normalizer per
endpoint, REST discovery + cursor advance, MQTT-stub raises, LiveClient
session/leaderboard/tyres/predictions/SC flag, empty + reconnect, async run-loop,
and a reality check that **replays recorded Canada as a live stream → real podium
VER/NOR/RUS**). Full suite: all pass except the one pre-existing stochastic
Monte-Carlo test (env-sensitive NumPy, see [[Calibration Log]] — unrelated).

**Two-page navigation (June 2026 update)** — Replay and Live are now **separate
pages** via persistent top tabs (`features/shell/PageTabs.tsx`): **▦ Replay**
(Year→GP picker + full scrub/speed transport) and **● Live** (always reachable;
`LiveStandby.tsx` shows a *no-token* or *waiting-for-a-race* screen when idle, the
full live dashboard when a race is streaming). `App.tsx` owns `page` (in
`raceStore`, default `replay`), fetches `/api/sessions` once to know whether live
is offered, and sends `select_session` on tab switch (remembering the last replay
race so Replay restores it). `StatusBar.tsx` is page-aware (replay picker vs live
label, transport hidden on standby). The old in-picker `● LIVE` pill was removed —
the Live tab replaces it. No backend change (the `"live"` session id + token gate
already existed); `tsc --noEmit` clean.

**Still host/real-feed only (can't run in-sandbox)**
- A real live race + a paid token to watch it end-to-end (sandbox blocks F1
  domains — see [[Environment Gotchas]]). Run on the host: set `OPENF1_TOKEN` in
  `.env`, start backend + frontend, pick **● LIVE**.
- `OpenF1MqttSource` is a documented stub (the lower-latency transport); REST
  polling is the working path. **Legitimate OpenF1 paid feed only** — no
  pirated/3rd-party streams (see [[Data Sources and Constraints]]).

Related: [[Design System]] · [[Calibration Log]] · [[Prediction Models]] · [[Architecture]] · [[Data Sources and Constraints]] · [[Environment Gotchas]] · [[About Me]]
