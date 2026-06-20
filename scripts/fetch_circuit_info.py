"""Fetch corner numbers/positions for a circuit via FastF1 (host machine only;
the Claude sandbox cannot reach FastF1's data source).

Writes data/circuit_info/<circuit_key>.json; the track map overlays corner
numbers when this file exists and silently omits them otherwise.

Usage: python scripts/fetch_circuit_info.py [--year 2024] [--gp Canada] [--session R]
"""
from __future__ import annotations

import argparse
import json

from _common import DATA_DIR, FIXTURES_DIR, hr


def run(year: int, gp: str, session: str) -> None:
    import fastf1

    cache = DATA_DIR / "fastf1_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache))

    hr(f"circuit_info: {year} {gp} {session}")
    ses = fastf1.get_session(year, gp, session)
    ses.load(telemetry=False, weather=False, messages=False)
    ci = ses.get_circuit_info()

    corners = [{"number": int(c.Number), "x": float(c.X), "y": float(c.Y)}
               for c in ci.corners.itertuples()]

    # match the fixture's circuit_key so the backend can find this file
    circuit_key = None
    for meta_path in FIXTURES_DIR.glob("*/meta.json"):
        meta = json.loads(meta_path.read_text())
        s = meta.get("session", {})
        if s.get("year") == year and gp.lower() in (s.get("country_name", "") or "").lower():
            circuit_key = s.get("circuit_key")
            break
    if circuit_key is None:
        print("! no matching fixture found; saving under circuit name instead")
        circuit_key = gp.lower()

    out_dir = DATA_DIR / "circuit_info"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{circuit_key}.json"
    out.write_text(json.dumps({
        "year": year, "gp": gp, "rotation_deg": float(ci.rotation),
        "corners": corners,
    }, indent=2))
    print(f"✅ wrote {out} ({len(corners)} corners)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--gp", default="Canada")
    p.add_argument("--session", default="R")
    a = p.parse_args()
    run(a.year, a.gp, a.session)
