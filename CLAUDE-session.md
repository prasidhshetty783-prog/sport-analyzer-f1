# CLAUDE-session.md — working context for AI assistants & new contributors

This file is the **onboarding brief** for anyone (human or AI coding agent)
picking up this repository mid-flight. The [`README`](README.md) explains what
the app *is*; this file explains how it is *built*, what must never be broken,
and where the sharp edges are.

Read this once before your first change. If a rule here conflicts with something
you infer from the code, the rule wins — say so instead of silently working
around it.

---

## 1. One-paragraph summary

**Sport Analyzer — F1 Live** is a real-time Formula 1 race dashboard: a 2D track
map with cars interpolated at 60 fps, a live leaderboard, per-car telemetry, a
3D Track Detail view, and machine-learning predictions (tyre degradation,
safety-car likelihood, Monte-Carlo finishing position, fuel load). It runs in two
interchangeable modes — **Replay** (recorded race fixtures, works offline) and
**Live** (OpenF1 real-time feed, requires a paid token). Python 3.10+/FastAPI on
the back end, React 18 + TypeScript + Vite + Three.js on the front, no database.

All five build phases are complete. Work now is refinement, not construction.

---

## 2. Hard constraints — never silently violate

1. **No official F1 API.** Data comes from community sources only: **OpenF1**
   (live + 2023→, REST/MQTT), **FastF1** (deep telemetry for training),
   **Jolpica** (Ergast successor, results back to 1950), and a public Kaggle
   1950–2024 results dump used for model priors.
2. **Live is token-gated.** OpenF1 historical data is free; the real-time feed
   needs a paid token. Every live feature sits behind `OPENF1_TOKEN`, and with no
   token the app must degrade cleanly to **replay-only** — the `● LIVE SESSION`
   entry is not even offered by `/api/sessions`.
3. **Every UI field is tagged `LIVE` / `EST` / `AI`.** Fuel is estimated, tyre
   life is a model output. A prediction is never presented as telemetry. "Real
   time" means broadcast-synced (seconds behind), and the delay is shown.
4. **Replay is first-class.** Recorded fixtures re-emit through the *same*
   internal event bus as live ingest, with a full transport (1×/2×/10×, scrub).
   Every feature must work identically in both modes — if you add something that
   only works live, it is not done.
5. **Respect the rate limits.** OpenF1's free tier is roughly 3 req/s.
   `scripts/_common.py` throttles; bulk pulls are chunked by date window and
   cached to disk. Sustained pulls will hit a 429 quota wall — honour
   `Retry-After` rather than hammering.
6. **No F1 or team logos, no official fonts, no betting features.** Team colours
   come from the data feed (`team_colour`), never from a hardcoded brand list.

---

## 3. How data flows

```text
OpenF1 live ───────────────┐
ingest/live_client.py      ├─▶ core/event_bus.py ─▶ state/race_state.py ─▶ models/ ─▶ api/ws.py ─▶ frontend
ingest/replay_engine.py ───┘   (one bus; live and replay are interchangeable producers)
(recorded fixtures)
```

The single most important architectural idea: **`LiveClient` and `ReplayEngine`
are swappable producers on one bus.** They both normalise into the same event
vocabulary, both drive `RaceState`, and both feed the same `Predictor`. Anything
downstream of the bus should not know or care which one is running.

Live ingest chain: `ingest/live_source.py` (`OpenF1RestSource` poller behind the
token; `OpenF1MqttSource` is a stub for a lower-latency transport later) →
`ingest/openf1_normalize.py` (raw OpenF1 rows → the shared fixture event
vocabulary) → `ingest/live_client.py` (`LiveClient`: computes the real broadcast
`delay_s`, handles GPS-gap retirement, reconnect/backoff, and the empty
"No live session" state).

---

## 4. Repo layout

