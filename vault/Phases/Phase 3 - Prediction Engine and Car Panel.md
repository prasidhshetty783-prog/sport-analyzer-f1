---
title: Phase 3 - Prediction Engine and Car Panel
type: phase
phase: 3
status: done
tags: [phase, models, prediction, car-panel]
updated: 2026-06-18
---

# Phase 3 — Prediction Engine & Car Detail Panel ✅

> "The AI": tyre / fuel / pit / finish predictions + the right-side Car panel. Back to [[Home]].

## Goal
Live-updating predictions per car; an SC visibly reshuffles the predicted finish.

## Backend (`backend/models/`) — see [[Prediction Models]] for the full mechanics
- `fuel.py` — deterministic fuel **EST**.
- `tire.py` — **Model A** tyre degradation (heuristic + distilled-GBT priors).
- `hazard.py` — **Model C** per-circuit safety-car rate → per-lap hazard.
- `montecarlo.py` — **Model B** vectorised NumPy finish simulation (~250 ms/2k sims);
  an SC restart compresses the field and shifts the odds.
- `predictor.py` — assembles one `PredictionMsg` per car; also `dnf_prediction()`.
- `priors.py` + `models/artifacts/priors.json` — every model loads the artifact if
  present, else ships **principled priors** so the app runs with **no training step**.

Wired into `ReplayEngine`: refresh every 30 s session-time + immediately on
flag/pit; included in the snapshot for new clients. **No WS schema change** —
`PredictionMsg` was already in protocol v1.

## Offline ML (`ml/`, host-only)
`build_training_set.py` (FastF1) → `train_tire.py` / `train_hazard.py` /
`build_priors.py` (XGBoost/LightGBM → distilled coeffs); `backtest.py` runs
**in-sandbox** on fixtures → `ml/reports/`. Calibration history: [[Calibration Log]].

## Frontend (`features/car-panel/`)
Right slide-in panel; **every field tagged LIVE/EST/AI**. Hand-rolled SVG
degradation sparkline + finish-distribution bar chart (no new frontend deps).
Later (Phase 5) gained a tabbed **"Car" schematic** — see [[Phase 5 - Polish UX and Live Mode]].

## Acceptance
Backtest report generated; panel shows live predictions; SC events visibly shift
the predicted finishes. 48 backend tests.

Related: [[Prediction Models]] · [[Calibration Log]] · [[Architecture]] · [[Design System]] · [[Phase 4 - Track Detail and 3D]]
