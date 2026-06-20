# CLAUDE.md — Sport Analyzer: F1 Live

Real-time F1 race dashboard: live track map, per-car telemetry, ML predictions
(tire life, pit strategy, finish position). Full spec: `BUILD_PROMPT.md` — it is
the source of truth; this file is the working summary.

> 📓 **Context vault (canonical):** open `vault/Home.md` first — an interlinked
> Obsidian knowledge base (Phases + Topics) built to give context with minimal
> tokens. Open the one relevant note instead of re-reading every doc.
>
> 🔄 **Standing instruction — keep it current:** whenever project context changes
> (a feature, a fix, a model/calibration change, a new constraint), UPDATE the
> relevant `vault/` note (`Phases/*` or `Topics/*`) and bump its `updated:`
> frontmatter as part of the same change. The vault is the source of truth for
> context going forward; `CLAUDE.md` / `CONVERSATION_SUMMARY.md` are secondary.

## Phase status

- ✅ **Phase 0** — data-access spike: scripts in `scripts/`, availability report, fixture
  recorder (acceptance run — `data_report.py` + fixture — executes on the host machine)
- ✅ **Phase 1** — event bus, replay engine (1×/2×/10×, scrub), WS server, frontend
  shell + status bar + leaderboard. 19 tests incl. real-fixture integration
  (podium VER/NOR/RUS, SC derivation, seek). Protocol: `backend/api/schema.py`
  → `python -m backend.api.gen_types` → `frontend/src/lib/ws/types.ts`
- ✅ **Phase 2** — live track map: outline derived from fastest-lap GPS trace
  (`backend/ingest/track_outline.py` → `GET /api/track/{id}`), canvas renderer at
  60 fps (interpolated markers, trails, click-select ↔ leaderboard sync, SF line).
  Corner numbers appear if `scripts/fetch_circuit_info.py` was run on the host.
  **Map environment:** real-world tile underlay (CARTO light/dark rasters, OSM
  data) when `data/circuit_geo/<circuit_key>.json` exists — fitted to the
  telemetry outline by `backend/ingest/georef.py` (Procrustes + circular shift
  over flips/direction/start offset; Canada residual ≈ 7 m). Fetch geometry per
  circuit with `scripts/fetch_circuit_geo.py --gp <name>` (host). Render clock
  is spring-smoothed (no hard clamp); trails removed; markers are F1-TV style.
- ✅ **Phase 3** — prediction engine + Car Detail panel. `backend/models/`:
  fuel.py (deterministic EST), tire.py (Model A, heuristic + distilled-GBT priors),
  hazard.py (Model C, per-circuit SC rate), montecarlo.py (Model B, vectorised
  NumPy sim — ~250 ms/2k sims; SC restart compresses the field and visibly shifts
  the odds), predictor.py (assembles `PredictionMsg` per car). Every model loads
  `models/artifacts/priors.json` if present, else ships principled priors
  (`priors.py`) so the app runs with **no training step** in-sandbox. Wired into
  `ReplayEngine` (refresh every 30 s session-time + immediately on flag/pit; in
  snapshot for new clients). `ml/`: build_training_set.py (FastF1, host),
  build_priors.py + train_tire/hazard/finish_baseline.py (host, XGBoost/LightGBM
  → distilled coeffs), backtest.py (runs in-sandbox on fixtures → `ml/reports/`;
  Canada MAE ≈ 2.9 vs persistence 2.7, top-3 hit 0.89). Frontend:
  `features/car-panel/` right slide-in, every field tagged LIVE/EST/AI, hand-rolled
  SVG deg sparkline + finish-distribution chart (no new frontend deps). 48 backend
  tests (16 new). No WS schema change — `PredictionMsg` was already in protocol v1.
