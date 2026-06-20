---
title: Phase 1 - Replay and Leaderboard
type: phase
phase: 1
status: done
tags: [phase, replay, backend, websocket]
updated: 2026-06-18
---

# Phase 1 — Replay Pipeline & Leaderboard ✅

> The spine: event bus + replay engine + WS server + frontend shell. Back to [[Home]].

## Goal
Re-stream a recorded race through an internal event bus so a recorded race
replays end-to-end with correct positions, gaps, tyres, and flags.

## What was built
### Backend
- `backend/core/event_bus.py` — single async pub/sub seam. Live ingest (Phase 5)
  will publish to the **same** bus → replay is first-class, not a dev hack.
- `backend/ingest/fixture_store.py` — Parquet streams → typed, time-sorted events.
- `backend/ingest/replay_engine.py` — virtual clock: **1×/2×/10×**, pause, seek;
  opens at the grid (`race_start_s − 15`).
- `backend/state/race_state.py` — derives leaderboard, flags (incl. SC/VSC), lap.
- `backend/api/ws.py` + `rest.py` — FastAPI `/ws` broadcast + `/api/sessions`.

### Frontend
- React 18 + TS + Vite; `src/store/raceStore.ts` (zustand); reconnecting WS client
  (`src/lib/ws/client.ts`); shell + status bar + transport + live leaderboard.

### WS protocol (one schema → two languages)
`backend/api/schema.py` → `python -m backend.api.gen_types` →
`frontend/src/lib/ws/types.ts` (a test fails if stale). **Changing this schema
requires explicit approval** (see [[About Me]] working agreement). Message kinds:
`positions`, `leaderboard`, `car_telemetry`, `prediction`, `race_control`,
`weather`, `session`. Full layout in [[Architecture]].

## Acceptance
A recorded race replays end-to-end with correct order/gaps/tyres/flags. **19 tests**
incl. real Canada-2024 integration (podium VER/NOR/RUS, SC derivation, seek,
`'+1 LAP'` gap strings).

## Notable fix (later session)
Lap counter jumped to N/N on race switch — a `laps` row with NaT `date_start`
produced a NaN-time event that poisoned `events.sort()`; `fixture_store.py` now
drops non-finite-time events before sorting.

Related: [[Architecture]] · [[Phase 0 - Data Access Spike]] · [[Phase 2 - Live Track Map]] · [[Commands and Run Guide]]
