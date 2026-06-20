"""§5.3 Model C — safety-car / red-flag hazard.

Per-lap deployment probability built from a per-circuit historical SC rate
(some circuits are near-certain SC, others rare) multiplied by situational
factors: rain, the chaotic opening lap, and recent on-track incident density
(from `race_control`). A logistic/GBM would slot in here; the calibrated-rate
form below is the principled prior and what `ml/train_hazard.py` refines.

Consumed by the Monte-Carlo simulator (Model B) and surfaced in Track Detail as
"SC likelihood today" (Phase 4).
"""
from __future__ import annotations

from backend.models.priors import circuit_priors, load_priors

# Fallback multipliers, used only when no calibrated artifact is present.
# `ml/calibrate_hazard.py` fits these from the recorded fixtures and writes them
# (plus a mean-calibration `prob_scale`) into priors.json["hazard"]; the
# per-circuit `sc_rate` likewise comes from priors.json["circuits"] when present.
_RAIN_MULT = 1.8
_LAP1_MULT = 3.0
_INCIDENT_MULT = 0.5   # per recent incident
_MAX_LAP_PROB = 0.55


class HazardModel:
    def __init__(self, circuit: str | None, total_laps: int):
        self.total_laps = max(1, int(total_laps))
        self.sc_rate = float(circuit_priors(circuit)["sc_rate"])
        hz = load_priors().get("hazard", {})
        self.rain_mult = float(hz.get("rain_mult", _RAIN_MULT))
        self.lap1_mult = float(hz.get("lap1_mult", _LAP1_MULT))
        self.prob_scale = float(hz.get("prob_scale", 1.0))
        # invert P(>=1 in race) into a per-green-lap base hazard, then apply the
        # calibrated mean-scale so predicted SC frequency matches the data.
        self.base_lap = (
            1.0 - (1.0 - self.sc_rate) ** (1.0 / self.total_laps)
        ) * self.prob_scale

    def per_lap_prob(
        self,
        lap: int,
        *,
        rain: bool = False,
        recent_incidents: int = 0,
        sc_active: bool = False,
    ) -> float:
        if sc_active:
            return 0.0  # already neutralised; can't redeploy on top
        p = self.base_lap
        if rain:
            p *= self.rain_mult
        if lap <= 1:
            p *= self.lap1_mult
        if recent_incidents:
            p *= 1.0 + _INCIDENT_MULT * recent_incidents
        return min(_MAX_LAP_PROB, p)

    def sc_likelihood_today(self, *, rain: bool = False) -> float:
        """Race-level P(>=1 SC) adjusted for today's conditions, in [0, 1]."""
        rate = self.sc_rate * (1.35 if rain else 1.0)
        return round(min(0.98, rate), 3)
