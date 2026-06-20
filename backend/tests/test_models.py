"""Phase 3 — prediction engine tests.

Covers the fuel estimator, tyre model, hazard model, the Monte-Carlo simulator,
the predictor that assembles ``PredictionMsg``s, and the replay-engine
integration that emits them on the bus (including the safety-car shift).
"""
from __future__ import annotations

import pytest

from backend.api.schema import PredictionMsg, WeatherMsg
from backend.models.fuel import FuelEstimator
from backend.models.hazard import HazardModel
from backend.models.montecarlo import CarSim, MonteCarloSimulator
from backend.models.predictor import CarInput, Predictor
from backend.models.tire import TireModel


# ----------------------------- fuel -----------------------------

def test_fuel_monotonic_and_capped():
    fe = FuelEstimator("Montreal", 70)
    assert fe.start_load <= 110.0
    full = fe.estimate(0)
    mid = fe.estimate(35)
    end = fe.estimate(70)
    assert full.kg > mid.kg > end.kg >= 0.0
    # at the flag there should be little fuel left (teams don't over-fuel much)
    assert end.kg < full.kg * 0.15
    assert full.laps > mid.laps


def test_fuel_sc_laps_save_fuel():
    fe = FuelEstimator("Montreal", 70)
    green = fe.estimate(30, sc_laps=0)
    under_sc = fe.estimate(30, sc_laps=10)
    assert under_sc.kg > green.kg  # SC laps burn ~35 % less


# ----------------------------- tyre -----------------------------

def test_tyre_deg_grows_with_age():
    tm = TireModel("Montreal")
    young = tm.predict("MEDIUM", 3, track_temp=40)
    old = tm.predict("MEDIUM", 25, track_temp=40)
    assert old.deg_rate >= young.deg_rate
    assert old.laps_to_cliff < young.laps_to_cliff
    # cumulative-loss sparkline is non-decreasing
    assert all(b >= a - 1e-6 for a, b in zip(old.curve, old.curve[1:]))


def test_tyre_soft_cliffs_before_hard():
    tm = TireModel("Montreal")
    soft = tm.predict("SOFT", 10, track_temp=40)
    hard = tm.predict("HARD", 10, track_temp=40)
    assert soft.laps_to_cliff < hard.laps_to_cliff


def test_tyre_hotter_track_brings_cliff_forward():
    tm = TireModel("Montreal")
    cool = tm.predict("MEDIUM", 10, track_temp=25)
    hot = tm.predict("MEDIUM", 10, track_temp=50)
    assert hot.laps_to_cliff <= cool.laps_to_cliff
    assert hot.deg_rate >= cool.deg_rate


# ----------------------------- hazard -----------------------------

def test_hazard_probabilities_bounded():
    hz = HazardModel("Monaco", 78)
    for lap in (1, 10, 40):
        p = hz.per_lap_prob(lap, rain=False)
        assert 0.0 <= p <= 0.55
    assert hz.per_lap_prob(5, sc_active=True) == 0.0


def test_hazard_rain_and_lap1_raise_risk():
    hz = HazardModel("Montreal", 70)
    base = hz.per_lap_prob(20, rain=False)
    assert hz.per_lap_prob(20, rain=True) > base
    assert hz.per_lap_prob(1, rain=False) > base
    assert hz.sc_likelihood_today(rain=True) >= hz.sc_likelihood_today(rain=False)


def test_monaco_more_sc_than_monza():
    assert (HazardModel("Monaco", 78).sc_likelihood_today()
            > HazardModel("Monza", 53).sc_likelihood_today())


# ----------------------------- Monte Carlo -----------------------------

def _grid(n=20, **kw):
    return [CarSim(code=f"D{i:02d}", position=i + 1, gap_s=float(i) * 2.0,
                   compound="MEDIUM", tyre_age=12, pits=1, fuel_laps=20.0, **kw)
            for i in range(n)]


