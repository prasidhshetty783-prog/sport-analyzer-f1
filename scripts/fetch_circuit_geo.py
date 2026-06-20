"""Download real-world circuit geometry (lat/lon) so the track map can show
the actual surroundings (map tiles) under the live map.

Source: the open f1-circuits dataset (OSM-derived, ODbL) on GitHub.
Run on the host machine (the Claude sandbox blocks GitHub raw):

    python scripts/fetch_circuit_geo.py --gp Canada
    python scripts/fetch_circuit_geo.py --gp Monaco --year 2024

Writes data/circuit_geo/<circuit_key>.json keyed to your recorded fixture.
The backend fits it to the telemetry outline automatically (no restart needed
beyond the asset cache: restart uvicorn or pick the session again).
"""
from __future__ import annotations

import argparse
import json

import requests

from _common import DATA_DIR, FIXTURES_DIR, hr

RAW = "https://raw.githubusercontent.com/bacinger/f1-circuits/master/circuits"

# GP name fragment -> f1-circuits file
CIRCUIT_FILES = {
    "canada": "ca-1978", "monaco": "mc-1929", "great britain": "gb-1948",
    "britain": "gb-1948", "silverstone": "gb-1948", "belgium": "be-1925",
    "spa": "be-1925", "italy": "it-1922", "monza": "it-1922",
    "emilia": "it-1953", "imola": "it-1953", "singapore": "sg-2008",
    "japan": "jp-1962", "suzuka": "jp-1962", "united states": "us-2012",
    "austin": "us-2012", "las vegas": "us-2023", "miami": "us-2022",
    "abu dhabi": "ae-2009", "yas marina": "ae-2009", "yas island": "ae-2009",
    "united arab emirates": "ae-2009", "bahrain": "bh-2002", "saudi": "sa-2021",
    "jeddah": "sa-2021", "australia": "au-1953", "melbourne": "au-1953",
    "china": "cn-2004", "spain": "es-1991", "barcelona": "es-1991",
    "madrid": "es-2026", "hungary": "hu-1986", "netherlands": "nl-1948",
    "zandvoort": "nl-1948", "azerbaijan": "az-2016", "baku": "az-2016",
    "qatar": "qa-2004", "brazil": "br-1940", "sao paulo": "br-1940",
    "mexico": "mx-1962", "austria": "at-1969",
}


def run(gp: str, year: int) -> None:
    hr(f"circuit geometry: {gp}")
    slug = next((v for k, v in CIRCUIT_FILES.items() if k in gp.lower()), None)
    if slug is None:
        raise SystemExit(f"no f1-circuits mapping for '{gp}' — add it to CIRCUIT_FILES")

    resp = requests.get(f"{RAW}/{slug}.geojson", timeout=30)
    resp.raise_for_status()
    feature = resp.json()["features"][0]
    coords = feature["geometry"]["coordinates"]
    props = feature.get("properties", {})

    circuit_key = None
    for meta_path in FIXTURES_DIR.glob("*/meta.json"):
        meta = json.loads(meta_path.read_text())
        s = meta.get("session", {})
        if gp.lower() in (s.get("country_name", "") or "").lower() and \
                (year is None or s.get("year") == year):
            circuit_key = s.get("circuit_key")
            break
    if circuit_key is None:
        print("! no matching fixture found; saving under circuit slug instead")
        circuit_key = slug

    out_dir = DATA_DIR / "circuit_geo"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{circuit_key}.json"
    out.write_text(json.dumps({
        "source": "bacinger/f1-circuits (OSM-derived, ODbL)",
        "circuit": slug,
        "name": props.get("Name", gp),
        "length_m": props.get("length"),
        "coordinates": coords,
    }, indent=1))
    print(f"✅ wrote {out} ({len(coords)} points)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gp", required=True)
    p.add_argument("--year", type=int, default=None)
    a = p.parse_args()
    run(a.gp, a.year)
