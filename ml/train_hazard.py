"""Estimate per-circuit safety-car / red-flag rates for Model C (§5.3).

Run on the **host**. Scans FastF1 race-control messages across seasons, counts
the fraction of races at each circuit that saw at least one safety car, and
writes the result into ``models/artifacts/priors.json`` (circuits section,
``sc_rate``). The served hazard model turns this into a per-lap deployment
probability with rain / lap-1 / incident multipliers.

    python -m ml.train_hazard --seasons 2018 2019 2020 2021 2022 2023 2024 2025
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from ml._artifacts import merge_priors

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "fastf1_cache"


def _norm(name: str) -> str:
    return str(name).strip().lower().split(" grand")[0].strip()


def _is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return "ratelimit" in type(e).__name__.lower() or "calls/h" in s \
        or "rate limit" in s


def build(seasons: list[int]) -> "tuple[dict, bool]":
    import fastf1

    CACHE.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))
    races = defaultdict(int)
    sc = defaultdict(int)
    rate_limited = False

    for year in seasons:
        if rate_limited:
            break
        try:
            sched = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as e:  # noqa: BLE001
            if _is_rate_limit(e):
                rate_limited = True
                break
            print(f"skip schedule {year}: {e}")
            continue
        for _, ev in sched.iterrows():
            rnd = int(ev["RoundNumber"])
            if rnd <= 0:
                continue
            try:
                ses = fastf1.get_session(year, rnd, "R")
                ses.load(telemetry=False, weather=False, messages=True)
            except Exception as e:  # noqa: BLE001
                if _is_rate_limit(e):
                    print("\nHit FastF1's 500-calls/hour limit — stopping and "
                          "keeping the rates gathered so far. Wait ~an hour and "
                          "re-run; cached races reload free, so it resumes.")
                    rate_limited = True
                    break
                print(f"skip {year} R{rnd}: {type(e).__name__}: {e}")
                continue
            key = _norm(ev["EventName"])
            races[key] += 1
            msgs = ses.race_control_messages
            if msgs is None or msgs.empty:
                continue
            text = " ".join(msgs.get("Message", []).astype(str)).upper()
            if "SAFETY CAR" in text or "RED FLAG" in text:
                sc[key] += 1
            print(f"  {year} R{rnd} {key}: sc={'Y' if sc[key] else 'n'}")

    out = {}
    for key, n in races.items():
        if n:
            out[key] = {"sc_rate": round(sc[key] / n, 3)}
    return out, rate_limited


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+",
                    default=list(range(2018, 2026)))
    args = ap.parse_args()
    try:
        values, rate_limited = build(args.seasons)
    except ImportError:
        print("fastf1 not installed — `pip install fastf1`. Using shipped defaults.")
        return
    if values:
        merge_priors("circuits", values)
        print(f"Computed SC rate for {len(values)} circuits.")
        if rate_limited:
            print("(partial — FastF1 hourly limit hit. Re-run later to refine "
                  "rates with more seasons; cached races are free.)")
    else:
        print("No race-control data gathered (rate limit or connectivity). "
              "Shipped defaults remain in effect.")


if __name__ == "__main__":
    main()
