---
title: Commands and Run Guide
type: topic
tags: [commands, run, test, host, ml]
updated: 2026-06-19
---

# Commands & Run Guide

> Copy-paste commands. **Data/training steps are host-only** — see [[Environment Gotchas]].
> Back to [[Home]].

## Setup (once)
```
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

## Dev (two terminals)
```
python -m uvicorn backend.app:app --reload --port 8000   # terminal A (:8000)
cd frontend && npm run dev                                # terminal B (:5173)
```
Open http://localhost:5173. After **backend** edits → restart uvicorn. After
**frontend** edits → hard-refresh (Ctrl+Shift+R).

The UI has **two pages** (top tabs): **▦ Replay** (past races, free) and **●
Live**. Live needs a paid token — put `OPENF1_TOKEN=...` (and optional
`OPENF1_TRANSPORT=rest`) in `.env`, then restart uvicorn; a `● LIVE SESSION`
appears and the Live tab connects when a race is on. No token ⇒ replay-only.
Full walkthrough in `RUN_GUIDE.md`.

## Tests / type-check
```
python -m pytest backend/tests -q     # 48 tests (needs the Canada fixture)
cd frontend && npx tsc --noEmit        # frontend type-check
python -m backend.api.gen_types        # regen TS types after schema edits
```

## Backtest / model scorecards (in-sandbox OK)
```
python -m ml.backtest                  # finish-MAE scorecard -> ml/reports/backtest.md
python -m ml.calibrate_hazard          # SC hazard fit + Brier -> ml/reports/hazard_calibration.md
python -m ml.build_priors              # Kaggle priors (auto-locates CSVs) -> priors.json
```
`SA_SIMS=<n>` env caps Monte-Carlo sims for faster backtests.

## Host-only (sandbox blocks F1 domains — [[Data Sources and Constraints]])
```
python scripts/record_fixture.py                     # record ONE race -> data/fixtures/
python scripts/record_all.py                         # ALL 2023-> races (resumable, skips existing)
python scripts/record_all.py --plan-only             # list what it would pull
python scripts/fetch_all_circuits.py                 # real map tiles + corners, every circuit
python scripts/fetch_all_circuits.py --skip-corners  # tiles only (no FastF1 limit)
python scripts/fetch_circuit_facts.py                # winners/records/first-GP (Track Detail)
python -m ml.build_training_set                      # FastF1 stint table (2018->; 500/hr cap, resumable)
python -m ml.train_tire ; python -m ml.train_hazard  # train real models -> priors.json
```
**Kaggle results dump** (for [[Calibration Log|build_priors]]): authenticate first
(`kaggle.json` in `~/.kaggle/`), then
`kaggle datasets download -d rohanrao/formula-1-world-championship-1950-2020 -p data/kaggle --unzip`.

## Restart rules
After fetching circuits or training → **restart uvicorn** so caches/priors reload.

Related: [[Environment Gotchas]] · [[Calibration Log]] · [[Phase 0 - Data Access Spike]] · [[Data Sources and Constraints]]