```text
backend/
  api/       FastAPI app surface, WS server, schema.py (protocol source of truth), gen_types.py
  core/      event_bus.py — the single internal bus
  ingest/    replay_engine.py, live_source.py, live_client.py, openf1_normalize.py,
             track_outline.py (GPS trace → circuit outline + elevation), georef.py
  models/    fuel.py, tire.py, hazard.py, montecarlo.py, predictor.py, priors.py
  state/     race_state.py — the authoritative in-memory race model
  tests/     pytest suite (incl. real-fixture integration + live-mode tests)
frontend/
  src/features/   shell, leaderboard, track-map (2D canvas), track-3d (Three.js), car-panel
  src/lib/ws/     generated TypeScript protocol types
  src/store/      Zustand state
  src/styles/     tokens.css — semantic design tokens
ml/          build_training_set.py, build_priors.py, train_*.py, backtest.py; reports in ml/reports/
scripts/     data spikes + host-only fetchers (record_fixture, record_all, fetch_*, data_report)
docs/        AI_MODEL_REPORT.md — model methodology, per-race backtest tables
data/        gitignored — fastf1_cache/, fixtures/, circuit_geo/, circuit_facts/, processed/
models/artifacts/  gitignored — serialized/distilled model coefficients
```

### The WebSocket protocol has exactly one source of truth

`backend/api/schema.py` defines the protocol as Pydantic models. TypeScript types
are **generated**, never hand-written:

```bash
python -m backend.api.gen_types      # → frontend/src/lib/ws/types.ts
```

Message kinds: `positions`, `leaderboard`, `car_telemetry`, `prediction`,
`race_control`, `weather`, `session`. **Editing this schema is a breaking change
— stop and ask before doing it.** Both phases 3 and 5 shipped major features with
zero schema changes; that is the standard to hold.

### Fixture format

`data/fixtures/<year>_<country>_race/` — one Parquet per stream (`location`,
`car_data`, `position`, `intervals`, `laps`, `stints`, `pit`, `weather`,
`race_control`, `drivers`) plus `meta.json` carrying `fixture_version: 1`.
Default demo race: **2024 Canada** (safety car + rain gives good variance).

---

## 5. Prediction models

Trained offline in `ml/` (XGBoost/LightGBM), then **distilled to lightweight
coefficients** served in-process. Each model loads `models/artifacts/priors.json`
if present and otherwise falls back to principled priors in `backend/models/priors.py`
— so **the app runs with no training step**. Do not add a mandatory training
prerequisite to the run path.

| Model | File | What it does |
| --- | --- | --- |
| A — tyre | `models/tire.py` | Degradation curve, "laps to the cliff" |
| B — finish | `models/montecarlo.py` | Vectorised NumPy race sim (~250 ms / 2k sims); SC restarts compress the field and visibly shift the odds |
| C — hazard | `models/hazard.py` | Per-circuit safety-car likelihood |
| Fuel | `models/fuel.py` | Deterministic estimate, tagged EST |

`models/predictor.py` assembles a `PredictionMsg` per car. It is refreshed every
30 s of session time and immediately on a flag or pit event, and is included in
the snapshot sent to newly-connected clients.

Current measured performance (see [`docs/AI_MODEL_REPORT.md`](docs/AI_MODEL_REPORT.md)
for methodology and per-race tables): finish-position **MAE ≈ 1.9 places**,
**top-3 hit rate ≈ 0.75**, safety-car model **+2.3% Brier skill** over a no-skill
baseline. Be honest about this — the model is roughly level with a persistence
baseline on calm races; its edge is in chaotic races and in the calibrated
probabilities, not in beating "freeze the current order" everywhere.

`python -m ml.backtest` regenerates the scorecard into `ml/reports/`.

---

## 6. Front-end conventions

- **Semantic CSS variables only**, defined in `src/styles/tokens.css`. 8-pt
  spacing scale. No inline hex — team colours from the data feed are the single
  exception.
- **Design language: premium motorsport.** F1 racing-red accent
  (`--color-accent`: `#e10600` light / `#ff2630` dark) on a carbon canvas (dark
  is the hero theme), with a crisp paddock-white light theme. Rounded cards
  (14–20px radius), hairline-lit edges, red CTA/active states.
- **Flag colours are deliberately distinct from the brand red**
  (`--color-flag-red` ≠ `--color-accent`) so a real red flag never reads as "just
  an accent". Do not collapse these.
- **Type:** Archivo (sans) + JetBrains Mono (timing), loaded via a Google Fonts
  `<link>` in `index.html` — no font npm dependency.
- **Theming:** dark theme under `[data-theme="dark"]`, toggled in the status bar
  and persisted to `localStorage`. The canvas map and the 3D scene re-read CSS
  variables on theme change — if you add a themed colour to either, wire it into
  that re-read.
- **Responsive:** the shell grid trims on laptops/tablets; on phones the
  leaderboard becomes a slide-in drawer, the Car Detail panel docks as a bottom
  sheet, the status bar compacts, and the 3D overlay controls shrink to
  icon-only.
