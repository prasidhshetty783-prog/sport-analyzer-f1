"""§5.1 Model A — tyre degradation & remaining life.

Serves a degradation curve from compound, tyre age, track temperature, and
dirty-air exposure. The shape is a linear wear region followed by a non-linear
"cliff". Coefficients come from :mod:`backend.models.priors`, which the offline
trainer (`ml/train_tire.py`) refines from a FastF1-built stint table and writes
back into ``models/artifacts/priors.json`` (distilled GBT coefficients) — so the
served model is dependency-free while still being trained offline.

Outputs (all tagged AI in the UI):
  * deg_rate     — current degradation, s/lap (slope of the wear curve now)
  * laps_to_cliff — projected laps until the performance cliff
  * curve        — cumulative time loss vs. fresh tyre over the next laps,
                   for the Car-Detail sparkline
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.models.priors import CLIFF_ACCEL, compound_priors

BASE_TRACK_TEMP = 35.0  # reference track temp the priors are normalised to
CURVE_HORIZON = 14       # laps drawn in the sparkline


@dataclass
class TyreReading:
    deg_rate: float          # s/lap, current
    laps_to_cliff: float     # laps until cliff (0 = already past it)
    curve: list[float]       # cumulative s lost vs fresh, ages [now .. now+H]
    compound: str
    age: int


def _temp_mult(track_temp: float | None) -> float:
    if track_temp is None:
        return 1.0
    return min(1.6, max(0.8, 1.0 + 0.012 * (track_temp - BASE_TRACK_TEMP)))


def _dirty_mult(dirty_share: float) -> float:
    return 1.0 + 0.25 * max(0.0, min(1.0, dirty_share))


class TireModel:
    """Stateless; one instance per race is plenty."""

    def __init__(self, circuit: str | None = None):
        self.circuit = circuit

    def _cum_loss(self, comp: dict, age: float, tmult: float, dmult: float) -> float:
        """Cumulative seconds lost vs a fresh tyre at a given age."""
        age = max(0.0, age)
        cliff = comp["cliff"]
        linear = comp["deg"] * age
        over = max(0.0, age - cliff)
        cliffy = 0.5 * CLIFF_ACCEL * over * over
        return (linear + cliffy) * tmult * dmult

    def predict(
        self,
        compound: str | None,
        tyre_age: int | None,
        *,
        track_temp: float | None = None,
        rain: bool = False,
        dirty_share: float = 0.0,
    ) -> TyreReading:
        comp = compound_priors(compound)
        age = float(tyre_age or 0)
        tmult = _temp_mult(track_temp)
        dmult = _dirty_mult(dirty_share)

        # Slicks on a wet track wear/grain abnormally fast; nudge the cliff in.
        wrong_tyre = rain and (compound or "").upper() in ("SOFT", "MEDIUM", "HARD")
        cliff = comp["cliff"]
        if wrong_tyre:
            cliff *= 0.4

        # effective cliff brought forward by heat + dirty air
        eff_cliff = cliff / (tmult * (1.0 + 0.30 * max(0.0, min(1.0, dirty_share))))
        laps_to_cliff = max(0.0, eff_cliff - age)

        # instantaneous slope of the cumulative-loss curve at the current age
        over = max(0.0, age - cliff)
        deg_rate = (comp["deg"] + CLIFF_ACCEL * over) * tmult * dmult
        if wrong_tyre:
            deg_rate *= 1.6

        base = self._cum_loss(comp, age, tmult, dmult)
        curve = [
            round(self._cum_loss(comp, age + k, tmult, dmult) - base, 3)
            for k in range(CURVE_HORIZON + 1)
        ]
        return TyreReading(
            deg_rate=round(deg_rate, 3),
            laps_to_cliff=round(laps_to_cliff, 1),
            curve=curve,
            compound=(compound or "UNKNOWN").upper(),
            age=int(age),
        )

    def pace_penalty(
        self,
        compound: str | None,
        tyre_age: float,
        *,
        track_temp: float | None = None,
        dirty_share: float = 0.0,
    ) -> float:
        """Seconds/lap a car loses *right now* from tyre wear (for Model B)."""
        comp = compound_priors(compound)
        return self._cum_loss(comp, tyre_age, _temp_mult(track_temp),
                              _dirty_mult(dirty_share))
