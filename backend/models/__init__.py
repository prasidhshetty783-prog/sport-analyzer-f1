"""Phase 3 prediction engine.

Models are trained offline by scripts in ``ml/`` and serialized into
``models/artifacts/``; this package *serves* them in-process. Every model
degrades to a principled, calibrated prior when no trained artifact is present,
so the app stays fully demoable in replay mode without any training run (the
Cowork/Claude sandbox cannot reach the F1 data domains — see CLAUDE.md).

Honest labelling (BUILD_PROMPT §2.4) is enforced at the message layer:
  * fuel   -> EST  (deterministic estimator, never telemetry)
  * tyre   -> AI   (Model A output)
  * finish -> AI   (Model B Monte-Carlo output)
"""
from __future__ import annotations

from backend.models.fuel import FuelEstimator
from backend.models.hazard import HazardModel
from backend.models.montecarlo import MonteCarloSimulator
from backend.models.predictor import Predictor
from backend.models.tire import TireModel

__all__ = [
    "FuelEstimator",
    "HazardModel",
    "MonteCarloSimulator",
    "Predictor",
    "TireModel",
]
