---
title: Calibration Log
type: topic
tags: [calibration, backtest, mae, brier, priors]
updated: 2026-06-18
---

# Calibration Log

> Every model-tuning pass with honest numbers. Mechanics in [[Prediction Models]].
> Back to [[Home]]. (Methodology note: backtest measures **finish-position MAE** vs
> a persistence baseline = "freeze the current running order".)

## 1. Model B — anchor + σ calibration (June 2026)
**Problem:** the simulator **trailed** persistence (overall MAE **2.771** vs
**1.474** across 70 fixtures) — high per-lap noise reshuffled the field, regressing
every car toward mid-grid.
**Fix (`montecarlo.py`):** `LAP_NOISE` 0.35→**0.12**, `POS_SPREAD` 0.055→**0.085**,
and blend the reported `exp` toward the live order (`ANCHOR_MIN=0.08`,
`ANCHOR_MAX=0.22`, weighted by race fraction left). Added `SA_SIMS` env override.
**Result (15-race sample):** mean MAE **2.96 → 1.86** (≈ persistence 1.80).
**Honest read:** on these sticky 2023/24 races the live order is already near-optimal,
so the realistic ceiling is "match persistence on point-MAE"; the sim's real value
is the probability distribution + SC-reactivity. Beating persistence needs the
chaotic tail.

## 2. Model C — SC hazard calibration (`ml/calibrate_hazard.py`)
Fit **in-sandbox** from 76 fixtures' `race_control` (detect `"SAFETY CAR DEPLOYED"`,
excluding VSC/heads-ups). Writes to `priors.json` keyed by **`circuit_short_name`**.
- Per-circuit **P(≥1 SC)** with **empirical-Bayes shrinkage** (K=6) — Interlagos/
  Jeddah/Lusail ~0.66, Monza/Spa/Yas ~0.33.
- Per-lap multipliers from data: **lap-1 ×8.0**, **rain ×1.25**, mean-scale **×0.711**.
- **Brier (SC-within-10-laps, 4448 lap-points):** model **0.0681** vs no-skill
  **0.0696** → **+2.3% skill**; reliability matches (predict ~12% → ~13% occur).
- Scorecard: `ml/reports/hazard_calibration.md`. `hazard.py` reads these at runtime.

## 3. Kaggle results-level priors (`ml/build_priors.py`, 1950–2024 dump)
Rewrote the builder to **auto-locate** the CSVs and apply an **Ergast→OpenF1
circuit crosswalk** (fixes the [[Environment Gotchas|key-mismatch bug]] — previously
keyed by Ergast `circuitRef` and silently bypassed). Field-level merged into
`priors.json` so calibrated `sc_rate`/`hazard` survive.
- **overtaking_difficulty** (mean |grid−finish|, 2014+) — 23 circuits, keyed correctly.
- **pit_loss_s** (median pit duration, 2018+) — ~19 s (Albert Park) … 30 s (Imola).
- **global dnf_rate = 0.171** (true 2014+ non-finish rate) → wired into Model B via
  `predictor.py` (was a flat 0.06).
**Result (15-race sample):** MAE **1.851** — **flat** vs Model-B-only 1.858.
**Honest read:** point-MAE didn't move because the anchored estimate tracks the live
order on stable races; the data's value is **correctness/realism** (per-circuit
priors now actually apply; believable DNF/pit-loss) and the chaotic-race tail.
Don't overfit DNF/overtaking to chase this sample.

## Backtest baseline reference
`ml/reports/backtest.md` (70 fixtures, pre-calibration): MAE 2.771 vs persistence
1.474, top-3 0.748. Regenerate on host: `python -m ml.backtest`.

## Open levers (if chasing a point-MAE win)
Add more **chaotic** fixtures; per-team DNF from Kaggle `constructors`/`status`;
probability-calibrate P(win)/P(podium). Not more data volume.

Related: [[Prediction Models]] · [[Phase 3 - Prediction Engine and Car Panel]] · [[Phase 5 - Polish UX and Live Mode]] · [[Commands and Run Guide]]
