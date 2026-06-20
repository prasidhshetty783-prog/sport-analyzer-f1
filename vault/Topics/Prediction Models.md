---
title: Prediction Models
type: topic
tags: [models, prediction, tyre, montecarlo, hazard, fuel]
updated: 2026-06-18
---

# Prediction Models (A / B / C + Fuel)

> How the "AI" works. Mechanics here; tuning history in [[Calibration Log]]. Back to [[Home]].

All live in `backend/models/`, served in-process, and load
`models/artifacts/priors.json` if present (else principled defaults in
`priors.py`), so the app runs with **no training step**. Built/refined by `ml/`.

## Model A — Tyre degradation & life (`tire.py`)
- Inputs: compound, tyre age, circuit, est. fuel, track/air temp, rain, dirty-air
  share, stint, track status.
- Output to UI (**AI**): current deg rate (s/lap), projected **laps to cliff**,
  degradation-curve sparkline.
- Per-compound priors (`COMPOUNDS` in `priors.py`): `pace`, `deg`, `cliff`;
  past the cliff, deg steepens by `CLIFF_ACCEL`. Fuel correction ≈ 0.03 s/kg.

## Model B — Finish prediction (Monte-Carlo, `montecarlo.py`)
A per-lap **stochastic simulation** (not a single regression) so SC/red flags
genuinely move the prediction. Vectorised NumPy, ~1–2k sims/refresh.
- Each sim lap: pace from Model A + noise (`LAP_NOISE`), per-circuit overtaking
  (difficulty index), simple pit policy, DNF hazard, SC draws from **Model C**.
- SC compresses the field → visibly reshuffles odds.
- **Output:** expected finish, P(win)/P(podium)/P(points), full distribution.
- **Calibration (June 2026):** σ cut 0.35→0.12, `POS_SPREAD`↑, and the reported
  `exp` is **blended toward the live running order** (`ANCHOR_MIN..ANCHOR_MAX`,
  weighted by race fraction remaining). `SA_SIMS` env overrides sim count for fast
  backtests. Per-car `dnf_rate` now comes from the Kaggle prior via `predictor.py`.
  Numbers in [[Calibration Log]].

## Model C — Safety-car hazard (`hazard.py`)
- Per-circuit historical **`sc_rate`** (P(≥1 SC)) → inverted to a per-green-lap
  base hazard, × multipliers: **lap-1**, **rain**, recent incidents.
- **Calibration:** `sc_rate` (empirical-Bayes shrunk per circuit), `lap1_mult`,
  `rain_mult`, and a mean-calibration `prob_scale` are fit from fixtures by
  `ml/calibrate_hazard.py` and read from `priors.json["hazard"]`. Scorecard:
  `ml/reports/hazard_calibration.md`. See [[Calibration Log]].
- Also surfaced as "SC likelihood today" in [[Phase 4 - Track Detail and 3D|Track Detail]].

## Fuel estimator (`fuel.py`, deterministic — EST)
`fuel_remaining = start_load − Σ(burn_per_lap)`, start ≤110 kg, per-circuit burn
(~1.2–1.9 kg/lap, reduced ~35% under SC/VSC). Exposes kg and "laps of fuel".

## Orchestration (`predictor.py`)
Assembles one `PredictionMsg` per car (tyre AI, fuel EST, finish AI). Called by the
replay engine every 30 s + on flag/pit. `dnf_prediction()` classifies retired cars
last. Provenance tags mirror the UI ([[Design System]]).

## Evaluation
`ml/backtest.py` reconstructs race state at lap *k* on fixtures and scores finish
MAE vs a **persistence baseline** (freeze current order), top-3 hit, Spearman →
`ml/reports/backtest.md`. SC calibration scored separately (Brier/reliability).

Related: [[Phase 3 - Prediction Engine and Car Panel]] · [[Calibration Log]] · [[Architecture]] · [[Glossary]]