- ✅ **Phase 4** — Track Detail + 3D. `frontend/src/features/track-3d/`: Three.js
  scene (`scene.ts`) + overlay (`Track3D.tsx`). Elevation-aware track ribbon from
  `asset.points`+`asset.elevation`; heightfielded terrain that follows the relief;
  georeferenced CARTO ground texture (reuses the 2D `assetToMerc` math); instanced
  trees/buildings (buildings are HEURISTIC from tile colour, not real footprints);
  procedural F1 cars (optional `frontend/public/models/f1.glb`); 3D corner sprites;
  Track Detail panel (live conditions, circuit stats, past winners, lap record) +
  elevation-profile strip. Backend: `track_outline.py` adds `elevation[]`;
  `GET /api/circuit/{id}` (computed laps/length/distance + records from
  `data/circuit_facts/<key>.json`); `scripts/fetch_circuit_facts.py` (host).
  **Refinement pass (this session):** (a) terrain `heightField` now carves a
  corridor so land never overlaps the ribbon and follows the LOWER deck at
  crossings; (b) water rebuilt as a smooth blurred-alpha sheet over a carved
  basin (`buildWater`/`buildWaterPlane`, WGRID 200² + dilate + box-blur) — no more
  blocky shorelines, thin rivers become continuous ribbons; the **track corridor
  is zeroed out of the water field** so the road is never submerged (Monaco
  harbour-front + tunnel); (c) `buildTunnels` detects self-crossings (XZ
  intersection + vertical gap, e.g. Suzuka) and builds an arched tunnel + portals
  over the lower road; (d) **flyover is a free-fly drone** — WASD translate,
  mouse ←→ yaw (mouse-right turns right), mouse ↑↓ altitude, via pointer lock
  (replaces the old auto-glide). Still HEURISTIC / host-tunable: building+desert
  classification from tile colour (e.g. Bahrain reads poorly), water depth, arch
  height, drone speed.
- ✅ **Phase 5** — **live mode done** + polish. **Live:** OpenF1 authenticated
  REST poller (`ingest/live_source.py` `OpenF1RestSource` behind `OPENF1_TOKEN`;
  `OpenF1MqttSource` stub + `make_live_source()` hook for the lower-latency
  transport later) → `ingest/openf1_normalize.py` (raw OpenF1 rows → the shared
  fixture event vocabulary) → `ingest/live_client.py` (`LiveClient`: an
  interchangeable bus producer mirroring `ReplayEngine`; drives `RaceState` +
  `Predictor`, computes the real broadcast `delay_s`, GPS-gap retirement,
  reconnect/backoff + empty "No live session" state). `app.py` token-gates a
  synthetic `"live"` session (`/api/sessions` adds `● LIVE SESSION` only when a
  token is set; **no token ⇒ replay-only**). **No WS schema change** —
  `SessionMsg.mode`/`delay_s` already existed; `RaceState.session()` just gained
  defaulted `mode`/`delay_s` kwargs. Frontend (`StatusBar.tsx`+`shell.css`, no
  new deps): `● LIVE` picker pill, live-aware transport (no scrub/speed, just
  freeze/resume), `broadcast +Ns` delay readout, empty-state line. 20 live tests
  (`backend/tests/test_live.py`), incl. **Canada replayed-as-live → real podium**;
  the live feed itself is host-only (sandbox blocks F1 domains). **Polish pass (earlier):**
  premium F1-red + carbon restyle (see Design language below), full responsive
  layout (compact 6-col leaderboard ≤1100px, drawer ≤860px, bottom-sheet car
  panel), and UX additions — **two-dropdown race filter** (Year + Grand Prix,
  parsed client-side in `StatusBar.tsx`), **flag-change toast** (`FlagToast.tsx`
  replaces the always-on flag chip; fires only on flag transitions), and a
  **Car Detail "Car" tab** (`CarSchematic` in `CarPanel.tsx`) — an F1-TV-style
  top-down schematic showing ONLY real data (speed/gear/throttle/brake/DRS LIVE,
  tyre set LIVE, tyre-life AI, fuel EST; no tyre/brake temps or ERS — not in the
  feed).

