---
title: Glossary
type: topic
tags: [glossary, terms]
updated: 2026-06-18
---

# Glossary

> Quick definitions. Back to [[Home]].

- **LIVE / EST / AI** — UI provenance tags. LIVE = real feed; EST = deterministic
  estimate (fuel); AI = model output (tyre life, finish). Core honesty rule —
  [[Design System]], [[Data Sources and Constraints]].
- **Fixture** — a recorded race in `data/fixtures/<year>_<country>_race/`
  (one Parquet per stream + `meta.json`). The replay unit — [[Phase 0 - Data Access Spike]].
- **Replay mode** — re-emitting a fixture through the event bus (1×/2×/10×, scrub).
  First-class, mirrors live — [[Architecture]].
- **Live mode** — real-time ingest behind `OPENF1_TOKEN`; not yet built —
  [[Phase 5 - Polish UX and Live Mode]].
- **Cliff** — tyre age where degradation accelerates non-linearly; "laps to cliff"
  is a Model A output — [[Prediction Models]].
- **Persistence baseline** — "freeze the current running order"; the bar Model B is
  scored against — [[Calibration Log]].
- **Anchor (Model B)** — blending the simulated expected finish toward the live
  order, weighted by race fraction remaining — [[Calibration Log]].
- **`sc_rate`** — per-circuit P(≥1 safety car); drives Model C — [[Prediction Models]].
- **Empirical-Bayes shrinkage** — pulling a low-sample circuit's rate toward the
  global mean so it doesn't overfit — [[Calibration Log]].
- **Brier score** — mean squared error of probabilistic predictions; lower = better;
  compared to a no-skill (base-rate) baseline — [[Calibration Log]].
- **`circuit_short_name`** — OpenF1's circuit key (e.g. "Monte Carlo"); the **runtime
  key** everything must align to — [[Environment Gotchas]].
- **`circuitRef`** — Ergast/Kaggle circuit key (e.g. "monaco"); needs a crosswalk to
  `circuit_short_name` — [[Environment Gotchas]], [[Calibration Log]].
- **georef / `assetToMerc`** — fitting the telemetry outline to real-world web-Mercator
  tiles; reused by the 3D scene — [[Phase 2 - Live Track Map]], [[Phase 4 - Track Detail and 3D]].
- **VEXAG** — vertical exaggeration (1.8×) of elevation in the 3D ribbon — [[Phase 4 - Track Detail and 3D]].
- **WS schema** — `backend/api/schema.py`; one source → Pydantic + TS types.
  Changing it needs approval — [[Architecture]], [[About Me]].

Related: [[Home]]
