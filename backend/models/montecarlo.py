"""§5.2 Model B — finish-position prediction via Monte-Carlo race simulation.

A per-lap stochastic simulation (not a single regression) so that safety cars
and red flags genuinely move the prediction — the behaviour the brief calls out.
Each simulated lap samples pace from the tyre model, runs a simple pit policy,
resolves traffic/overtaking through a per-circuit difficulty index, draws DNFs
from a reliability hazard, and draws SC/red events from Model C. The field
compresses behind the safety car, which is what visibly reshuffles the odds.

Vectorised over `n_sims` simulations with NumPy; ~1-2 k sims finish well under
the 2 s/refresh budget on a laptop.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from backend.models.hazard import HazardModel
from backend.models.priors import (CLIFF_ACCEL, FUEL_S_PER_KG, circuit_priors,
                                    compound_priors)

# compound code table (keep order stable; index used in the vectorised core)
_COMP_ORDER = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]
_COMP_IDX = {c: i for i, c in enumerate(_COMP_ORDER)}

REF_LAP = 90.0          # nominal lap, cancels in relative ranking
POS_SPREAD = 0.085      # s/lap intrinsic pace spread implied by running order
LAP_NOISE = 0.12        # s, per-lap pace noise (calibrated down from 0.35 so the
                        # field stops randomly reshuffling — see ANCHOR note below)
TRAFFIC_GAP = 1.6       # s, "in dirty air" threshold
STUCK_PENALTY = 0.45    # s/lap a trapped car loses, scaled by overtake difficulty
HOLD_GAP = 0.7          # s, residual gap a denied pass settles at
SC_LAP_TIME = 40.0      # s slower than green under the safety car
SC_DURATION = 4         # laps a deployment typically lasts
SC_PIT_DISCOUNT = 0.55  # pit time-loss multiplier under SC (cheap stop)
DNF_BIG = 1.0e7         # sort-key base for retirements
# Reported expected finish is blended toward the live running order (a strong
# persistence baseline mid-race); trust the sim more the more of the race remains.
# Calibrated against ml/backtest.py (June 2026): on a 15-race sample this cut the
# simulator's mean MAE from 2.96 to ~1.86 (≈ persistence 1.80), up from clearly
# trailing it. w_sim = ANCHOR_MIN + (ANCHOR_MAX - ANCHOR_MIN) * frac_left.
ANCHOR_MIN = 0.08
ANCHOR_MAX = 0.22


@dataclass
class CarSim:
    code: str
    position: int
    gap_s: float | None      # gap to leader in seconds (None/lapped -> derived)
    compound: str | None
    tyre_age: int
    pits: int
    fuel_laps: float         # laps of fuel remaining now
    dnf_rate: float = 0.06   # per-race retirement hazard


@dataclass
class FinishPrediction:
    exp: float
    p_win: float
    p_podium: float
    p_points: float
    dist: list[float]        # P(finish position = 1..N)


class MonteCarloSimulator:
    def __init__(self, circuit: str | None, total_laps: int):
        self.circuit = circuit
        self.total_laps = max(1, int(total_laps))
        pri = circuit_priors(circuit)
        self.difficulty = float(pri["overtaking_difficulty"])
        self.burn = float(pri["fuel_kg_per_lap"])
        self.pit_loss = float(pri["pit_loss_s"])
        self.hazard = HazardModel(circuit, total_laps)
        cp = [compound_priors(c) for c in _COMP_ORDER]
        self._deg = np.array([c["deg"] for c in cp])
        self._cliff = np.array([c["cliff"] for c in cp])
        self._pace = np.array([c["pace"] for c in cp])

    # -- vectorised tyre time-loss vs fresh ---------------------------------
    def _tyre_loss(self, age, code, tmult):
        deg = self._deg[code]
        cliff = self._cliff[code]
        over = np.maximum(0.0, age - cliff)
        return (deg * age + 0.5 * CLIFF_ACCEL * over * over) * tmult

    def simulate(
        self,
        cars: list[CarSim],
        *,
        current_lap: int,
        flag: str = "GREEN",
        rain: bool = False,
        track_temp: float | None = None,
        n_sims: int = 1500,
        seed: int | None = None,
    ) -> dict[str, FinishPrediction]:
        rng = np.random.default_rng(seed)
        n = len(cars)
        if n == 0:
            return {}
        laps_left = max(0, self.total_laps - max(0, int(current_lap)))
        S = int(n_sims)
        _env = os.environ.get("SA_SIMS")  # offline backtest sweeps override n_sims
        if _env:
            S = max(1, int(_env))

        # --- initial state arrays (S, n) -----------------------------------
        order = np.argsort([c.position for c in cars])  # leader first
        ranks = np.empty(n)
        for r, idx in enumerate(order):
            ranks[idx] = r
        pace_off = (ranks - ranks.mean()) * POS_SPREAD          # (n,)

        raw_gaps = np.array([
            c.gap_s if (c.gap_s is not None and np.isfinite(c.gap_s)) else np.nan
            for c in cars
        ], dtype=float)
        # lapped/unknown cars: fall back to rank-based spacing so order holds
        gaps = np.where(np.isfinite(raw_gaps), raw_gaps, ranks * 25.0)

        cum = np.tile(gaps, (S, 1)).astype(float)               # race time so far
        age = np.tile(np.array([float(c.tyre_age) for c in cars]), (S, 1))
        code = np.tile(np.array([_COMP_IDX.get((c.compound or "UNKNOWN").upper(),
                                              5) for c in cars]), (S, 1))
        fuel_laps = np.tile(np.array([c.fuel_laps for c in cars]), (S, 1))
        pits = np.tile(np.array([c.pits for c in cars]), (S, 1)).astype(float)
        alive = np.ones((S, n), dtype=bool)
        death_lap = np.full((S, n), self.total_laps, dtype=float)
        used_second = np.tile(np.array([c.pits > 0 for c in cars]), (S, 1))

        tmult = 1.0
        if track_temp is not None:
            tmult = min(1.6, max(0.8, 1.0 + 0.012 * (track_temp - 35.0)))

        sc_remaining = np.zeros(S, dtype=int)
        restart = np.zeros(S, dtype=int)
        if flag in ("SC", "VSC"):
            sc_remaining[:] = SC_DURATION
        per_lap_dnf = np.array([c.dnf_rate for c in cars]) / max(1, self.total_laps)

        for k in range(laps_left):
            lap_no = current_lap + k + 1
            # --- safety-car deployment (Model C) ---------------------------
            newly = sc_remaining <= 0
            if newly.any():
                p_sc = self.hazard.per_lap_prob(
                    lap_no, rain=rain, recent_incidents=0, sc_active=False)
                trig = (rng.random(S) < p_sc) & newly
                sc_remaining[trig] = SC_DURATION
            sc_now = sc_remaining > 0

            # --- gap to car ahead on track (for traffic) -------------------
            sort_idx = np.argsort(cum, axis=1)
            sorted_cum = np.take_along_axis(cum, sort_idx, axis=1)
            ahead_gap = np.full((S, n), 1e6)
            ahead_gap[:, 1:] = sorted_cum[:, 1:] - sorted_cum[:, :-1]
            gap_ahead = np.empty((S, n))
            np.put_along_axis(gap_ahead, sort_idx, ahead_gap, axis=1)
            in_traffic = gap_ahead < TRAFFIC_GAP

            # --- lap time --------------------------------------------------
            dirty = np.where(in_traffic, 0.30, 0.05)
            tyre = self._tyre_loss(age, code, tmult * (1.0 + 0.25 * dirty))
            fuel_kg = np.maximum(0.0, fuel_laps) * self.burn
            # at a safety-car restart the field is nose-to-tail: more pace
            # variance and easier passing for a couple of laps (real SC drama)
            restarting = (restart > 0)[:, None]
            stuck = (in_traffic * (STUCK_PENALTY * self.difficulty)
                     * np.where(restarting, 0.30, 1.0))
            noise = (rng.normal(0.0, LAP_NOISE, size=(S, n))
                     * np.where(restarting, 2.6, 1.0))
            lap_t = (REF_LAP + pace_off + self._pace[code] + tyre
                     + FUEL_S_PER_KG * fuel_kg + stuck + noise)

            # under SC everyone runs the same slow delta -> field compresses
            lap_t = np.where(sc_now[:, None], REF_LAP + SC_LAP_TIME, lap_t)

            # --- pit policy ------------------------------------------------
            near_cliff = (self._cliff[code] - age) <= 1.0
            laps_remaining = self.total_laps - lap_no
            force_two = (~used_second) & (laps_remaining <= 8) & (~rain)
            cheap = sc_now[:, None] & (age >= 6) & (laps_remaining > 3)
            do_pit = (alive & (laps_remaining > 1)
                      & (near_cliff | cheap | force_two))
            if do_pit.any():
                ploss = self.pit_loss * np.where(sc_now[:, None],
                                                SC_PIT_DISCOUNT, 1.0)
                lap_t = lap_t + np.where(do_pit, ploss, 0.0)
                # fresh tyres: dry alternate (HARD if long to go else MEDIUM),
                # INTER in the rain
                if rain:
                    new_code = np.full((S, n), _COMP_IDX["INTERMEDIATE"])
                else:
                    new_code = np.where(laps_remaining > 20,
                                        _COMP_IDX["HARD"], _COMP_IDX["MEDIUM"])
                code = np.where(do_pit, new_code, code)
                age = np.where(do_pit, 0.0, age)
                pits = np.where(do_pit, pits + 1, pits)
                used_second = used_second | do_pit

            # --- advance ----------------------------------------------------
            cum = cum + np.where(alive, lap_t, 0.0)
            age = age + 1.0
            fuel_laps = fuel_laps - np.where(sc_now[:, None], 0.65, 1.0)
            sc_remaining = np.maximum(0, sc_remaining - 1)

            # field compression on the lap the SC withdraws
            cleared = (sc_remaining == 0) & sc_now
            if cleared.any():
                so = np.argsort(cum, axis=1)
                comp = np.cumsum(np.full((S, n), 1.2), axis=1) - 1.2
                new_cum = np.empty((S, n))
                base = np.take_along_axis(cum, so[:, :1], axis=1)
                np.put_along_axis(new_cum, so, base + comp, axis=1)
                cum = np.where(cleared[:, None], new_cum, cum)
                restart[cleared] = 2

            # --- DNFs ------------------------------------------------------
            dnf = alive & (rng.random((S, n)) < per_lap_dnf[None, :])
            if dnf.any():
                death_lap = np.where(dnf, float(lap_no), death_lap)
                alive = alive & ~dnf
            restart = np.maximum(0, restart - 1)

        # --- classify: finishers by time, retirements by laps completed -----
        finish_key = np.where(alive, cum, DNF_BIG + (self.total_laps - death_lap))
        rank_pos = np.argsort(np.argsort(finish_key, axis=1), axis=1) + 1  # 1..n

        # blend toward the live order — trust the sim more the more of the race is
        # left, but never stray far from the (sticky) running order.
        frac_left = laps_left / self.total_laps if self.total_laps else 0.0
        w_sim = ANCHOR_MIN + (ANCHOR_MAX - ANCHOR_MIN) * min(1.0, max(0.0, frac_left))

        out: dict[str, FinishPrediction] = {}
        for i, c in enumerate(cars):
            p = rank_pos[:, i]
            dist = np.bincount(p, minlength=n + 1)[1:n + 1] / S
            exp = w_sim * float(p.mean()) + (1.0 - w_sim) * float(c.position)
            out[c.code] = FinishPrediction(
                exp=round(exp, 2),
                p_win=round(float((p == 1).mean()), 4),
                p_podium=round(float((p <= 3).mean()), 4),
                p_points=round(float((p <= 10).mean()), 4),
                dist=[round(float(x), 4) for x in dist],
            )
        return out
