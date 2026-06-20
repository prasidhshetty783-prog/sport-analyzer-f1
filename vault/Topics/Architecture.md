---
title: Architecture
type: topic
tags: [architecture, backend, frontend, websocket, layout]
updated: 2026-06-19
---

# Architecture

> Modules, the event-bus seam, the WS protocol, and repo layout. Back to [[Home]].

## Data flow
```
OpenF1 live (Phase 5 ✅) ─┐
ingest/live_client.py     ├─▶ core/event_bus.py ─▶ state/race_state.py ─▶ models/ ─▶ api/ws.py ─▶ frontend
ingest/replay_engine.py ──┘                                                         api/rest.py
(recorded fixtures)
```
- **One internal event bus** (`backend/core/event_bus.py`): live ingest and replay
  are **interchangeable producers** — `ReplayEngine` and `LiveClient` expose the
  same surface (`run/stop/snapshot/play/pause/...`) and emit the same WS kinds, so
  every feature works in both modes ([[Phase 1 - Replay and Leaderboard|Replay]]
  stays first-class).
- **Live producer (Phase 5):** `ingest/live_source.py` (`OpenF1RestSource` REST
  poller behind `OPENF1_TOKEN` + `OpenF1MqttSource` stub + `make_live_source()`),
  `ingest/openf1_normalize.py` (raw OpenF1 rows → the shared fixture event
  vocabulary), `ingest/live_client.py` (drives `RaceState`+`Predictor`, real
  `delay_s`, reconnect/empty handling). `app.py` builds a `LiveClient` for the
  synthetic `"live"` session, else a `ReplayEngine`. See [[Phase 5 - Polish UX and Live Mode]].
- `SportAdapter` interface keeps F1 swappable later — don't over-engineer past it.

## Repo layout
```
scripts/    Phase 0 spikes: check_*, record_*, fetch_*, data_report, _common
backend/    api/ core/ ingest/ models/ state/ tests/   (Python 3.10+, FastAPI)
frontend/   React 18 + TS + Vite; src/features/*; tokens in src/styles/tokens.css
ml/         training + backtest scripts; reports in ml/reports/
data/       gitignored: fixtures/ circuit_geo/ circuit_info/ circuit_facts/ kaggle/ fastf1_cache/ processed/
models/artifacts/   priors.json + serialized models (gitignored)
vault/      this Obsidian vault
```

## WS protocol — one schema, two languages
- Source of truth: `backend/api/schema.py` (Pydantic).
- Generate TS: `python -m backend.api.gen_types` → `frontend/src/lib/ws/types.ts`
  (a test fails if stale).
- **Message kinds:** `positions`, `leaderboard`, `car_telemetry`, `prediction`,
  `race_control`, `weather`, `session`.
- ⚠️ **Changing this schema requires explicit approval** ([[About Me]] working agreement).

## REST endpoints (`backend/api/rest.py`, all cached in-process)
- `/api/health`, `/api/sessions`
- `/api/track/{id}` — 2D outline + elevation + corners + geo
- `/api/drivers/{id}` — roster + OpenF1 `headshot_url`
- `/api/circuit/{id}` — Track Detail facts (laps, length, distance, records)

## Frontend state
`src/store/raceStore.ts` (zustand): WS messages → state. Slices include `rows`,
`telemetry`, `predictions`, `driverMeta`, `selectedDrv`, `view3D`, `session`,
`weather`, `conn`.

## Conventions
- No DB in v1 — in-memory state + Parquet/JSON caches.
- Models served **in-process**; trained offline in [[Prediction Models|ml/]].
- Styling = semantic CSS variables only (see [[Design System]]).

Related: [[Phase 1 - Replay and Leaderboard]] · [[Data Sources and Constraints]] · [[Prediction Models]] · [[Commands and Run Guide]]
