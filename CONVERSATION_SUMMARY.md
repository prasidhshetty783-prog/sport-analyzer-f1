# Sport Analyzer — Conversation Handoff Summary

> Paste this into a new chat to restore full context. Cumulative across all
> sessions. **Primary context store is now the Obsidian vault at `vault/`** — open
> `vault/Home.md` first (routing index → one focused note per topic, minimal
> tokens). Full spec: `BUILD_PROMPT.md`; working summary: `CLAUDE.md`; run/test:
> `RUN_GUIDE.md`.
>
> ⚠️ **Maintenance rule (standing instruction):** when project context changes,
> update the relevant `vault/` note (Phases/* or Topics/*) **and bump its
> `updated:` frontmatter** — don't just edit this file. The vault is the canonical,
> token-efficient context going forward.

---

## 0. Latest work (June 2026) — 3D refinement, F1 restyle, responsive, model calibration, Kaggle priors, context vault

Polish pass before Phase 5. All in `frontend/`; full-project `tsc --noEmit`
passes. **Visual results are host-only** (sandbox can't render Three.js / paint
CSS) — verified types + logic, not pixels.

**3D fixes (`features/track-3d/scene.ts`, `Track3D.tsx`, `track3d.css`):**
- **Surroundings.** `heightField` now carves a corridor so terrain sits just
  below the asphalt (no land poking through the ribbon) and, at over/under
  crossings, follows the LOWER deck. Water rebuilt entirely: classify on a fine
  200² grid → dilate (thin rivers become continuous ribbons, not dots) → box-blur
  (smooth shorelines) → carve a flat basin → one reflective sheet with a blurred
  alpha mask (`buildWater`/`boxBlur`/`buildWaterPlane`/`waterSample`,
  `recomputeGroundHeights`). Fixes the blocky "Minecraft" edges.
- **Tunnels.** New `buildTunnels()`/`buildTunnelAt()` + module `segInt()` detect
  self-crossings (XZ intersection + vertical gap, e.g. Suzuka) and build an arched
  tunnel with portal rims over the lower road so cars pass through, not into land.
- **Flyover → drone.** Replaced the auto-glide with a free-fly controller:
  **W/A/S/D** translate, **mouse ←→** yaw, **mouse ↑↓** altitude, via pointer lock
  (`enableFly`/`disableFly`/`onFlyKey`/`onFlyMouse`/`updateFly`, `isPointerLocked`).
  On-screen hint in `Track3D.tsx`; Esc releases capture before closing.

**F1 restyle (premium motorsport):**
- `styles/tokens.css` reworked: **F1 racing-red** accent (`#e10600` light /
  `#ff2630` dark) on a **carbon** dark theme (the hero look) + **paddock-white**
  light theme; refined shadows, `--hairline-top`, `--ring-focus`, `--speed-line`.
  Flag colours kept distinct from the brand red.
- Fonts: **Archivo** + **JetBrains Mono** via Google Fonts `<link>` in
  `index.html`; removed `@fontsource/titillium-web` imports from `main.tsx`
  (no font npm dep). `global.css`: carbon-weave backdrop on dark, red selection,
  focus-visible ring, scrollbar polish. Status bar gets a red "timing-tower" tick.

**Responsive (`shell.css` + `App.tsx`/`StatusBar.tsx`/`Leaderboard.tsx`):**
- Shell grid adapts (rail trims at ≤1200/1000px). At ≤760px the leaderboard
  becomes a **slide-in drawer** — `☰` (`.sb-nav`) in the status bar toggles
  `shell[data-nav]`, with a tap-out `.shell-backdrop`; auto-closes on driver
  select (`Leaderboard onSelect`). Car Detail docks as a **bottom sheet** at
  ≤540px; status bar compacts/wraps; 3D overlay panel/controls shrink to icon-only.

**Follow-up tweaks (same session):**
- Responsive tightened: leaderboard drops to a **compact 6-col grid ≤1100px**
  (hides LAST + PIT) and the **drawer now kicks in ≤860px** (small tablets), so
  intermediate widths are no longer cramped.
- **Flyover yaw fixed** — mouse-right now turns right (`onFlyMouse` sign).
- **Two-dropdown race filter** — Year + Grand Prix (cascading), parsed client-side
  in `StatusBar.tsx` (`parseSession`/`RaceFilter`); no schema change.
- **Flag-change toast** — `FlagToast.tsx` (rendered in `App.tsx`) replaces the
  always-on flag chip; fires only on flag transitions, auto-dismisses (~4.5s).
- **Car Detail "Car" tab** — `CarSchematic` in `CarPanel.tsx`: F1-TV-style top-down
  schematic, **real data only** (speed/gear/throttle/brake/DRS LIVE, tyre set LIVE,
  tyre-life AI, fuel EST). No tyre/brake temps or ERS — not in the feed (and rpm
  isn't either, so no shift lights). Panel is now tabbed (Overview / Car).
- **Map: track-under-water fixed** — `buildWater` zeroes the water field inside the
  track corridor so the road is never submerged (Monaco). Bahrain/desert
  environment accuracy is tile-heuristic and host-tunable, not fixed blind.

**Data range (host recording):** replay fixtures are **OpenF1 2023→ only**
(`record_all.py` defaults to 2023..current; OpenF1 has no position/`car_data`
before 2023, so older races CANNOT be replayed). Pre-2023 only feeds **training**:
FastF1 telemetry 2018→ (`ml/build_training_set.py --seasons …`) + Kaggle/Jolpica
results 1950→ — lowers MAE, does not create replayable races.

**Model calibration + Kaggle priors (latest, full detail in `vault/Topics/Calibration Log.md`):**
- **Model B (Monte-Carlo finish)** — `backend/models/montecarlo.py`: per-lap noise
  σ 0.35→0.12, `POS_SPREAD`↑, and `exp` blended toward the live running order
  (`ANCHOR_MIN`/`ANCHOR_MAX`, by race-fraction). `SA_SIMS` env caps sims for
  backtests. Mean finish-MAE **2.96→~1.86** (15-race sample; ≈ persistence, was
  clearly trailing). Honest: on sticky races the point-MAE ceiling ≈ persistence;
  the sim's value is the distribution + SC reactivity.
- **Model C (SC hazard)** — new `ml/calibrate_hazard.py` fits from fixtures'
  `race_control` (in-sandbox): per-circuit P(≥1 SC) empirical-Bayes shrunk + lap-1
  ×8 / rain ×1.25 / mean-scale ×0.711 → `priors.json["hazard"]`; `hazard.py` reads
  them. **Brier 0.0681 vs 0.0696 no-skill (+2.3%)**, well-calibrated. Scorecard
  `ml/reports/hazard_calibration.md`.
- **Kaggle priors (1950–2024 dump)** — rewrote `ml/build_priors.py`: auto-locates
  CSVs + an **Ergast→OpenF1 circuit crosswalk** (fixes the key-mismatch that had
  bypassed per-circuit priors). Field-merges overtaking_difficulty + pit_loss_s
  (23 circuits) + global **dnf_rate 0.171** into `priors.json` (preserving
  sc_rate/hazard); `predictor.py` now feeds Model B the calibrated DNF. MAE flat
  (~1.85) but the priors now actually apply and are realistic — value is
  correctness, not point-MAE.
- **Recurring bug class — circuit keys:** runtime uses OpenF1 `circuit_short_name`
  ("Monte Carlo"); the shipped `CIRCUITS` dict + Ergast `circuitRef` ("monaco")
  mismatch and silently get bypassed. **Always key artifact priors by
  `circuit_short_name`.**

**Context vault (NEW) — `vault/`:** an Obsidian knowledge base, 16 fully-wikilinked
notes (`Home` routing index + `About Me` + `Phases/0–5` + `Topics/{Architecture,
Data Sources and Constraints, Environment Gotchas, Prediction Models,
Calibration Log, Design System, Commands and Run Guide}` + `Glossary`). It is the
**primary context store** — open `vault/Home.md` first and keep its notes updated.

**Still host-only / pending:** Phase 5 **live mode** (`OPENF1_TOKEN`) is the main
remaining build. Likely 3D visual tuning once rendered: water depth/colour
(`waterFloor −1.3`), tunnel arch height/`TUNNEL_SPAN`, drone `speed`/mouse
sensitivity, exact red shade. Archivo loads from Google Fonts at runtime
(system-sans fallback offline).

---

## 1. What the project is

**Sport Analyzer: F1 Live** — a real-time F1 race dashboard. Replays recorded
races through an event bus with a live 2D track map, per-car telemetry, ML-style
predictions (tire life, fuel, pit window, predicted finish), and a 3D Track
Detail view. Stack: Python 3.10+ / FastAPI / NumPy backend; React 18 + TypeScript
+ Vite + Three.js frontend; WebSocket protocol. No database — in-memory state +
Parquet/JSON file caches.

Working dir: `D:\Claude Code Projects\Sports Analyzer`.

## 2. CRITICAL environment gotchas (these bite repeatedly)

1. **The Cowork/Claude sandbox blocks all F1 data domains** (OpenF1, FastF1,
   Jolpica, Kaggle, GitHub-raw) AND general web downloads. Every data-fetching /
   training / model-download script must run on the **host** (the user's Windows
   machine). In-sandbox we test with the already-recorded fixtures or mocks.
2. **The synced mount serves STALE/TRUNCATED content for files Claude just
   edited** (attr-cache). The host file written by Write/Edit is ALWAYS correct;
   only the sandbox's bash re-read is stale/garbled. Re-confirmed June 2026: an
   edited file reads **truncated at its old cached byte size** (grep sees later
   tokens but `cat`/`wc`/`cp` stop early; `ls -l` shows the pre-session mtime). A
   **brand-new** path reads fresh, though. To verify: Read the edited `.ts/.tsx`
   (Read tool is accurate) → Write fresh copies to a NEW path (`.verify/` or
   `/tmp`) → reconstruct the project in `/tmp` (unedited files copy fresh from the
   mount, overwrite edited ones with fresh copies, symlink `node_modules`) → run
   `node_modules/.bin/tsc --noEmit`. Never trust a bash re-read of a just-edited file.
3. **The sandbox filesystem (`/tmp`) and installed deps are wiped between turns** —
   rebuild the verify env (`npm install` three, pip deps) each verification pass.
4. Deletions from the sandbox need `mcp__cowork__allow_cowork_file_delete`.

## 3. Phase status

- ✅ Phase 0 — data-access spike + fixture recorder
- ✅ Phase 1 — event bus, replay engine (1×/2×/10×, scrub), WS server, shell + leaderboard
- ✅ Phase 2 — live 2D track map (telemetry outline, CARTO tiles, corners)
- ✅ Phase 3 — prediction engine + Car Detail panel
- ✅ **Phase 4 — Track Detail + 3D** (built earlier; **refined latest session** —
  see §0: terrain carve, smooth water, tunnels, free-fly drone)
- 🟡 Phase 5 — live mode (`OPENF1_TOKEN`) **not started**; **polish done latest
  session** (§0): F1-red + carbon restyle, Archivo, full responsive layout

## 4. Architecture / layout

```
backend/  api/ (schema.py, rest.py, ws.py, gen_types.py)  core/  ingest/  models/  state/  tests/
frontend/ src/features/{track-map, car-panel, track-3d, leaderboard, shell}/  src/lib/ws/  src/store/  src/styles/
ml/       build_training_set.py, train_*.py, build_priors.py, backtest.py, reports/
scripts/  record_*.py, fetch_*.py, check_*.py, data_report.py, _common.py
data/     (gitignored) fixtures/ circuit_geo/ circuit_info/ circuit_facts/ kaggle/ fastf1_cache/ processed/
models/artifacts/  (gitignored) priors.json + serialized models
```

- **WS protocol** (`backend/api/schema.py`, protocol v1): typed JSON, one schema →
  Pydantic + generated TS (`python -m backend.api.gen_types` → `frontend/src/lib/ws/types.ts`).
  Kinds: positions, leaderboard, car_telemetry, prediction, race_control, weather,
  session. **Changing this schema requires stop-and-ask** (working agreement).
- **REST** (`backend/api/rest.py`): `/api/health`, `/api/sessions`,
  `/api/track/{id}` (2D outline + elevation + corners + geo),
  `/api/drivers/{id}` (roster + OpenF1 headshot_url), `/api/circuit/{id}` (Track
  Detail facts). All cached in-process.
- **Frontend store** (`src/store/raceStore.ts`): zustand; WS messages → state.
  Slices include `driverMeta`, `selectedDrv`, `view3D`/`setView3D`.
- ~76 recorded fixtures in `data/fixtures/` (2023→); default demo: 2024 Canada
  (SC + rain). Australia/Austria good for 3D (geo + elevation).

## 5. Phase 3 recap (predictions)

`backend/models/`: fuel.py (EST), tire.py (Model A deg), hazard.py (Model C SC
rate), montecarlo.py (Model B finish sim — SC restart shifts win prob),
predictor.py (assembles `PredictionMsg`, has `dnf_prediction()`). All degrade to
principled priors (`priors.py`) so the app runs with NO training step in-sandbox;
`models/artifacts/priors.json` overrides when host training is run. Car Detail
panel tags every field LIVE/EST/AI.

## 6. Phase 4 — Track Detail + 3D (built across this session)

**2D map upgrades (`frontend/src/features/track-map/`):**
- `engine.ts` — camera **zoom + follow-cam**: `camZoom` 1–5, smooth north-up pan
  following the selected driver, free drag-pan when none; zoom toward cursor; track
  ribbon scales, markers grow gently (`markerScale`). **Tile fix:** parent-tile
  fallback (`getTile`, `MapEngine.loaded`) + prefetch margin so surroundings never
  go blank while panning. Enhanced corners (apex dot + badge) + S1/S2/S3 sector
  ticks (stylized even-thirds, not official timing boundaries).
- `TrackMap.tsx` — zoom +/−/reset buttons + level readout, wheel-zoom, drag-pan
  (click-vs-drag detection), follow indicator; **"Track info" button opens 3D**.

**Driver images (`car-panel/CarPanel.tsx`):** `cp-photo` header at top — OpenF1
headshot (loaded client-side by the browser from `/api/drivers`) with a team-
coloured initials-avatar fallback (`DriverAvatar`), number, name, team, position.

**3D Track Detail (`frontend/src/features/track-3d/`):**
- `scene.ts` (`Scene3D`, Three.js):
  - **Elevation-aware track ribbon** from `asset.points` + `asset.elevation`
    (GPS z; see backend below). VEXAG=1.8 vertical exaggeration.
  - **Terrain that follows the relief** — 96×96 heightfielded ground (`heightField()`
    = IDW over the centerline; hugs the track nearby, smooth average far) so the
    track never "flies". Trees/water/buildings sit on the terrain.
  - **Georeferenced ground texture** = the SAME CARTO map as 2D (Voyager raster),
    aligned by reusing the 2D `assetToMerc` math; anisotropic + mipmapped + 3072²
    canvas (crisp, not pixelated).
  - **Environment from the tiles:** instanced rounded color-varied **trees**, a
    single merged **uniform water sheet** (was droplet-circles), and instanced
    **building boxes** (HEURISTIC from tile colour — NOT real footprints).
  - **Procedural F1 cars** (`buildF1Car`) — open-wheel body/wings/halo/4 rolling
    wheels, team-coloured, `CAR_SCALE=0.62`. Optional real model: drop a
    web-optimized `frontend/public/models/f1.glb` and `loadCarModel()` (GLTFLoader)
    uses team-tinted clones (procedural fallback). Cars driven by the same WS
    positions + replay clock as the 2D map (reuse `track-map/buffer.ts`).
  - **3D corner-number** sprites; start/finish gate; lights + fog; theme-aware.
  - **Camera modes:** Orbit / Chase (selected car) / **Flyover** = smooth free
    "drone" (orbit pivot eases along the lap with damping; user keeps full
    rotate/zoom/pan).
- `Track3D.tsx` overlay — fetches asset + facts; RAF loop; Orbit/Chase/Flyover
  buttons with inline SVG icons (`ModeIcon`: pan/car/drone); **Track Detail panel**
  (live conditions from weather, circuit stats, past winners, lap record, first GP;
  collapsible sections); **elevation-profile strip** (SVG from `asset.elevation`).
  Store `view3D`/`setView3D`; `App.tsx` renders `<Track3D/>` when open. Esc closes.

**Backend for Phase 4:**
- `backend/ingest/track_outline.py` — adds `elevation[]` per outline point
  (smoothed/resampled GPS z, relative to min; `_smooth_closed_1d`,
  `_resample_closed(extra=)`). Real relief: Austria 4.7%, Monaco 3.7% of span.
- `GET /api/circuit/{id}` — computed laps + lap length + race distance (from the
  georeferenced outline; Albert Park came out 5.18 km / 305.7 km, ~1% of real) +
  records merged from `data/circuit_facts/<key>.json` when present (else null →
  panel shows dashes).
- `scripts/fetch_circuit_facts.py` (host) — Jolpica → winners / first-GP /
  fastest-lap cache per circuit (best-effort country/name matching).

**Dependency:** `three` + `@types/three` added to `frontend/package.json` — **user
must run `npm install` in `frontend/`** (done once; flagged + approved heavy dep).

## 7. Key bug fixes (this session)

- **Lap counter jumped to N/N after switching races** — a `laps` row with a NaT
  `date_start` produced a NaN-time `lap_start` event; the NaN poisoned
  `events.sort()` (NaN compares false → partially-ordered list), so the engine's
  bisect-based `seek()` replayed ~the whole race. Fixed in `fixture_store.py`: skip
  NaN-time lap rows + drop any non-finite-time event before sort
  (`events = [e for e in events if e[0] == e[0]]`). Needs uvicorn restart (store
  caches fixtures).
- **Map tiles blank when zoomed/following** — parent-tile fallback (above).
- **Retirement delay** shortened 18s → 12s (`RETIRE_GAP_S`). DNF cars still drop
  from the leaderboard.

## 8. Pre-Phase-4 cleanup (this session)

- Reviewed/hardened host scripts: `train_hazard.py` now detects FastF1's
  500-calls/hour limit + resumes (was silently churning); others
  (`fetch_all_circuits.py`, `build_training_set.py`, etc.) already robust.

## 9. How to run (see RUN_GUIDE.md for detail)

```
pip install -r requirements.txt
cd frontend && npm install            # includes three (required for 3D)
python -m uvicorn backend.app:app --reload --port 8000   # terminal A
cd frontend && npm run dev            # terminal B  -> http://localhost:5173
```
After backend edits: **restart uvicorn**. After frontend edits: **hard-refresh**
(Ctrl+Shift+R). 3D: click **Track info** on the map; select a car + **Chase**, or
**Flyover** to drone around the lap.

Tests: `python -m pytest backend/tests -q` (48; needs Canada fixture) ·
`cd frontend && npx tsc --noEmit`.

## 10. Still pending / host-only (sandbox blocks F1 domains)

- `python scripts/fetch_all_circuits.py` (host) → real-world map tiles + corners
  for ALL circuits (then restart uvicorn). `--skip-corners` avoids FastF1.
- `python scripts/fetch_circuit_facts.py` (host) → winners/records/first-GP for the
  3D panel (else those fields show dashes).
- `ml/build_training_set` → `ml/train_tire` / `train_hazard` (host) to train real
  models (FastF1 500/hr limit; resumable). Backtest: `python -m ml.backtest`.
- **Real F1 car model:** export the attached `.blend` to a **web-optimized `.glb`**
  (few MB, decimated) → `frontend/public/models/f1.glb` (that dir doesn't exist
  yet). The 562 MB `.blend` / 687 MB `.obj` can't be used directly (no Blender in
  sandbox, far too heavy); don't commit them.
- **Real building footprints** (vs the current heuristic blocks) would need an
  OpenStreetMap/Overpass fetch script run on the host — not yet built.

## 11. Important caveats

- **3D is not visually verifiable in-sandbox** (tsc only, no render). Things that
  may need visual tuning once loaded: terrain blend strength, building
  density/colour thresholds (Voyager palette), flyover speed, vertical
  exaggeration, and the orientation/scale of an imported `.glb`.
- **Buildings are heuristic** (classified from map-tile colour), not real shapes.
- **Honest data labeling** is a core project value: every UI field is tagged
  LIVE/EST/AI; computed/approximate values must never be presented as telemetry.
- No F1/team logos or official fonts; team colours come from data; no betting.

## 12. Working agreement

State assumptions instead of asking on small decisions. **Stop and ask** before:
paid services, new heavy dependencies, or WS protocol schema changes. Commits
scoped per phase. Tag every UI field LIVE/EST/AI. Light card UI on off-white
canvas, teal accent, soft shadows; dark theme under `[data-theme="dark"]`.
