"""Shipped priors for the prediction engine.

These constants make the app work *today* without any offline training run. The
offline pipeline (`ml/build_priors.py`, `ml/overtaking_index.py`,
`ml/train_*.py`) can write a richer ``models/artifacts/priors.json`` that
overrides any subset of these values; loading is transparent via
:func:`load_priors`.

Provenance of the seeded numbers:
  * compound pace/deg/cliff: typical Pirelli dry-compound behaviour, fuel- and
    track-temp-normalised; rough but directionally correct.
  * per-circuit SC rate + overtaking difficulty: hand-seeded from well-known
    historical character (Monaco ~never overtakes & high SC; Monza easy passing
    & low SC). `ml/` recomputes these from Kaggle `lap_times`/`results`.
  * fuel burn: ~1.2-1.9 kg/lap scaled by lap distance.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------- compounds

# Pace offset is seconds vs. a fresh MEDIUM baseline (negative = faster).
# `deg` is the *linear* degradation in s/lap added per lap of tyre age, before
# the non-linear cliff. `cliff` is the tyre age (laps) at which the cliff hits.
COMPOUNDS: dict[str, dict[str, float]] = {
    "SOFT":         {"pace": -0.55, "deg": 0.055, "cliff": 16.0},
    "MEDIUM":       {"pace":  0.00, "deg": 0.038, "cliff": 26.0},
    "HARD":         {"pace":  0.55, "deg": 0.026, "cliff": 38.0},
    "INTERMEDIATE": {"pace":  4.50, "deg": 0.045, "cliff": 30.0},
    "WET":          {"pace":  9.00, "deg": 0.050, "cliff": 28.0},
    "UNKNOWN":      {"pace":  0.20, "deg": 0.040, "cliff": 26.0},
}

# Fuel correction: a full (~110 kg) car is ~0.03 s/kg slower. Used to normalise
# observed lap times to a fresh-tyre, low-fuel baseline (BUILD_PROMPT §5.1).
FUEL_S_PER_KG = 0.030

# Past the cliff, degradation steepens by this factor per lap over the cliff.
CLIFF_ACCEL = 0.14

# ---------------------------------------------------------------- circuits

# overtaking_difficulty: 0 = trivial passing (Monza), 1 = nearly impossible
#   (Monaco). Scales Monte-Carlo overtake success probability.
# sc_rate: P(>=1 safety car in the race), historical. Drives Model C base hazard.
# fuel_kg_per_lap / pit_loss_s: per-circuit; default used when unknown.
_DEFAULT_CIRCUIT = {
    "overtaking_difficulty": 0.55,
    "sc_rate": 0.40,
    "fuel_kg_per_lap": 1.60,
    "pit_loss_s": 21.0,
}

CIRCUITS: dict[str, dict[str, float]] = {
    "monaco":      {"overtaking_difficulty": 0.97, "sc_rate": 0.72, "fuel_kg_per_lap": 1.25, "pit_loss_s": 19.0},
    "singapore":   {"overtaking_difficulty": 0.85, "sc_rate": 0.80, "fuel_kg_per_lap": 1.65, "pit_loss_s": 27.0},
    "montreal":    {"overtaking_difficulty": 0.45, "sc_rate": 0.60, "fuel_kg_per_lap": 1.55, "pit_loss_s": 18.0},
    "montréal":    {"overtaking_difficulty": 0.45, "sc_rate": 0.60, "fuel_kg_per_lap": 1.55, "pit_loss_s": 18.0},
    "canada":      {"overtaking_difficulty": 0.45, "sc_rate": 0.60, "fuel_kg_per_lap": 1.55, "pit_loss_s": 18.0},
    "monza":       {"overtaking_difficulty": 0.20, "sc_rate": 0.30, "fuel_kg_per_lap": 1.80, "pit_loss_s": 22.0},
    "spa":         {"overtaking_difficulty": 0.30, "sc_rate": 0.45, "fuel_kg_per_lap": 1.90, "pit_loss_s": 19.0},
    "silverstone": {"overtaking_difficulty": 0.40, "sc_rate": 0.40, "fuel_kg_per_lap": 1.75, "pit_loss_s": 20.0},
    "baku":        {"overtaking_difficulty": 0.55, "sc_rate": 0.78, "fuel_kg_per_lap": 1.60, "pit_loss_s": 19.0},
    "jeddah":      {"overtaking_difficulty": 0.50, "sc_rate": 0.75, "fuel_kg_per_lap": 1.65, "pit_loss_s": 21.0},
    "zandvoort":   {"overtaking_difficulty": 0.80, "sc_rate": 0.35, "fuel_kg_per_lap": 1.45, "pit_loss_s": 21.0},
    "hungaroring": {"overtaking_difficulty": 0.82, "sc_rate": 0.35, "fuel_kg_per_lap": 1.40, "pit_loss_s": 20.0},
    "suzuka":      {"overtaking_difficulty": 0.60, "sc_rate": 0.45, "fuel_kg_per_lap": 1.70, "pit_loss_s": 22.0},
    "interlagos":  {"overtaking_difficulty": 0.35, "sc_rate": 0.55, "fuel_kg_per_lap": 1.55, "pit_loss_s": 20.0},
    "austin":      {"overtaking_difficulty": 0.40, "sc_rate": 0.45, "fuel_kg_per_lap": 1.70, "pit_loss_s": 21.0},
    "melbourne":   {"overtaking_difficulty": 0.55, "sc_rate": 0.55, "fuel_kg_per_lap": 1.60, "pit_loss_s": 21.0},
}

# Per-team DNF (reliability) hazard per race, historical-ish prior. Refined by
# ml/ from Kaggle status.csv. Used as a fallback when no per-team value exists.
DEFAULT_DNF_RATE = 0.06


def normalize_circuit(name: str | None) -> str:
    return (name or "").strip().lower()


def circuit_priors(name: str | None) -> dict[str, float]:
    """Merge shipped per-circuit values over defaults (+ any artifact override)."""
    key = normalize_circuit(name)
    overrides = load_priors().get("circuits", {})
    merged = dict(_DEFAULT_CIRCUIT)
    if key in CIRCUITS:
        merged.update(CIRCUITS[key])
    if key in overrides:
        merged.update(overrides[key])
    return merged


def compound_priors(compound: str | None) -> dict[str, float]:
    key = (compound or "UNKNOWN").strip().upper()
    base = COMPOUNDS.get(key, COMPOUNDS["UNKNOWN"])
    overrides = load_priors().get("compounds", {})
    if key in overrides:
        return {**base, **overrides[key]}
    return dict(base)


def _artifacts_dir() -> Path:
    env = os.environ.get("MODELS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "models" / "artifacts"


@lru_cache(maxsize=1)
def load_priors() -> dict:
    """Optional ``models/artifacts/priors.json`` written by the offline pipeline."""
    path = _artifacts_dir() / "priors.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
