"""Phase 0 spike: verify Jolpica (Ergast-compatible) API is reachable.

Pulls race results + historical winners — feeds the Track Detail
"previous winners" panel and long-horizon training labels.

Usage: python scripts/check_jolpica.py
"""
from __future__ import annotations

from _common import JOLPICA_BASE, hr, http_get_json


def run() -> tuple[bool, str]:
    try:
        hr("Jolpica (Ergast-compatible)")

        data = http_get_json(f"{JOLPICA_BASE}/2024/9/results.json")  # 2024 round 9 = Canada
        races = data["MRData"]["RaceTable"]["Races"]
        race = races[0]
        podium = [(r["position"], r["Driver"]["code"], r["Constructor"]["name"])
                  for r in race["Results"][:3]]
        print(f"\n{race['season']} {race['raceName']} podium: {podium}")

        # Deep history reachability: 1957 season (pre-Ergast-deprecation data).
        old = http_get_json(f"{JOLPICA_BASE}/1957/results/1.json")
        old_races = old["MRData"]["RaceTable"]["Races"]
        oldest = old_races[0]["raceName"] if old_races else "n/a"
        print(f"1957 winners reachable, first race: {oldest}")

        ok = bool(podium) and bool(old_races)
        return ok, f"{race['raceName']} podium {podium[0][1]}/{podium[1][1]}/{podium[2][1]}; history to 1957 OK"
    except Exception as e:  # noqa: BLE001
        return False, f"Jolpica unreachable: {e}"


if __name__ == "__main__":
    ok, detail = run()
    print(f"\n{'✅' if ok else '❌'} {detail}")
    raise SystemExit(0 if ok else 1)
