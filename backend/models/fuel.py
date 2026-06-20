"""§5.4 Fuel estimator — deterministic, NOT machine-learned.

    fuel_remaining = start_load - Σ(burn_per_lap)

Start load is capped at the 110 kg regulation maximum; per-circuit burn comes
from the priors table (~1.2-1.9 kg/lap) and is reduced ~35 % under SC/VSC, when
the field runs slowly behind the safety car. Output is exposed both in kg and as
"laps of fuel" and is always tagged EST in the UI — never presented as telemetry.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.models.priors import circuit_priors

MAX_FUEL_KG = 110.0
SC_BURN_FACTOR = 0.65  # ~35 % less fuel used per lap behind SC/VSC
_MARGIN = 1.04         # teams fill slightly over race distance


@dataclass
class FuelReading:
    kg: float
    laps: float  # laps of fuel remaining at the current burn rate


class FuelEstimator:
    def __init__(self, circuit: str | None, total_laps: int):
        pri = circuit_priors(circuit)
        self.burn = float(pri["fuel_kg_per_lap"])
        self.total_laps = max(1, int(total_laps))
        # Start with just enough for the race distance + a small margin, capped.
        self.start_load = min(MAX_FUEL_KG, self.burn * self.total_laps * _MARGIN)

    def estimate(self, current_lap: int, sc_laps: int = 0) -> FuelReading:
        """Fuel after completing ``current_lap`` laps, ``sc_laps`` of them slow."""
        lap = max(0, int(current_lap))
        sc = max(0, min(int(sc_laps), lap))
        green = lap - sc
        used = self.burn * green + self.burn * SC_BURN_FACTOR * sc
        kg = max(0.0, self.start_load - used)
        return FuelReading(kg=round(kg, 1), laps=round(kg / self.burn, 1))
