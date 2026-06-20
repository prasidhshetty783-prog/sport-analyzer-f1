---
title: Phase 0 - Data Access Spike
type: phase
phase: 0
status: done
tags: [phase, data, fixtures]
updated: 2026-06-18
---

# Phase 0 — Data Access Spike ✅

> No app code — prove the data exists and record a replay fixture. Back to [[Home]].

## Goal
Verify all community F1 sources are reachable and capture one full historical race
to `data/fixtures/` so the app is demoable any day without a live session.

## What was built
- `scripts/` spikes: `check_*.py` (hit OpenF1 / FastF1 / Jolpica and print sample
  rows), `record_fixture.py` (record one race), `record_all.py` (batch, resumable),
  `data_report.py` (availability scorecard), `_common.py` (rate-limited `openf1_get`).
- A recorded **fixture format** consumed unchanged by the Phase 1 replay engine.

### Fixture format
`data/fixtures/<year>_<country>_race/` — one Parquet per stream
(`location`, `car_data`, `position`, `intervals`, `laps`, `stints`, `pit`,
`weather`, `race_control`, `drivers`) + `meta.json` (`fixture_version: 1`).
- Gotcha: `intervals.gap_to_leader`/`interval` are **strings** when the race has
  lapped cars (OpenF1 mixes floats with `'+1 LAP'`) — replay parses both.
- ~95 fixtures now on disk (2023→). Default demo race: **2024 Canada** (SC + rain).

## Acceptance
One command prints a data-availability report and the fixture exists. Then
`CLAUDE.md` was written.

## Key constraint surfaced here
OpenF1 only carries **2023→present**, and it's the only source with the
GPS `location` + `car_data` streams replay needs → **pre-2023 races can't be
replayed.** Details in [[Data Sources and Constraints]].

Related: [[Architecture]] · [[Data Sources and Constraints]] · [[Environment Gotchas]] · [[Commands and Run Guide]] · [[Phase 1 - Replay and Leaderboard]]