def test_mc_distribution_valid():
    mc = MonteCarloSimulator("Montreal", 70)
    out = mc.simulate(_grid(), current_lap=40, n_sims=800, seed=0)
    assert len(out) == 20
    for fp in out.values():
        assert abs(sum(fp.dist) - 1.0) < 5e-3  # entries rounded to 4 dp
        assert 0.0 <= fp.p_win <= 1.0
        assert fp.p_podium >= fp.p_win
        assert fp.p_points >= fp.p_podium
        assert 1.0 <= fp.exp <= 20.0
    # probabilities are consistent across the field
    assert abs(sum(fp.p_podium for fp in out.values()) - 3.0) < 0.05
    assert abs(sum(fp.p_points for fp in out.values()) - 10.0) < 0.05


def test_mc_leader_favoured():
    mc = MonteCarloSimulator("Montreal", 70)
    out = mc.simulate(_grid(), current_lap=40, n_sims=1500, seed=1)
    assert out["D00"].exp < out["D10"].exp < out["D19"].exp
    assert out["D00"].p_win > 0.4


def test_mc_safety_car_shifts_finish():
    """A late safety car must visibly reduce the leader's win probability."""
    mc = MonteCarloSimulator("Montreal", 70)
    cars = [CarSim(f"D{i:02d}", i + 1, float(i) * 2.0, "HARD", 28, 1, 12.0)
            for i in range(20)]
    green = mc.simulate(cars, current_lap=62, flag="GREEN", n_sims=2000, seed=7)
    sc = mc.simulate(cars, current_lap=62, flag="SC", n_sims=2000, seed=7)
    assert sc["D00"].p_win < green["D00"].p_win - 0.04
    assert sc["D01"].p_win > green["D01"].p_win  # runner-up gains


def test_mc_within_time_budget():
    import time
    mc = MonteCarloSimulator("Montreal", 70)
    t = time.time()
    mc.simulate(_grid(), current_lap=10, n_sims=2000, seed=2)
    assert time.time() - t < 2.0


# ----------------------------- predictor -----------------------------

def test_predictor_emits_for_all_cars():
    cars = [CarInput(code=f"D{i:02d}", position=i + 1, current_lap=30,
                     gap_leader_s=float(i) * 2.0, interval_s=2.0,
                     compound="MEDIUM", tyre_age=12, pits=1) for i in range(20)]
    p = Predictor("Montreal", 70, n_sims=600)
    wx = WeatherMsg(air=22, track=42, humidity=50, rain=False, wind=3)
    msgs = p.predict(cars, race_lap=30, flag="GREEN", weather=wx, t_s=1500.0, seed=3)
    assert len(msgs) == 20
    assert all(isinstance(m, PredictionMsg) for m in msgs)
    m = msgs[0]
    assert m.updated_at == 1500.0
    assert m.fuel.kg > 0 and m.fuel.laps > 0
    assert m.tyre.laps_to_cliff >= 0


def test_predictor_handles_empty():
    p = Predictor("Montreal", 70)
    assert p.predict([], race_lap=1) == []


# ----------------------------- replay integration -----------------------------

class _RecBus:
    def __init__(self):
        self.msgs = []

    def publish(self, m):
        self.msgs.append(m)


def test_replay_emits_predictions(canada):
    from backend.ingest.replay_engine import ReplayEngine

    bus = _RecBus()
    eng = ReplayEngine(canada, bus)
    mid = canada.race_start_s + 0.5 * (canada.duration_s - canada.race_start_s)
    eng.seek(mid)
    preds = [m for m in bus.msgs if isinstance(m, PredictionMsg)]
    assert len(preds) >= 10
    drivers = {m.drv for m in preds}
    assert len(drivers) == len(preds)  # one per driver
    # probabilities self-consistent over the field
    assert abs(sum(m.finish.p_points for m in preds) - 10.0) < 0.1


def test_replay_predictions_in_snapshot(canada):
    from backend.ingest.replay_engine import ReplayEngine

    eng = ReplayEngine(canada, _RecBus())
    mid = canada.race_start_s + 0.5 * (canada.duration_s - canada.race_start_s)
    eng.seek(mid)
    snap_bus = _RecBus()
    eng.bus = snap_bus
    eng.snapshot()
    assert any(isinstance(m, PredictionMsg) for m in snap_bus.msgs)
