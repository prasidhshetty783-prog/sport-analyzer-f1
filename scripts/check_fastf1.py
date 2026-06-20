"""Phase 0 spike: verify FastF1 can load a session with telemetry + weather.

First run downloads session data into data/fastf1_cache/ (can take a few
minutes); subsequent runs are fast.

Usage: python scripts/check_fastf1.py [--year 2024] [--gp Monza] [--session R]
"""
from __future__ import annotations

import argparse

from _common import DATA_DIR, hr


def run(year: int = 2024, gp: str = "Monza", session: str = "R") -> tuple[bool, str]:
    try:
        import fastf1

        cache = DATA_DIR / "fastf1_cache"
        cache.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(cache))

        hr(f"FastF1: {year} {gp} {session}")
        ses = fastf1.get_session(year, gp, session)
        ses.load(telemetry=True, weather=True, messages=True)

        laps = ses.laps
        print(f"\nlaps: {len(laps)} rows; columns include "
              f"{[c for c in ['LapTime', 'Compound', 'TyreLife', 'Stint', 'TrackStatus'] if c in laps.columns]}")
        print(laps[["Driver", "LapNumber", "LapTime", "Compound", "TyreLife"]]
              .dropna().head(3).to_string(index=False))

        fl = laps.pick_fastest()
        tel = fl.get_telemetry()
        need = [c for c in ["Speed", "Throttle", "Brake", "X", "Y", "Z", "Distance"] if c in tel.columns]
        print(f"\nfastest-lap telemetry ({fl['Driver']}): {len(tel)} samples, cols {need}")
        print(tel[need].head(3).to_string(index=False))

        wx = ses.weather_data
        print(f"\nweather: {len(wx)} rows")
        print(wx[["AirTemp", "TrackTemp", "Rainfall", "Humidity"]].head(3).to_string(index=False))

        ci = ses.get_circuit_info()
        print(f"\ncircuit_info: {len(ci.corners)} corners, rotation={ci.rotation}")

        ok = len(laps) > 0 and len(tel) > 0 and len(wx) > 0 and len(ci.corners) > 0
        return ok, (f"{year} {gp} {session}: laps={len(laps)}, telemetry samples={len(tel)}, "
                    f"weather rows={len(wx)}, corners={len(ci.corners)}, rotation={ci.rotation}°")
    except Exception as e:  # noqa: BLE001
        return False, f"FastF1 failed: {e}"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--gp", default="Monza")
    p.add_argument("--session", default="R")
    a = p.parse_args()
    ok, detail = run(a.year, a.gp, a.session)
    print(f"\n{'✅' if ok else '❌'} {detail}")
    raise SystemExit(0 if ok else 1)
