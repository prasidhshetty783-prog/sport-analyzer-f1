"""Phase 0 spike: verify OpenF1 REST is reachable and returns the streams we need.

Hits a past session (no auth required for historical data) and prints sample
rows from `location`, `car_data`, and `intervals`.

Usage: python scripts/check_openf1.py [--year 2024] [--country Canada]
"""
from __future__ import annotations

import argparse
from datetime import timedelta

from _common import (hr, iso, openf1_get, parse_iso, resolve_session,
                     sample_rows)


def run(year: int = 2024, country: str = "Canada") -> tuple[bool, str]:
    try:
        session = resolve_session(year, country)
        skey = session["session_key"]
        hr(f"OpenF1: {session['country_name']} {year} — {session['session_name']} "
           f"(session_key={skey})")

        # Small time window mid-race so responses stay tiny.
        start = parse_iso(session["date_start"]) + timedelta(minutes=30)
        end = start + timedelta(seconds=10)
        win = {"date>": iso(start), "date<": iso(end)}

        loc = openf1_get("location", session_key=skey, **win)
        print(f"\nlocation ({len(loc)} rows in 10 s window) sample:")
        print(sample_rows(loc))

        car = openf1_get("car_data", session_key=skey, driver_number=loc[0]["driver_number"] if loc else 1, **win)
        print(f"\ncar_data ({len(car)} rows) sample:")
        print(sample_rows(car))

        inter = openf1_get("intervals", session_key=skey, **{"date>": iso(start), "date<": iso(start + timedelta(minutes=2))})
        print(f"\nintervals ({len(inter)} rows in 2 min window) sample:")
        print(sample_rows(inter))

        ok = bool(loc) and bool(car) and bool(inter)
        detail = (f"{session['country_name']} {year} Race: "
                  f"location={len(loc)}, car_data={len(car)}, intervals={len(inter)} sample rows")
        return ok, detail
    except Exception as e:  # noqa: BLE001
        return False, f"OpenF1 unreachable or schema changed: {e}"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--country", default="Canada")
    a = p.parse_args()
    ok, detail = run(a.year, a.country)
    print(f"\n{'✅' if ok else '❌'} {detail}")
    raise SystemExit(0 if ok else 1)
