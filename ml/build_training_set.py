"""Build the stint-level tyre training table with FastF1 (§3.3).

Run on the **host** — the Cowork/Claude sandbox cannot reach the FastF1 /
livetiming backends (see CLAUDE.md). Produces one row per (driver, lap) with the
features Model A needs, cached as Parquet in ``data/processed/``.

    python -m ml.build_training_set --seasons 2022 2023 2024 2025

Columns: year, round, circuit, driver, team, compound, tyre_life, stint,
lap_number, lap_time_s, fuel_corrected_s, delta_to_stint_best, air_temp,
track_temp, rainfall, track_status, is_pit_lap.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "fastf1_cache"
FUEL_S_PER_KG = 0.030
START_FUEL_KG = 100.0


def build(seasons: list[int]) -> "pd.DataFrame":  # noqa: F821
    import fastf1
    import pandas as pd

    CACHE.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))

    frames = []
    rate_limited = False
    for year in seasons:
        if rate_limited:
            break
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as e:  # noqa: BLE001
            if _is_rate_limit(e):
                rate_limited = True
                break
            print(f"skip schedule {year}: {e}")
            continue
        for _, ev in schedule.iterrows():
            rnd = int(ev["RoundNumber"])
            if rnd <= 0:
                continue
            # The whole per-race body is in the try: a single race that won't
            # load cleanly (future/cancelled round, missing telemetry) is skipped
            # rather than killing the build. messages=True so lap TrackStatus is
            # populated; weather is optional and falls back to NaN.
            try:
                ses = fastf1.get_session(year, rnd, "R")
                ses.load(telemetry=False, weather=True)
                laps = ses.laps
                if laps is None or laps.empty:
                    continue
                total_laps = int(laps["LapNumber"].max())
                try:
                    wx = ses.weather_data
                except Exception:  # noqa: BLE001
                    wx = None
                df = laps[laps["LapTime"].notna()].copy()
                if df.empty:
                    continue
                df["lap_time_s"] = df["LapTime"].dt.total_seconds()
                # fuel correction: a heavier (early-race) car is slower; remove it
                burn = START_FUEL_KG / max(1, total_laps)
                fuel_kg = (total_laps - df["LapNumber"]).clip(lower=0) * burn
                df["fuel_corrected_s"] = df["lap_time_s"] - FUEL_S_PER_KG * fuel_kg
                # delta vs the driver's best fuel-corrected lap in that stint
                df["delta_to_stint_best"] = df.groupby(
                    ["Driver", "Stint"])["fuel_corrected_s"].transform(
                    lambda s: s - s.min())
                df["air_temp"] = _nearest_weather(df, wx, "AirTemp")
                df["track_temp"] = _nearest_weather(df, wx, "TrackTemp")
                df["rainfall"] = _nearest_weather(df, wx, "Rainfall")
                df["rainfall"] = df["rainfall"].fillna(False).astype(bool)
                out = pd.DataFrame({
                    "year": year, "round": rnd,
                    "circuit": ses.event["EventName"],
                    "driver": df["Driver"], "team": df["Team"],
                    "compound": df["Compound"], "tyre_life": df["TyreLife"],
                    "stint": df["Stint"], "lap_number": df["LapNumber"],
                    "lap_time_s": df["lap_time_s"],
                    "fuel_corrected_s": df["fuel_corrected_s"],
                    "delta_to_stint_best": df["delta_to_stint_best"],
                    "air_temp": df["air_temp"], "track_temp": df["track_temp"],
                    "rainfall": df["rainfall"],
                    "track_status": (df["TrackStatus"] if "TrackStatus" in df.columns
                                     else ""),
                    "is_pit_lap": df["PitInTime"].notna() | df["PitOutTime"].notna(),
                })
                frames.append(out)
                print(f"  {year} R{rnd} {ses.event['EventName']}: {len(out)} laps")
            except Exception as e:  # noqa: BLE001 - skip any race that won't load
                if _is_rate_limit(e):
                    print("\nHit FastF1's 500-calls/hour limit — stopping and "
                          "saving what's loaded so far. Wait ~an hour and re-run "
                          "to add more (already-fetched races are cached & free).")
                    rate_limited = True
                    break
                print(f"skip {year} R{rnd}: {type(e).__name__}: {e}")
                continue

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return df, rate_limited


def _is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return "ratelimit" in type(e).__name__.lower() or "calls/h" in s \
        or "rate limit" in s


def _nearest_weather(laps, wx, col):
    import numpy as np
    if wx is None or wx.empty:
        return np.nan
    wt = wx["Time"].dt.total_seconds().to_numpy()
    wv = wx[col].to_numpy()
    lt = laps["LapStartTime"].dt.total_seconds().to_numpy()
    idx = np.clip(np.searchsorted(wt, lt), 0, len(wv) - 1)
    return wv[idx]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024],
                    help="seasons to pull (default: 2024 — one season trains a "
                         "solid model and stays under FastF1's 500/hour limit; "
                         "pass more and it resumes across runs via the cache)")
    args = ap.parse_args()
    df, rate_limited = build(args.seasons)
    if df.empty:
        print("No laps gathered. If you just hit the rate limit, wait ~an hour "
              "and re-run; otherwise check FastF1 connectivity.")
        raise SystemExit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "stints.parquet"
    df.to_parquet(path, index=False)
    n_races = df[["year", "round"]].drop_duplicates().shape[0]
    print(f"\nWrote {len(df):,} laps from {n_races} races -> {path}")
    if rate_limited:
        print("(partial — FastF1 hourly limit hit. train_tire works on this now; "
              "re-run later to add more races.)")


if __name__ == "__main__":
    main()
