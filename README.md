# 🏎️ Sport Analyzer — F1 Live

A real-time **Formula 1 race dashboard**: cars moving on a live track map, per-car telemetry, and machine-learning predictions (tyre life, pit windows, projected finishing position) that update as the race unfolds.

> **Unofficial, fan-built, educational project.** Not affiliated with Formula 1. No F1/team logos, no official fonts, no betting features. All data comes from community sources (OpenF1, FastF1, Jolpica/Ergast, a public Kaggle results dump).

It runs in two modes, presented as two pages:

- **▦ Replay** — re-watch any recorded race with a full transport (play/pause, 1×/2×/10×, scrub) and all the predictions. Works out of the box, no account needed.
- **● Live** — follow a race happening right now from the OpenF1 real-time feed (needs a paid OpenF1 token). Honest about being a few seconds behind the broadcast, with a visible delay indicator.

## Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [How accurate are the predictions](#how-accurate-are-the-predictions)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Project status](#project-status)
- [Tests](#tests)
- [Data sources and attribution](#data-sources-and-attribution)
- [License](#license)

## Features

- **Live 2D track map** — cars interpolated at 60 fps on a circuit outline derived from real GPS traces, with a real-world map underlay (OSM/CARTO tiles), team colours from data, corner numbers, and click-to-select synced with the leaderboard.
- **Live leaderboard** — positions, gaps and intervals (including lapped `+1 LAP` cars), last-lap times, tyre compound and age, pit counts.
- **Car Detail panel** — speed/gear/throttle/brake/DRS telemetry plus the AI cards. Every field is tagged **LIVE** (real data), **EST** (estimated), or **AI** (model output) — a model output is never shown as if it were telemetry.
- **AI predictions** — tyre degradation and "laps to the cliff", a Monte-Carlo finishing-position forecast (P(win)/P(podium)/P(points) plus a full distribution), per-circuit safety-car likelihood, and a fuel-load estimate.
- **3D Track Detail** — a Three.js view with an elevation-aware track ribbon, terrain, a drone fly-over, winners/records, and an elevation profile.
- **Replay is first-class** — recorded races re-emit through the *same* internal event bus as the live feed, so every feature works identically in both modes.

## Screenshots


https://github.com/user-attachments/assets/4cf0a02d-79be-4b6e-9a55-b9ddd5dce6ab



## How accurate are the predictions

Finishing-position forecasts are scored mid-race against the real result, and compared to a **persistence baseline** (just "freeze the current order"):

- **Finish-position error (MAE): ~1.9 positions** on stable 2023–24 races after calibration — i.e. on average a car's predicted finish is within ~2 places of reality. That is roughly level with the persistence baseline on these races; the model's edge shows up in chaotic races and in the probabilities, not in beating persistence on calm ones.
- **Top-3 hit rate: ~0.75** — about three out of four podium slots are correctly identified mid-race.
- **Safety-car model: +2.3% skill over a no-skill baseline** (Brier 0.0681 vs 0.0696), with well-calibrated probabilities (predict ~12% → ~13% actually happen).

Full methodology, per-race tables, and how to improve these numbers are in [`docs/AI_MODEL_REPORT.md`](docs/AI_MODEL_REPORT.md).

## Tech stack

- **Backend** — Python 3.10+, FastAPI, WebSockets; NumPy for the Monte-Carlo sim; XGBoost/LightGBM for offline model training (distilled to lightweight coefficients served in-process). No database — in-memory state plus Parquet/JSON caches.
- **Frontend** — React 18 + TypeScript + Vite, Zustand, a hand-rolled Canvas track map, and Three.js for the 3D view. No charting/UI mega-dependencies.
- **Data** — OpenF1 (live + 2023→ telemetry/GPS), FastF1 (deep history for training), Jolpica/Ergast (results back to 1950), a Kaggle 1950–2024 results dump (priors).

## Quick start

```bash
# once
pip install -r requirements.txt
cd frontend && npm install && cd ..

# terminal 1 — backend  (http://localhost:8000)
python -m uvicorn backend.app:app --reload --port 8000

# terminal 2 — frontend (http://localhost:5173)
cd frontend && npm run dev
```

Open http://localhost:5173 and use the **Replay** tab. The full step-by-step — including how to enable Live mode and how to retrain the AI models — is in [`RUN_GUIDE.md`](RUN_GUIDE.md).

## Architecture

```text
OpenF1 live ───────────────┐
ingest/live_client.py      ├─▶ core/event_bus.py ─▶ state/race_state.py ─▶ models/ ─▶ api/ws.py ─▶ frontend
ingest/replay_engine.py ───┘   (one internal event bus; live + replay are interchangeable producers)
(recorded fixtures)
```

The WebSocket protocol lives in **one file** (`backend/api/schema.py`); TypeScript types are generated from it (`python -m backend.api.gen_types`). The prediction models live in `backend/models/` and are trained offline in `ml/`. A deeper tour is in the interlinked Obsidian notes under [`vault/`](vault/) (start at `vault/Home.md`).

## Project status

All five build phases are complete:

| Phase | What |
| --- | --- |
| 0 | Data-access spike (OpenF1 / FastF1 / Jolpica reachable, fixture recorder) |
| 1 | Event bus, replay engine, WS server, leaderboard |
| 2 | Live 2D track map (GPS-derived outline + real-world tiles) |
| 3 | Prediction engine (tyre / Monte-Carlo finish / safety-car / fuel) + Car panel |
| 4 | Track Detail + 3D scene |
| 5 | Live mode (token-gated) + premium restyle + two-page Replay/Live UI |

## Tests

```bash
python -m pytest backend/tests -q     # backend (incl. live-mode tests; needs the Canada fixture)
cd frontend && npx tsc --noEmit       # frontend type-check
```

## Data sources and attribution

- [OpenF1](https://openf1.org) — live and recent timing/telemetry (historical is free; real-time needs a paid token).
- [FastF1](https://github.com/theOehrly/Fast-F1) — deep historical telemetry for training.
- [Jolpica](https://github.com/jolpica/jolpica-f1) (Ergast successor) — results back to 1950.
- Kaggle "Formula 1 World Championship (1950–2024)" results dump — model priors.
- Map tiles — OpenStreetMap data, CARTO basemaps (attribution shown in-app).

Please review each source's terms before deploying publicly.

## License

[MIT](LICENSE) for the code in this repository. F1 data remains subject to its providers' terms; "Formula 1", "F1", team names and marks belong to their respective owners and are used here only descriptively.
