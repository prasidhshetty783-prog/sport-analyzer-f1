# Sport Analyzer — Run & Test Guide

Everything below runs on your **host machine** (Windows). The data + AI-training
steps *must* run on the host — the Cowork sandbox blocks the F1 data domains.

> **The app now has two pages** (top of the screen): **Replay** for past races and
> **Live** for a race happening right now. Replay works with the fixtures you
> already have. Live needs a paid OpenF1 token (Step 4).

---

## 1. One-time setup

Run once (or after pulling new dependencies). **No new dependencies were added for
live mode** — if you set the project up before, you're already good.

```
pip install -r requirements.txt          # backend (Python 3.10+)
cd frontend && npm install                # frontend, then: cd ..
```

You already have ~76 recorded fixtures in `data/fixtures/`, so the **Replay page
runs immediately** with no data step.

---

## 2. Start the app (two terminals)

**Terminal A — backend:**
```
python -m uvicorn backend.app:app --reload --port 8000
```

**Terminal B — frontend:**
```
cd frontend
npm run dev
```

Open the URL Vite prints (default **http://localhost:5173**). Vite proxies
`/api` and `/ws` to the backend on :8000.

> After pulling these changes: **restart uvicorn**, then **hard-refresh** the
> browser (**Ctrl+Shift+R**) so the new two-page UI loads.

---

## 3. Using the two pages

At the very top you'll see two tabs: **Replay** and **Live**.

### ▦ Replay page (past races)
1. Use the **Year** dropdown, then the **Grand Prix** dropdown, to pick a race.
2. Press **▶ play** (or **2× / 10×**) and drag the **scrub bar** to move through
   the race.
3. **Click any car** on the map (or a leaderboard row) to open the Car Detail
   panel with telemetry + the AI tyre / fuel / finish predictions.
   Every field is tagged **LIVE** (from data), **EST** (estimated), or **AI**
   (model output) — predictions are never shown as if they were real telemetry.

### ● Live page (a race happening now)
- The Live tab is **always there**. What it shows depends on your setup:
  - **No token set** → a friendly screen telling you live is off and how to turn
    it on. (Replay still works fully.)
  - **Token set, but no race live right now** → a "Waiting for a live session…"
    screen. Leave it open; it fills in automatically when a race goes green.
  - **A race is live** → the full dashboard, exactly like Replay, but driven by
    the real feed. You'll see a red **● LIVE** badge and a **`broadcast +Ns`**
    delay (live data is always a few seconds behind the world feed — that's
    normal and honest). You can **freeze/resume** but not scrub or fast-forward a
    live broadcast.

To enable Live, do Step 4.

---

## 4. Turn on Live mode (paid OpenF1 token)

Live timing needs a **paid OpenF1 real-time token**. Historical/replay data is
free and needs nothing.

1. Copy `.env.example` to `.env` (in the project root) if you haven't already.
2. Set your token:
   ```
   OPENF1_TOKEN=your-token-here
   # optional, default is rest:
   OPENF1_TRANSPORT=rest
   ```
3. **Restart uvicorn.** A **● LIVE SESSION** now exists; click the **Live** tab.

If a race is on, the Live page connects within a second or two. If not, you'll
see the waiting screen until a session starts. (`OPENF1_TRANSPORT=mqtt` is a
documented stub for a future lower-latency transport — leave it on `rest`.)

> Without a token the app **stays replay-only** — the Live tab just shows the
> "live is off" screen. Nothing breaks.

---

## 5. (Optional, host-only) Refresh data & update the AI models

The app ships with **working built-in AI priors**, so it predicts out of the box
with **no training step**. These commands *re-train / sharpen* the models with
real data. They hit OpenF1 / FastF1 / Kaggle, so run them on the **host**. All are
resumable (cached to disk).

### 5a. More races to replay
```
python scripts/record_fixture.py --year 2024 --country Canada   # one race
python scripts/record_all.py                                     # every 2023-> race
```

### 5b. Real map tiles + corner numbers (nicer track view)
```
python scripts/fetch_all_circuits.py                 # tiles + corners
python scripts/fetch_circuit_facts.py                # winners / lap records (Track Detail)
```

### 5c. Update the AI models (the prediction engine)
Run these **in order**. Each step writes into `models/artifacts/priors.json`,
which the backend loads on startup.

```
# 1. Build the training table from FastF1 telemetry (2018->; ~500 calls/hr cap, resumable)
python -m ml.build_training_set        # -> data/processed/stints.parquet

# 2. Long-history priors from the Kaggle results dump (finish / DNF / overtaking / pit-loss)
#    First get the dataset (one time):
#    kaggle datasets download -d rohanrao/formula-1-world-championship-1950-2020 -p data/kaggle --unzip
python -m ml.build_priors              # -> priors.json (priors block)

# 3. Train the served models (distilled into priors.json)
python -m ml.train_tire                # tyre-degradation (Model A)
python -m ml.train_hazard              # per-circuit safety-car rate (Model C)
python -m ml.train_finish_baseline     # finish-position baseline (Model B support)
python -m ml.calibrate_hazard          # calibrate SC probabilities (Brier check)

# 4. Score the result (sanity check — runs anywhere, no network)
python -m ml.backtest                  # -> ml/reports/backtest.md
```

**Then restart uvicorn** so the new `models/artifacts/priors.json` is picked up.
Both Replay and Live use the same refreshed models automatically.

> The models are served **in-process** — there's no separate model server. If you
> skip this whole step, the app still predicts using the shipped heuristic priors;
> training just makes the numbers sharper.

---

## 6. Run the tests (sanity check)

```
python -m pytest backend/tests -q          # backend incl. live-mode tests (needs the Canada fixture)
cd frontend && npx tsc --noEmit            # frontend type-check
python -m backend.api.gen_types            # only needed if you edit the WS schema
```

Live mode added `backend/tests/test_live.py` (20 tests). One older Monte-Carlo
test (`test_mc_safety_car_shifts_finish`) can fail depending on your NumPy build
— it's a known stochastic/calibration quirk, unrelated to live mode.

---

## 7. Troubleshooting

- **Live tab says "Live timing is off"** → no `OPENF1_TOKEN`. Add it to `.env`
  and restart uvicorn (Step 4). This is expected without a token.
- **Live tab stuck on "Waiting for a live session…"** → no F1 session is live
  right now (correct behaviour), or your token can't see one. It connects when a
  race starts.
- **`broadcast +Ns` delay looks big** → live data is broadcast-synced (a few
  seconds behind). A momentarily large number during a reconnect is normal.
- **Switched to Replay and it's blank** → pick a Year + Grand Prix; the first
  fixture loads automatically on launch.
- **Map shows a grey card, not road/satellite tiles** → that circuit has no
  `data/circuit_geo/<key>.json` yet. Run `fetch_all_circuits.py` (Step 5b).
- **Predictions look flat** → expected on shipped heuristic priors; run the
  `ml/` steps (5c) to sharpen them, then restart uvicorn.
- **Frontend can't reach backend** → start uvicorn on :8000 *before* `npm run
  dev`; hard-refresh after restarts.
```
