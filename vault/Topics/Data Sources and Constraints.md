---
title: Data Sources and Constraints
type: topic
tags: [data, openf1, fastf1, jolpica, kaggle, constraints]
updated: 2026-06-19
---

# Data Sources & Hard Constraints

> Where F1 data comes from + the 6 rules we never silently break. Back to [[Home]].

## Sources
| Source | Covers | Used for |
|---|---|---|
| **OpenF1** (REST/MQTT) | **2023→present** | Live + recent: `location` (GPS), `car_data`, `position`, `intervals`, `laps`, `stints`, `pit`, `weather`, `race_control`, `drivers`. The **only** source with GPS/telemetry streams → the only replayable era. |
| **FastF1** (Python) | telemetry **2018→**, timing further back | Training data (`ml/build_training_set.py`), circuit info/corners, session recording. Host-only. |
| **Jolpica** (Ergast successor) | results **1950→** | Track Detail winners/records, long-horizon labels. |
| **Kaggle** (rohanrao 1950–2024) | results-level history | Finish/DNF/overtaking/pit-loss priors. See [[Calibration Log]] for how it's wired. |

### Replay vs training era (important)
- **Replay** needs GPS `location` + `car_data` → **OpenF1 only → 2023→.**
  `scripts/record_all.py` defaults to 2023..current; older `--seasons` return empty.
  **Pre-2023 races cannot be replayed.**
- **Training** can reach back: FastF1 telemetry 2018→, Kaggle/Jolpica results 1950→.
  Lowers model MAE; does **not** create replayable races.

## The 6 hard constraints (never silently violate)
1. **No official F1 API.** Use OpenF1 / FastF1 / Jolpica only.
2. **Live needs a paid `OPENF1_TOKEN`.** Gate all live features behind it; the app
   must degrade to **replay-only** without it. ✅ **Implemented (Phase 5):**
   `OpenF1RestSource` (REST polling) → `LiveClient`; no token ⇒ no `● LIVE`
   entry, replay-only. MQTT is a documented stub. See [[Phase 5 - Polish UX and Live Mode]].
3. **Tag every UI field LIVE / EST / AI.** Fuel = EST, tyre life = AI model output —
   never present them as telemetry. "Real time" = broadcast-synced (seconds behind);
   show a delay indicator. (See [[Design System]], [[Prediction Models]].)
4. **Replay is first-class** — recorded fixtures re-emit through the same event bus
   as live ingest; every feature works in both modes. (See [[Architecture]].)
5. **Respect rate limits** (OpenF1 free ≈ 3 req/s); chunk bulk pulls, cache to disk.
6. **No F1/team logos or official fonts**; team colours come from data
   (`team_colour`). **No betting features.**

## ⛔ Off-limits: pirated/3rd-party streams
For live mode we will **not** source API keys or access for unlicensed streaming
sites (e.g. Footybite). The legitimate path is **OpenF1's paid real-time plan**
(already the architecture), or officially licensed F1 timing/data providers.

Related: [[Environment Gotchas]] (these domains are blocked in-sandbox) · [[Phase 0 - Data Access Spike]] · [[Phase 5 - Polish UX and Live Mode]] · [[Calibration Log]]