- **No new heavy dependencies.** The charts (degradation sparkline, finish
  distribution) and the whole 2D map are hand-rolled SVG/Canvas on purpose.

---

## 7. Commands

```bash
# setup
pip install -r requirements.txt
cd frontend && npm install

# dev
python -m uvicorn backend.app:app --reload --port 8000   # backend  → :8000
cd frontend && npm run dev                                # frontend → :5173

# checks
python -m pytest backend/tests -q      # backend suite (needs the Canada fixture)
cd frontend && npx tsc --noEmit        # front-end type check
python -m backend.api.gen_types        # regenerate TS types after a schema edit
python -m ml.backtest                  # finish-prediction scorecard → ml/reports/
```

### Host-only operations

Anything that reaches out to an F1 data domain must run on a normal developer
machine with open network access — sandboxed/CI agent environments commonly
block `api.openf1.org`, `api.jolpi.ca`, `livetiming.formula1.com` and
`kaggle.com` via an egress allowlist. In-sandbox tests mock `openf1_get` instead.

```bash
python scripts/record_fixture.py                      # record ONE race → data/fixtures/
python scripts/record_all.py                          # record ALL races (2023→, resumable, skips existing)
python scripts/record_all.py --plan-only              # dry run
python scripts/fetch_all_circuits.py                  # map tiles + corner numbers for every circuit
python scripts/fetch_all_circuits.py --skip-corners   # tiles only (no FastF1, no rate limit)
python scripts/data_report.py                         # data-availability scorecard
python -m ml.build_training_set                       # training data pull
```

`record_all` skips fixtures already on disk, so it is safe to interrupt and
re-run. See [`RUN_GUIDE.md`](RUN_GUIDE.md) for the full step-by-step, including
enabling Live mode and retraining the models.

---

## 8. Known heuristics and rough edges

Be honest about these in the UI and in commit messages — several are marked
HEURISTIC in the code for a reason.

- **3D buildings are inferred from map-tile colour, not real footprints.** They
  are decorative massing. Bahrain in particular classifies poorly (desert reads
  as built-up).
- **Water depth, tunnel arch height and drone speed are hand-tuned constants** in
  the Three.js scene, not derived from data.
- **Tunnel detection** works by finding XZ self-intersections with a vertical gap
  (e.g. Suzuka's crossover, Monaco's tunnel). It will miss unusual geometry.
- **Georeferencing** fits real-world tiles to the telemetry outline with a
  Procrustes fit plus a circular shift over flips/direction/start-offset. Canada
  lands at roughly 7 m residual; other circuits vary.
- **Corner numbers require a host-side fetch** (`scripts/fetch_circuit_info.py`).
  They are absent, not wrong, if that never ran.
- **OpenF1 data quirks** — all handled in code, keep handling them: a `404` means
  an empty result set rather than an error; `intervals.gap_to_leader` mixes
  floats with the string `'+1 LAP'`; `laps.segments_*` are list columns (sanitize
  before Parquet, dedupe on hashable columns only); retired or garaged cars emit
  exact `(0,0,0)` location rows (filtered at load; the map hides a car 15 s after
  its data ends). Replay opens at the grid (`race_start_s − 15`), not at the
  first data row.
- The **MQTT live transport is a stub.** `make_live_source()` is the hook for
  swapping it in when lower latency is wanted.

---

## 9. Working agreement

- **State assumptions instead of asking on small decisions.** Make the call,
  write down what you assumed.
- **Stop and ask** before: paid services, new heavy dependencies, or WebSocket
  protocol schema changes.
- **Keep commits scoped.** One coherent change per commit.
- **Run the checks before you commit** — `pytest backend/tests -q` and
  `npx tsc --noEmit`. Do not commit a red suite.
- **Visual QA after every UI change.** Build it, screenshot it, look at it
  critically, and iterate until it actually looks good. A change that type-checks
  but looks broken is not finished.
- **Data belongs in `data/`, artifacts in `models/artifacts/`** — both are
  gitignored. Never commit fixtures, caches, video, or the large 3D source
  assets; GitHub's hard file limit is 100 MB and these blow past it.

---

*Unofficial, fan-built, educational project. Not affiliated with Formula 1.
Code is [MIT](LICENSE); F1 data remains subject to its providers' terms.*
