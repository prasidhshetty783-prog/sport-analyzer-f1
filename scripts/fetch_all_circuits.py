"""Batch-fetch real-world track geometry (map tiles) + corner numbers for EVERY
recorded circuit, so all track maps get the full Canada-style treatment.

**Host only** (the sandbox blocks GitHub-raw + FastF1). Geometry comes from the
open f1-circuits dataset — a light GitHub fetch with no rate limit. Corners come
from FastF1, which has a 500-calls/hour cap, so the corner pass stops cleanly and
is resumable. Files are written keyed by ``circuit_key`` and de-duplicated, so a
circuit shared across seasons is fetched once; existing files are skipped.

    python scripts/fetch_all_circuits.py                 # geometry + corners
    python scripts/fetch_all_circuits.py --skip-corners  # tiles only (no FastF1)
    python scripts/fetch_all_circuits.py --skip-geo      # corners only

After it runs, restart uvicorn (or just pick a race again) so the map asset
cache rebuilds with the new geometry/corners.
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict

import requests

from _common import DATA_DIR, FIXTURES_DIR, hr
from fetch_circuit_geo import CIRCUIT_FILES, RAW

GEO_DIR = DATA_DIR / "circuit_geo"
INFO_DIR = DATA_DIR / "circuit_info"


def unique_circuits() -> "OrderedDict[int, dict]":
    """circuit_key -> {year, hints[]} for every recorded fixture (deduped)."""
    out: OrderedDict[int, dict] = OrderedDict()
    for mp in sorted(FIXTURES_DIR.glob("*/meta.json")):
        try:
            s = json.loads(mp.read_text()).get("session", {})
        except Exception:  # noqa: BLE001
            continue
        key = s.get("circuit_key")
        if key is None or key in out:
            continue
        # most-specific first: circuit/location beat the country name, so the
        # three USA races (COTA/Miami/Vegas) and Monza-vs-Imola disambiguate
        # correctly instead of all collapsing onto the country's first circuit.
        hints = [h for h in (s.get("circuit_short_name"), s.get("location"),
                             s.get("country_name")) if h]
        out[key] = {"year": s.get("year"), "hints": hints}
    return out


def _slug_for(hints: list[str]):
    """Resolve an f1-circuits slug from any of the circuit's name hints."""
    for h in hints:
        hl = h.lower()
        for frag, slug in CIRCUIT_FILES.items():
            if frag in hl:
                return slug, h
    return None, None


def fetch_geo(key: int, hints: list[str]) -> str:
    slug, matched = _slug_for(hints)
    if slug is None:
        return "nomap"
    resp = requests.get(f"{RAW}/{slug}.geojson", timeout=30)
    resp.raise_for_status()
    feat = resp.json()["features"][0]
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    (GEO_DIR / f"{key}.json").write_text(json.dumps({
        "source": "bacinger/f1-circuits (OSM-derived, ODbL)",
        "circuit": slug,
        "name": feat.get("properties", {}).get("Name", matched),
        "length_m": feat.get("properties", {}).get("length"),
        "coordinates": feat["geometry"]["coordinates"],
    }, indent=1))
    return "ok"


def fetch_corners(key: int, year: int, hints: list[str]):
    import fastf1

    cache = DATA_DIR / "fastf1_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache))
    last: Exception | None = None
    for h in hints:
        try:
            ses = fastf1.get_session(year, h, "R")
            ses.load(telemetry=False, weather=False, messages=False)
            ci = ses.get_circuit_info()
            corners = [{"number": int(c.Number), "x": float(c.X), "y": float(c.Y)}
                       for c in ci.corners.itertuples()]
            INFO_DIR.mkdir(parents=True, exist_ok=True)
            (INFO_DIR / f"{key}.json").write_text(json.dumps({
                "year": year, "gp": h, "rotation_deg": float(ci.rotation),
                "corners": corners,
            }, indent=2))
            return len(corners)
        except Exception as e:  # noqa: BLE001
            if _is_rate_limit(e):
                raise
            last = e
            continue
    raise last or RuntimeError("no matching FastF1 session for hints")


def _is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return "ratelimit" in type(e).__name__.lower() or "calls/h" in s \
        or "rate limit" in s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-corners", action="store_true",
                    help="fetch geometry/tiles only (no FastF1, no rate limit)")
    ap.add_argument("--skip-geo", action="store_true",
                    help="fetch corners only")
    args = ap.parse_args()

    circuits = unique_circuits()
    if not circuits:
        print("No fixtures found in data/fixtures/.")
        return
    hr(f"{len(circuits)} unique circuits across your fixtures")

    geo_n = corner_n = 0
    rate_stopped = False
    for key, c in circuits.items():
        label = (c["hints"][0] if c["hints"] else str(key))
        if not args.skip_geo and not (GEO_DIR / f"{key}.json").exists():
            try:
                if fetch_geo(key, c["hints"]) == "ok":
                    geo_n += 1
                    print(f"  geo     {label} (key {key})  ✅")
                else:
                    print(f"  geo     {label}: no f1-circuits mapping  –")
            except Exception as e:  # noqa: BLE001
                print(f"  geo     {label}: {e}  !")
        if (not args.skip_corners and not rate_stopped
                and not (INFO_DIR / f"{key}.json").exists()):
            try:
                n = fetch_corners(key, c["year"], c["hints"])
                corner_n += 1
                print(f"  corners {label}: {n} corners  ✅")
            except Exception as e:  # noqa: BLE001
                if _is_rate_limit(e):
                    print("\nFastF1 500-calls/hour limit reached — stopping the "
                          "corner pass. Geometry keeps going; re-run later to "
                          "finish corners (already-fetched ones are skipped).")
                    rate_stopped = True
                else:
                    print(f"  corners {label}: {e}  !")

    hr(f"done — {geo_n} new geometry file(s), {corner_n} new corner file(s)")
    print("Restart uvicorn (or pick a race again) to see the updated maps.")


if __name__ == "__main__":
    main()
