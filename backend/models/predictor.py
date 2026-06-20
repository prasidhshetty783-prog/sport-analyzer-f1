"""Orchestrates Models A/B/C + the fuel estimator into ``PredictionMsg``s.

Given a snapshot of running cars (from :meth:`RaceState.predict_inputs`), the
race lap, the current flag, and the latest weather, it produces one prediction
per car. The replay engine calls :meth:`predict` on a cadence and immediately on
SC/VSC/red or pit events, so the Car-Detail panel updates live and the field
visibly reshuffles under a safety car.

Field provenance (mirrors the UI tags):
  * tyre   -> AI   (Model A)
  * fuel   -> EST  (deterministic estimator)
  * finish -> AI   (Model B Monte-Carlo)
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.api.schema import (FinishDist, FuelEst, PredictionMsg, TyrePred,
                                WeatherMsg)
from backend.models.fuel import FuelEstimator
from backend.models.hazard import HazardModel
from backend.models.montecarlo import CarSim, MonteCarloSimulator
from backend.models.priors import DEFAULT_DNF_RATE, load_priors
from backend.models.tire import TireModel

DIRTY_AIR_S = 2.0  # interval-to-car-ahead below this ⇒ dirty air (BUILD_PROMPT)


@dataclass
class CarInput:
    code: str
    position: int
    current_lap: int
    gap_leader_s: float | None
    interval_s: float | None
    compound: str | None
    tyre_age: int | None
    pits: int


class Predictor:
    def __init__(self, circuit: str | None, total_laps: int, *, n_sims: int = 1500):
        self.circuit = circuit
        self.total_laps = max(1, int(total_laps))
        self.n_sims = n_sims
        self.tire = TireModel(circuit)
        self.fuel = FuelEstimator(circuit, total_laps)
        self.mc = MonteCarloSimulator(circuit, total_laps)
        self.hazard = HazardModel(circuit, total_laps)

    def predict(
        self,
        cars: list[CarInput],
        *,
        race_lap: int,
        flag: str = "GREEN",
        weather: WeatherMsg | None = None,
        sc_laps: int = 0,
        t_s: float = 0.0,
        seed: int | None = None,
    ) -> list[PredictionMsg]:
        if not cars:
            return []
        track_temp = weather.track if weather else None
        rain = bool(weather.rain) if weather else False

        # per-car race DNF hazard: calibrated global rate from the Kaggle dump
        # (ml/build_priors.py) when present, else the shipped default.
        dnf_default = float(load_priors().get("dnf", {}).get("default", DEFAULT_DNF_RATE))
        # --- Model B: one simulation produces every car's finish distribution
        sim_cars = [
            CarSim(
                code=c.code, position=c.position, gap_s=c.gap_leader_s,
                compound=c.compound, tyre_age=int(c.tyre_age or 0), pits=c.pits,
                fuel_laps=self.fuel.estimate(c.current_lap, sc_laps).laps,
                dnf_rate=dnf_default,
            )
            for c in cars
        ]
        finish = self.mc.simulate(
            sim_cars, current_lap=race_lap, flag=flag, rain=rain,
            track_temp=track_temp, n_sims=self.n_sims, seed=seed)

        out: list[PredictionMsg] = []
        for c in cars:
            dirty = c.interval_s is not None and c.interval_s < DIRTY_AIR_S
            dirty_share = 0.7 if dirty else 0.1
            tyre = self.tire.predict(
                c.compound, c.tyre_age, track_temp=track_temp, rain=rain,
                dirty_share=dirty_share)
            fuel = self.fuel.estimate(c.current_lap, sc_laps)
            fp = finish.get(c.code)
            if fp is None:
                continue
            out.append(PredictionMsg(
                drv=c.code,
                finish=FinishDist(exp=fp.exp, p_win=fp.p_win,
                                  p_podium=fp.p_podium, p_points=fp.p_points,
                                  dist=fp.dist),
                tyre=TyrePred(deg_rate=tyre.deg_rate,
                              laps_to_cliff=tyre.laps_to_cliff),
                fuel=FuelEst(kg=fuel.kg, laps=fuel.laps),
                updated_at=round(float(t_s), 1),
            ))
        return out

    def sc_likelihood(self, *, rain: bool = False) -> float:
        return self.hazard.sc_likelihood_today(rain=rain)

    @staticmethod
    def dnf_prediction(code: str, field_size: int, t_s: float) -> PredictionMsg:
        """A retired car: classified last, zero finishing-chance everywhere, so
        the panel shows DNF instead of a stale (and misleading) podium odds."""
        n = max(1, int(field_size))
        dist = [0.0] * n
        dist[-1] = 1.0
        return PredictionMsg(
            drv=code,
            finish=FinishDist(exp=float(n), p_win=0.0, p_podium=0.0,
                              p_points=0.0, dist=dist),
            tyre=TyrePred(deg_rate=0.0, laps_to_cliff=0.0),
            fuel=FuelEst(kg=0.0, laps=0.0),
            updated_at=round(float(t_s), 1))