## Hard constraints (never silently violate)

1. No official F1 API. Sources: **OpenF1** (live+2023→, REST/MQTT), **FastF1**
   (deep telemetry, training data), **Jolpica** (Ergast successor, results→1950).
2. OpenF1 historical = free/unauthenticated. **Live needs paid token** → gate all
   live features behind `OPENF1_TOKEN`; app must degrade to replay-only without it.
3. Every UI field is tagged `LIVE` / `EST` / `AI`. Fuel = estimated, tire life =
   model output — never present them as telemetry. "Real time" = broadcast-synced
   (seconds behind); show a delay indicator.
4. Replay is first-class: recorded fixtures re-emit through the same event bus as
   live ingest (1×/2×/10×, scrub). Every feature must work in both modes.
5. OpenF1 free tier ≈ 3 req/s — rate-limit (`scripts/_common.py` does this); bulk
   pulls get chunked by date windows and cached to disk.
6. No F1/team logos or official fonts; team colors come from data (`team_colour`).
   No betting features.

## Environment gotchas (important)

1. The Cowork/Claude sandbox **blocks all F1 data domains** (api.openf1.org,
   api.jolpi.ca, livetiming.formula1.com, kaggle.com) via its egress allowlist —
   verified June 2026. **All data-fetching scripts must be run on the host machine**
   (user's Windows box), not in the sandbox. In-sandbox testing uses mocked
   `openf1_get`. APIs + schemas were verified alive via the permitted fetch tool.
2. The synced mount serves **stale content** for files rewritten by Claude's file
   tools mid-session (attr-cache pins old size) and corrupts `.git` lock-file
   dances. Confirmed June 2026: a heavily-edited file reads **truncated at its
   cached byte size** in bash (grep finds later tokens but `cat`/`wc`/`cp` stop
   early), and `ls -l` shows the pre-session mtime. **The Read file-tool is
   accurate; bash re-reads of edited files are not.** A **brand-new** file (path
   never cached) reads fresh in bash. So to type-check edits: Read the edited
   `.ts/.tsx` (accurate) → Write fresh copies to a **new** path (e.g. a `.verify/`
   dir or `/tmp`), reconstruct the project in `/tmp` (unedited files copy fresh
   from the mount; overwrite the edited ones with the fresh copies; symlink
   `node_modules`), then `node_modules/.bin/tsc --noEmit`. Deleting from the
   sandbox needs `mcp__cowork__allow_cowork_file_delete`. Git operations on host only.
3. Sandbox background processes **die when their bash call ends** — long jobs
   must fit one call (or be re-entrant across calls, like the fixture recorder).
4. OpenF1 quirks (all handled in code, keep handling them): 404 = empty result
   set; sustained pulls hit a 429 quota wall (wait it out, honor Retry-After);
   `intervals.gap_to_leader` mixes floats with `'+1 LAP'`; `laps.segments_*`
   are list columns (sanitize before parquet, dedupe on hashable cols only);
   retired/garaged cars emit exact `(0,0,0)` location rows (filtered at load;
   map hides cars 15 s after their data ends). Replay opens at the grid
   (`race_start_s − 15`), not at data start.

## Layout & conventions

```
scripts/    Phase 0 spikes: check_*.py, record_fixture.py, data_report.py, _common.py
backend/    (Phase 1+) api/ core/ ingest/ models/ state/ tests/  — Python 3.10+, FastAPI
frontend/   (Phase 1+) React 18 + TS + Vite; src/features/*; tokens in src/styles/tokens.css
ml/         training + backtest scripts; reports in ml/reports/
data/       gitignored: kaggle/ fastf1_cache/ processed/ fixtures/
models/artifacts/  serialized models (gitignored)
```

- Fixtures: `data/fixtures/<year>_<country>_race/` — one Parquet per stream
  (`location`, `car_data`, `position`, `intervals`, `laps`, `stints`, `pit`,
  `weather`, `race_control`, `drivers`) + `meta.json` (`fixture_version: 1`).
  Phase 1 replay engine consumes exactly this format. Gotcha: `intervals`
  `gap_to_leader`/`interval` are stored as strings when the race has lapped
  cars (OpenF1 mixes floats with `'+1 LAP'`) — replay must parse both.
- WS protocol (Phase 1+): typed JSON, one schema file → Pydantic + TS types.
  Message kinds: `positions`, `leaderboard`, `car_telemetry`, `prediction`,
  `race_control`, `weather`, `session` (see BUILD_PROMPT §6).
- Styling: semantic CSS variables only, 8-pt spacing. No inline hex (team colors
  from data are the one exception). **Design language (June 2026 restyle):
  premium motorsport** — F1 racing-red accent (`--color-accent`: `#e10600` light /
  `#ff2630` dark) on a **carbon canvas** (dark = the hero theme) and a crisp
  **paddock-white** light theme. Rounded cards (radius 14–20px) with hairline-lit
  edges + refined shadows, red CTA/play/active states, a red "timing-tower" tick
  on the status bar, faint carbon-weave backdrop on dark. **Flag colours are kept
  semantically distinct from the brand red** (`--color-flag-red` ≠ accent) so a
  real red flag never reads as "just an accent". Type: **Archivo** (sans) +
  **JetBrains Mono** (timing), loaded via Google Fonts `<link>` in `index.html`
  (no font npm dep — the old `@fontsource/titillium-web` imports were removed from
  `main.tsx`). Dark theme under `[data-theme="dark"]` (toggle in status bar,
  persisted to localStorage); the canvas map + 3D scene re-read CSS vars on theme
  change. **Responsive:** the shell grid adapts (rail trims on laptops/tablets);
  on phones the leaderboard becomes a slide-in drawer (☰ in status bar + tap-out
  backdrop in `App.tsx`/`shell.css`, auto-closes on driver select), the Car Detail
  panel docks as a bottom sheet, the status bar compacts/wraps, and the 3D overlay
  panel/controls shrink to icon-only. **Track Detail (Phase 4) follows the user's
  Singapore track-card reference:** card with outline + sector/DRS highlights,
  corner numbers, stat tiles (first GP, laps, length, distance, lap record +
  holder), collapsible sections, elevation profile strip along the bottom.
- Models: GBTs (XGBoost/LightGBM), trained offline in `ml/`, served in-process.
  No DB in v1 — in-memory state + file caches.

## Commands

```
pip install -r requirements.txt        # backend setup
cd frontend && npm install             # frontend setup
python -m uvicorn backend.app:app --reload --port 8000   # dev backend
cd frontend && npm run dev             # dev frontend → http://localhost:5173
python -m pytest backend/tests -q     # 48 tests (needs the Canada fixture)
python -m backend.api.gen_types        # regenerate TS types after schema edits
python scripts/record_fixture.py       # record ONE race → data/fixtures/ (~few min)
python scripts/record_all.py           # record ALL races (host; 2023→, resumable, skips existing)
python scripts/record_all.py --plan-only   # list what record_all would pull
python -m ml.backtest                  # finish-prediction scorecard → ml/reports/ (all fixtures)
python scripts/fetch_all_circuits.py   # real-world map tiles + corners for EVERY circuit (host; deduped, resumable)
python scripts/fetch_all_circuits.py --skip-corners   # tiles only (no FastF1 / no rate limit)
python scripts/data_report.py          # Phase 0 acceptance scorecard
```

Recording data (record_fixture / record_all / build_training_set / train_*) only
works on the **host** — the sandbox blocks the F1 data domains. `record_all`
skips fixtures already on disk, so it's safe to interrupt and re-run.

## Working agreement

State assumptions instead of asking on small decisions. **Stop and ask** before:
paid services, new heavy dependencies, or WS protocol schema changes. Commits
scoped per phase. Default fixture race: 2024 Canada (SC + rain variance); add one
clean race later for the second demo regime.
