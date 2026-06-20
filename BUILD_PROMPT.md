# Build Prompt — Sport Analyzer: F1 Live (v1)

> **How to use this file:** Open an empty repo in Claude Code and paste this entire document as your first message (or save it as `BUILD_PROMPT.md` in the repo root and say "Read BUILD_PROMPT.md and start Phase 0"). Work phase by phase — review and approve each phase before moving to the next. After Phase 0, ask Claude Code to generate a `CLAUDE.md` capturing the project conventions below.

---

## 1. What we're building

**Sport Analyzer** is a real-time sports intelligence platform. Sport #1 is **Formula 1**: a live race dashboard that shows cars moving on a circuit map in real time, deep per-car telemetry, and ML-powered predictions (tire life, pit strategy, projected finishing position) that update as the race unfolds.

- **Primary user:** F1 fans watching a race who want broadcast-grade data + predictive insight in one screen.
- **MVP:** One web app, one sport (F1), works in two modes: **Live** (during a real session) and **Replay** (re-streams a recorded historical race through the exact same pipeline).
- **Future:** Other sports will be added later. Architect for this from day one (see §6, `SportAdapter`), but build zero non-F1 features now.

---

## 2. Ground rules — read before writing any code

These are hard constraints based on what F1 data actually exists. Do not silently violate them.

1. **There is no official public F1 API.** We use community sources: **OpenF1** (REST/MQTT, 2023→present), **FastF1** (Python library, deep historical telemetry + session recording), and **Jolpica** (community successor to the deprecated Ergast API, results back to 1950). Phase 0 must verify all three are reachable before anything else gets built.
2. **OpenF1 historical data is free and unauthenticated; real-time access requires a paid OpenF1 account** (OAuth2 bearer token; MQTT-over-WSS is the preferred live transport). Build everything against historical/replay data first. Gate live mode behind an `OPENF1_TOKEN` env var so the app degrades gracefully without one.
3. **"Real time" means broadcast-synced, not instantaneous.** Live data lands roughly a few seconds behind the world feed. Show a small "data delay" indicator in the UI; never claim millisecond accuracy.
4. **Some values the user asked for are NOT broadcast by F1 and must be modeled, not fetched.** Specifically:
   - **Fuel remaining** → estimated (cars start with ≤110 kg; per-lap burn rate calibrated per circuit). Label it "est." in the UI.
   - **Tire remaining life** → predicted by our ML model from compound, stint age, temps, fuel load, and traffic. Label it "predicted."
   - Compound, stint age, speed, throttle, brake, gear, DRS, gaps, positions, weather, flags **are** real feed data.
   Every field in the UI must be visually tagged as `LIVE`, `EST`, or `AI` so we never misrepresent model output as telemetry.
