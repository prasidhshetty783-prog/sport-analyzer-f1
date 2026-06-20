"""Fetch per-circuit facts (past winners, first GP, fastest race lap) from
Jolpica (the Ergast successor) for every recorded fixture, so the 3D Track
Detail panel can show real records.

**Host only** (the Claude sandbox blocks api.jolpi.ca). Writes
``data/circuit_facts/<circuit_key>.json`` keyed to your fixtures; the backend
``GET /api/circuit/{id}`` merges these over the computed lap/length/distance.
Missing data just leaves a field null (the panel shows a dash) — nothing is
fabricated.

    python scripts/fetch_circuit_facts.py
    python scripts/fetch_circuit_facts.py --since 2014   # winners from 2014+

Notes: Jolpica/Ergast fastest-lap data starts ~2004, so "lap record" here is the
fastest *race* lap we can find in that window — labelled accordingly in the UI.
"""
from __future__ import annotations

import argparse
import json
import time

import requests

from _common import DATA_DIR, FIXTURES_DIR, hr

BASE = "https://api.jolpi.ca/ergast/f1"
OUT_DIR = DATA_DIR / "circuit_facts"


def _get(path: str, params: dict | None = None) -> dict | None:
    for attempt in range(4):
        try:
            r = requests.get(f"{BASE}/{path}", params={**(params or {}), "format": "json"},
                             timeout=30)
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            r.raise_for_status()
            return r.json().get("MRData", {})

        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                print(f"  ! {path}: {e}")
                return None
            time.sleep(1 + attempt)
    return None


def load_circuits() -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        d = _get("circuits.json", {"limit": 100, "offset": offset})
        if not d:
            break
        circuits = d.get("CircuitTable", {}).get("Circuits", [])
        out.extend(circuits)
        total = int(d.get("total", 0))
        offset += 100
        if offset >= total or not circuits:
            break
        time.sleep(0.3)
    return out


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def match_circuit(circuits: list[dict], country: str, hints: list[str]) -> dict | None:
    """Best-effort match of an OpenF1 fixture to an Ergast circuit by country +
    name/locality token overlap."""
    cands = [c for c in circuits
             if _norm(country) in _norm(c.get("Location", {}).get("country", ""))
             or _norm(c.get("Location", {}).get("country", "")) in _norm(country)]
    pool = cands or circuits
    best, best_score = None, 0
    for c in pool:
        loc = c.get("Location", {})
        text = _norm(c.get("circuitName", "") + loc.get("locality", "") + loc.get("country", ""))
        score = sum(1 for h in hints if h and _norm(h) and _norm(h) in text)
        if c in cands:
            score += 1
        if score > best_score:
            best, best_score = c, score
    return best or (cands[0] if cands else None)


def fetch_facts(circuit_id: str, since: int) -> dict:
    facts: dict = {"first_gp": None, "winners": [], "lap_record": None,
                   "lap_record_holder": None}
    # winners (finish position 1) across all seasons at this circuit
    d = _get(f"circuits/{circuit_id}/results/1.json", {"limit": 100})
    races = (d or {}).get("RaceTable", {}).get("Races", [])
    seasons = []
    winners = []
    for r in races:
        yr = int(r.get("season", 0))
        seasons.append(yr)
        res = r.get("Results", [{}])[0]
        drv = res.get("Driver", {})
        winners.append({"year": yr,
                        "driver": f"{drv.get('givenName','')} {drv.get('familyName','')}".strip(),
                        "constructor": res.get("Constructor", {}).get("name", "")})
    if seasons:
        facts["first_gp"] = min(seasons)
    facts["winners"] = sorted([w for w in winners if w["year"] >= since],
                              key=lambda w: w["year"], reverse=True)[:12]
    # fastest race lap we can find (Ergast fastest-lap data ~2004+)
    best = None
    for yr in range(max(since, 2004), 2026):
        rd = _get(f"{yr}/circuits/{circuit_id}/results.json", {"limit": 60})
        for r in (rd or {}).get("RaceTable", {}).get("Races", []):
            for res in r.get("Results", []):
                fl = res.get("FastestLap", {}).get("Time", {}).get("time")
                if fl and (best is None or fl < best[0]):
                    drv = res.get("Driver", {})
                    best = (fl, f"{drv.get('givenName','')} {drv.get('familyName','')}".strip(), yr)
        time.sleep(0.25)
    if best:
        facts["lap_record"] = best[0]
        facts["lap_record_holder"] = f"{best[1]} ({best[2]})"
    return facts


def unique_fixtures() -> dict:
    out: dict = {}
    for mp in sorted(FIXTURES_DIR.glob("*/meta.json")):
        try:
            s = json.loads(mp.read_text()).get("session", {})
        except Exception:  # noqa: BLE001
            continue
        key = s.get("circuit_key")
        if key is None or key in out:
            continue
        out[key] = {
            "country": s.get("country_name", ""),
            "hints": [h for h in (s.get("circuit_short_name"), s.get("location")) if h],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2010)
    args = ap.parse_args()

    fixtures = unique_fixtures()
    if not fixtures:
        print("No fixtures found.")
        return
    hr(f"circuit facts for {len(fixtures)} circuits (Jolpica)")
    circuits = load_circuits()
    if not circuits:
        print("Could not load circuit list from Jolpica.")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    for key, info in fixtures.items():
        out_path = OUT_DIR / f"{key}.json"
        if out_path.exists():
            continue
        c = match_circuit(circuits, info["country"], info["hints"])
        label = info["hints"][0] if info["hints"] else info["country"]
        if not c:
            print(f"  {label} (key {key}): no Ergast match  -")
            continue
        facts = fetch_facts(c["circuitId"], args.since)
        facts["circuit"] = c.get("circuitName")
        out_path.write_text(json.dumps(facts, indent=2))
        done += 1
        print(f"  {label}: {c['circuitName']} — {len(facts['winners'])} winners, "
              f"first GP {facts['first_gp']}  OK")
        time.sleep(0.4)
    hr(f"done — wrote {done} circuit-facts file(s) to {OUT_DIR}")


if __name__ == "__main__":
    main()