5. **Replay mode is a first-class feature, not a dev hack.** Races happen ~24 weekends a year; the app must be fully demoable any day. The replay engine re-emits a recorded session through the same internal event bus at 1×/2×/10× speed with play/pause/scrub. All UI features must work identically in both modes.
6. **GPS positions:** OpenF1's `location` endpoint provides per-car x/y/z track coordinates sampled at ~3.7 Hz; `intervals` updates roughly every 4 s. The frontend must buffer and interpolate (see §7) — raw samples are too sparse for smooth 60 fps motion.
7. **Legal/branding:** This is an unofficial fan/educational project. Do not use the F1 logo, official F1 fonts, or team logos. Use driver codes (HAM, VER…), team names as text, and team colors (available from OpenF1's drivers endpoint as `team_colour`). No betting/wagering features of any kind.

---

## 3. Data sources

### 3.1 Live + recent (2023→present)

**OpenF1** — `https://api.openf1.org/v1/` — REST (JSON/CSV) + MQTT/WSS for live.

| Endpoint | Gives us | Feeds |
|---|---|---|
| `location` | x, y, z car coordinates, ~3.7 Hz | Live track map |
| `car_data` | speed, throttle, brake, n_gear, rpm, drs, ~3.7 Hz | Car detail panel |
| `position` | running order | Leaderboard |
| `intervals` | gap to leader + interval to car ahead (~every 4 s) | Leaderboard, dirty-air feature |
| `laps` | lap + sector times, pit-out flags | Pace model inputs |
| `stints` | compound, tyre_age_at_start, stint lap range | Tire model inputs |
| `pit` | pit stop durations + lap numbers | Strategy model |
| `weather` | air temp, track temp, humidity, rainfall, wind | Tire + hazard models, track panel |
| `race_control` | flags, safety car, VSC, red flag messages | Hazard model, status bar |
| `sessions`, `meetings`, `drivers` | metadata, driver names, `team_colour` | Everything |

Respect rate limits (free tier ≈ 3 req/s). Prefer bulk historical pulls cached to disk; for live, prefer MQTT/WSS over polling.

### 3.2 Deep history + telemetry (training data)

- **FastF1** (Python, `pip install fastf1`): per-session laps (LapTime, Compound, TyreLife, Stint, sector times, TrackStatus), full telemetry (Speed, Throttle, Brake, X/Y/Z, Distance), per-session weather (AirTemp, TrackTemp, Rainfall…), and `circuit_info` (corner positions, track rotation). Also includes a live-timing **recorder** — use it to capture sessions for replay fixtures. Enable its on-disk cache (`data/fastf1_cache/`).
- **Jolpica-F1** (`https://api.jolpi.ca/ergast/f1/`): Ergast-compatible results, standings, circuits back to 1950 — for the Track Detail "previous winners" panel and long-horizon training labels.

### 3.3 Kaggle datasets (for training the prediction models)

Download via the `kaggle` CLI into `data/kaggle/` (user will provide `KAGGLE_USERNAME`/`KAGGLE_KEY`; if absent, print the manual download URLs and continue).

| Kaggle dataset | Contents | Used for |
|---|---|---|
| `rohanrao/formula-1-world-championship-1950-2020` (updated through recent seasons despite the name) | Full Ergast dump: `races`, `results`, `lap_times`, `pit_stops`, `qualifying`, `drivers`, `constructors`, `circuits`, `status`, `sprint_results`, standings CSVs | Finish-position model labels, overtaking-difficulty index per circuit, DNF/reliability rates (`status.csv`), pit-loss times, previous winners |
| `cjgdev/formula-1-race-data-19502017` | Alternative Ergast-style historical dump | Cross-check / backfill |
| `alexjr2001/formula-1-dataset-race-data-and-telemetry` | FastF1-derived telemetry & lap aggregates, race/weather metadata, updatable per race | Tire-degradation model pretraining, pace baselines |
| `mkaur1141/formula-1-world-championship-dataset-20002026` | Races, results, qualifying, standings through the 2026 season | Recent-era labels, current-grid priors |
| `dubradave/formula-1-drivers-dataset` | Driver career stats | Driver skill prior feature |

**Important:** Kaggle covers results-level history well, but the highest-value training table for the tire model is **built, not downloaded**: write `ml/build_training_set.py` that uses FastF1 to assemble a stint-level dataset for the last 3–4 seasons (every lap: driver, team, circuit, compound, TyreLife, fuel-corrected lap time, AirTemp, TrackTemp, rainfall, gap-to-car-ahead, TrackStatus). Cache the result as Parquet in `data/processed/`. Treat Kaggle as the historical backbone and FastF1 extraction as the telemetry backbone.

---

## 4. MVP features

Global shell: dark, broadcast-style single-page app. Top status bar = session name, flag status (green/yellow/VSC/SC/red), lap counter `LAP 34/58`, weather chip, data-delay indicator, Live/Replay mode switch + replay transport controls (play/pause, speed, scrub). Session picker on load (live session if available, else recorded replays).

### 4.1 Live Track Map (home view)

- 2D top-down circuit rendered from the session's position-data trace (derive the track outline by plotting a fastest-lap X/Y path; rotate using FastF1 `circuit_info` rotation). Canvas or SVG — pick whichever profiles better at 20 markers × 60 fps.
- Each car = a circular marker in `team_colour` with the 3-letter driver code, smoothly interpolated between position samples. Optional short trailing motion line.
- Sector boundaries and start/finish line marked; corners numbered (from `circuit_info`).
- Yellow/SC/red flag conditions tint the affected UI (full-course tint for SC/red).
- **Click a car → opens the Car Detail panel (4.2). Click the track itself (or a "Track info" button) → opens Track Detail (4.3).**

### 4.2 Car Detail panel (right-side slide-in)

Selecting a driver (e.g., Hamilton/Ferrari) shows, with each field tagged `LIVE` / `EST` / `AI`:

| Field | Source | Tag |
|---|---|---|
| Current speed, gear, throttle/brake bars, DRS state | `car_data` | LIVE |
| Position, last lap, best lap, gap ahead/behind | `position`, `laps`, `intervals` | LIVE |
| Tire compound + stint age (laps) | `stints` | LIVE |
| Clean air / dirty air state | derived: interval-ahead < 2.0 s ⇒ dirty | EST |
| **Fuel remaining (kg + "laps of fuel")** | fuel estimator (§5.4) | EST |
| **Tire life remaining** ("~8 laps to cliff" + degradation curve sparkline) | Tire model (§5.1) | AI |
| **Pit stops remaining** (e.g., "1 more likely, window lap 38–44") | Strategy logic (§5.2) | AI |
| **Predicted finish** — expected position + distribution chips: P(win), P(podium), P(points), with a small bar chart of the finish-position distribution | Monte Carlo engine (§5.2) | AI |

Prediction cards must show confidence and refresh on a visible cadence ("updated 12 s ago"). When SC/red flag is deployed, predictions visibly recompute (this is where the product feels alive).

### 4.3 Track Detail view

- **3D circuit model** with real elevation — the "race-day flyover" look. Build pipeline (`ml/build_track_assets.py`): take a clean fastest-lap FastF1 telemetry trace (X/Y/Z), smooth it (Savitzky–Golay), resample the centerline, extrude a track-width ribbon mesh with ~2–3× vertical exaggeration, color sectors, mark corner numbers and DRS zones, export glTF per circuit. Render with **Three.js**: orbit controls + an automated "flyover" camera path. *Fallback if Z data is too noisy for a circuit:* circuit centerline GeoJSON (e.g., the open `f1-circuits` GeoJSON repo) + sampled elevations from an open elevation API, cached.
- **Side panel:** circuit name/country/length/laps; lap record; previous winners table (Jolpica/Kaggle `races`+`results` join, last 10 years); live conditions now — track temp, air temp, humidity, rainfall, wind (OpenF1 `weather`).

### 4.4 Race Leaderboard (left rail, always visible)

Per row: position (with up/down change animation), driver code + team color bar, gap to leader, interval to car ahead, last lap time, current compound icon + tire age, pit stop count. Hover/tap shows gap to the car behind. Clicking a row selects that car everywhere (map + panel stay in sync). Mini "battle" highlight when interval < 1.0 s.

---

## 5. Prediction engine ("the AI")

All models live in `backend/models/`, trained offline by scripts in `ml/`, serialized to `models/artifacts/`, and served in-process by the FastAPI backend. Start with gradient-boosted trees (XGBoost or LightGBM) — no deep learning in v1.

### 5.1 Model A — Tire degradation & remaining life

- **Training data:** the FastF1-built stint table (§3.3) + Kaggle telemetry dataset.
- **Features:** compound, tyre age (laps), circuit ID, estimated fuel load, AirTemp, TrackTemp, rainfall flag, dirty-air share of recent laps (interval-ahead < 2 s), driver, team, stint number, track status.
- **Targets:** (a) regression — fuel-corrected lap-time delta vs. the driver's fresh-tire baseline for that stint; (b) classification — "performance cliff within next 3 laps."
- **Output to UI:** current deg rate (s/lap), projected laps until cliff, degradation curve for the sparkline.
- Apply a fuel correction of ~0.03 s per kg when normalizing lap times.

### 5.2 Model B — Finish-position prediction (Monte Carlo race simulator)

A per-lap stochastic simulation, not a single regression — because the user explicitly wants safety cars and red flags to influence the prediction.

- **State per car:** position, gap, compound + age, est. fuel, pit stops done, compounds used (enforce the two-compound rule in dry races).
- **Each simulated lap:** sample lap time from Model A's pace prediction + noise; simple pit-strategy policy (pit near tire cliff; opportunistic cheap stop under SC); overtake attempt when pace delta > threshold, success probability scaled by a per-circuit **overtaking-difficulty index** (computed offline from historical position changes in Kaggle `lap_times`/`results`); DNF hazard from historical reliability (`status.csv`); SC/red-flag events drawn from Model C.
- **Run:** 1,000–2,000 vectorized (NumPy) simulations per refresh; refresh every ~30 s and immediately on pit stops, SC/VSC, or red flags. Budget < 2 s per refresh on a laptop.
- **Output:** full finish distribution per driver → expected finish, P(win)/P(podium)/P(points).
- **Baseline for sanity:** a plain XGBoost "state → finish position" model; the simulator must beat it on backtests before it ships.

### 5.3 Model C — Safety car / red flag hazard

Per-lap deployment probability: per-circuit historical SC/red rates (some circuits are near-certain SC, others rare) × multipliers for rain, lap-1, and recent incident density (from `race_control`). Logistic regression or simple GBM is fine. Also exposed in the Track Detail panel as "SC likelihood today."

### 5.4 Fuel estimator (deterministic, not ML)

`fuel_remaining = start_load − Σ(burn_per_lap)`, with start load ≤ 110 kg and a per-circuit burn table (~1.2–1.9 kg/lap, reduced ~35% under SC/VSC). Calibrate the burn table offline from circuit length/characteristics; expose both kg and "laps of fuel."

### 5.5 Evaluation protocol (must exist before models ship)

- Time-based split: train ≤ 2023 seasons, validate 2024, test 2025 (adjust to data available).
- **Backtest harness** (`ml/backtest.py`): reconstruct race state at lap *k* for held-out races, run the full prediction stack, compare to real outcomes. Metrics: MAE of finish position, top-3 hit rate, Brier score + calibration plot for SC-within-10-laps, tire-cliff lead time error. Print a scorecard; store results in `ml/reports/`.

---

## 6. Architecture

```
            ┌──────────────────────────── backend (Python / FastAPI) ───────────────────────────┐
 OpenF1 ───▶│ ingest/openf1_client.py ──┐                                                       │
 (REST/MQTT)│                           ├─▶ core/event_bus.py ─▶ state/race_state.py            │
 Recorded ─▶│ ingest/replay_engine.py ──┘            │                  │                       │
 sessions   │                                        ▼                  ▼                       │
 (FastF1 /  │                              models/ (tire, montecarlo,  api/ws.py  api/rest.py   │
  fixtures) │                              hazard, fuel)                 │            │          │
            └────────────────────────────────────────────────────────────┼────────────┼─────────┘
                                                                         ▼            ▼
                                                       frontend (React + TS + Vite, WebSocket client)
```

- **One internal event bus**; live ingest and replay are interchangeable producers. This is the seam that makes Replay a first-class mode and the seam future sports plug into.
- **`SportAdapter` interface** (`backend/core/adapter.py`): `list_sessions()`, `stream_events()`, `get_static_assets()`. F1 implements it; future sports implement it later. Don't over-engineer beyond this interface.
- **WebSocket protocol** — typed JSON messages; define TS types + Pydantic models from one schema file:
  - `positions` `{t, cars:[{drv, x, y, z}]}` (high frequency)
  - `leaderboard` `{rows:[{pos, drv, team, gap_leader, interval, last_lap, compound, tyre_age, pits}]}`
  - `car_telemetry` `{drv, speed, gear, throttle, brake, drs}`
  - `prediction` `{drv, finish:{exp, p_win, p_podium, p_points, dist}, tyre:{deg_rate, laps_to_cliff}, fuel:{kg, laps}, updated_at}`
  - `race_control` `{flag, message}` · `weather` `{air, track, humidity, rain, wind}` · `session` `{lap, total_laps, mode, delay_s}`
- **Stack:** Python 3.11+, FastAPI + uvicorn, NumPy/pandas, XGBoost or LightGBM, FastF1; React 18 + TypeScript + Vite, Zustand (or similar light store), Three.js for the 3D track, Canvas/SVG for the 2D map. No database in v1 — in-memory state + Parquet/JSON file caches. Docker-compose optional, not required.

```
sport-analyzer/
├── BUILD_PROMPT.md  · CLAUDE.md  · README.md  · .env.example
├── backend/   (api/ · core/ · ingest/ · models/ · state/ · tests/)
├── frontend/  (src/features/{track-map,car-panel,track-detail,leaderboard,shell}/ · src/lib/ws/ · src/styles/tokens.css)
├── ml/        (build_training_set.py · train_*.py · backtest.py · build_track_assets.py · reports/)
├── data/      (kaggle/ · fastf1_cache/ · processed/ · fixtures/)   ← gitignored
└── models/artifacts/
```

---

## 7. Frontend & UX requirements

- **Smooth motion:** buffer incoming position samples ~3–5 s and interpolate (linear or Catmull-Rom along the track path) so markers glide at 60 fps despite ~3.7 Hz input. Pause/scrub must not break interpolation.
- **Design tokens:** semantic CSS variables only (`--color-bg-surface`, `--color-accent`, `--color-flag-sc`, …) in `src/styles/tokens.css`, 8-pt spacing scale, one accent color + team colors from the data. Dark theme default; structure tokens so a light theme is a variable swap. Typeface: one geometric/technical sans (e.g., a free Titillium-style face) — no F1 official fonts. I'll restyle later, so keep all styling in tokens + small component styles, never inline hex values.
- **Performance budget:** 20 animated markers + leaderboard updates without dropped frames on a mid-range laptop; 3D track view lazy-loaded.
- Tag every data point `LIVE`/`EST`/`AI` (subtle chip), show prediction freshness, and animate position changes — the product's credibility depends on honest labeling.

---

## 8. Build phases (with acceptance criteria)

**Phase 0 — Data access spike (no app code).** Scripts that: hit OpenF1 for a past session and print sample `location`/`car_data`/`intervals` rows; load a FastF1 session with telemetry + weather; hit Jolpica; download the Kaggle datasets (or print manual instructions). Record one full historical race into `data/fixtures/` for replay. ✅ Done when one command prints a data-availability report and the fixture exists. Then write `CLAUDE.md`.

**Phase 1 — Replay pipeline + Leaderboard.** Event bus, replay engine (1×/2×/10×, scrub), WS server, frontend shell + status bar + live-updating leaderboard. ✅ A recorded race replays end-to-end with correct positions, gaps, tires, and flags.

**Phase 2 — Live Track Map.** Track outline from position trace, interpolated team-colored markers, click-to-select, flag tinting. ✅ Smooth 60 fps motion during replay; selecting a car syncs with the leaderboard.

**Phase 3 — Models + Car Detail panel.** Training-set builder, Models A/B/C + fuel estimator, backtest scorecard, prediction messages on the bus, full Car Detail panel with tagged fields. ✅ Backtest report generated; panel shows live-updating predictions during replay; SC events visibly shift predicted finishes.

**Phase 4 — Track Detail + 3D.** Track asset pipeline for 3+ circuits, Three.js viewer with flyover, winners/records/live-conditions panel. ✅ 3D view recognizably matches the real circuit, including elevation (e.g., Spa's Eau Rouge clearly climbs).

**Phase 5 — Live mode + polish.** OpenF1 authenticated live client behind `OPENF1_TOKEN` (MQTT/WSS preferred, REST-polling fallback), delay indicator, error/reconnect handling, empty states, README with screenshots + a 2-minute demo script. ✅ App runs in live mode during a session when a token exists, and replay mode is indistinguishable in features.

Suggested replay fixtures: one chaotic race (red flag + multiple SCs) and one clean race, so demos can show both prediction regimes.

---

## 9. Non-goals (v1)

User accounts/auth; betting or odds framing; mobile native apps; multi-sport UI; historical-season browsing beyond what Track Detail needs; pixel-perfect official-broadcast cloning; any use of F1/team logos or marks.

## 10. Definition of done

A reviewer with no setup beyond `make dev` (or two commands documented in the README) can: pick a recorded race, watch cars move smoothly on the circuit, click Hamilton and see speed/tires/fuel-est/predicted finish updating, watch a safety car visibly change the predictions, open the 3D track flyover with past winners and live conditions — and the backtest scorecard in `ml/reports/` justifies trusting the numbers.

**Working agreement for Claude Code:** state assumptions explicitly instead of asking when blocked on small decisions; stop and ask before adding paid services, new heavy dependencies, or schema changes to the WS protocol; keep commits scoped per phase.
