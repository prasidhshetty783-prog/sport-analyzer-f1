"""Compute per-circuit + global priors from the Kaggle/Ergast dump (1950-2024).

Runs anywhere the CSVs are reachable (host, or sandbox if synced). It
**auto-locates** the CSV directory by searching for ``races.csv`` under a few
candidate roots, so it works whether the dump sits in ``data/kaggle``,
``kaggle/``, an ``archive/`` subfolder, or a moved folder — no flag-fiddling.

Keyed by the **OpenF1 ``circuit_short_name``** the runtime actually uses (via
CROSSWALK — the Ergast ``circuitRef`` like "monaco"/"villeneuve" never matched
"Monte Carlo"/"Montreal", so older priors were silently bypassed), it derives:

  * ``overtaking_difficulty`` — from how much grid->finish order changes (2014+);
  * ``pit_loss_s``            — median pit-stop duration (2018+);
  * a global ``dnf_rate``     — share of entries that do not finish (2014+).

These are **field-level merged** into ``models/artifacts/priors.json`` so the
calibrated ``sc_rate`` (ml/calibrate_hazard.py) and ``hazard`` section survive.
Exits 0 with a hint if the CSVs can't be found.

    python -m ml.build_priors                       # auto-locate
    python -m ml.build_priors --kaggle kaggle/data  # explicit root
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "models" / "artifacts"
PRIORS_PATH = ARTIFACTS / "priors.json"
KAGGLE_HINT = ("rohanrao/formula-1-world-championship-1950-2020 — e.g.\n"
               "  kaggle datasets download -d rohanrao/formula-1-world-championship-1950-2020 "
               "-p data/kaggle --unzip")

# Ergast circuitRef -> OpenF1 circuit_short_name (lowercased), for every circuit
# on the current calendar that we hold fixtures for. Unmapped historic circuits
# are ignored (not raced today). Keep in sync with new fixtures.
CROSSWALK: dict[str, str] = {
    "albert_park": "melbourne", "americas": "austin", "bahrain": "sakhir",
    "baku": "baku", "catalunya": "catalunya", "hungaroring": "hungaroring",
    "imola": "imola", "interlagos": "interlagos", "jeddah": "jeddah",
    "losail": "lusail", "las_vegas": "las vegas", "marina_bay": "singapore",
    "miami": "miami", "monaco": "monte carlo", "villeneuve": "montreal",
    "monza": "monza", "rodriguez": "mexico city", "shanghai": "shanghai",
    "silverstone": "silverstone", "spa": "spa-francorchamps",
    "red_bull_ring": "spielberg", "suzuka": "suzuka",
    "yas_marina": "yas marina circuit", "zandvoort": "zandvoort",
}


def _find_csv_dir(start: Path | None) -> Path | None:
    """Locate the directory containing races.csv + results.csv + circuits.csv."""
    roots = [start, ROOT / "data" / "kaggle", ROOT / "kaggle",
             ROOT / "data", ROOT]
    seen: set[Path] = set()
    for r in roots:
        if not r or r in seen or not r.exists():
            continue
        seen.add(r)
        for races in r.rglob("races.csv"):
            d = races.parent
            if (d / "results.csv").exists() and (d / "circuits.csv").exists():
                return d
    return None


def build(d: Path) -> tuple[dict, float]:
    import pandas as pd

    races = pd.read_csv(d / "races.csv")
    results = pd.read_csv(d / "results.csv")
    circuits = pd.read_csv(d / "circuits.csv")
    status = pd.read_csv(d / "status.csv")

    df = (results.merge(races[["raceId", "circuitId", "year"]], on="raceId")
          .merge(circuits[["circuitId", "circuitRef"]], on="circuitId")
          .merge(status, on="statusId"))
    m = df[df["year"] >= 2014].copy()
    m["grid"] = pd.to_numeric(m["grid"], errors="coerce")
    m["pos"] = pd.to_numeric(m["positionOrder"], errors="coerce")
    m = m.dropna(subset=["grid", "pos"])
    m = m[m["grid"] > 0]

    # --- overtaking difficulty: less grid->finish movement => harder passing ---
    moves = (m.assign(delta=(m["grid"] - m["pos"]).abs())
             .groupby("circuitRef")["delta"].mean())
    moves = moves[moves.index.isin(CROSSWALK)]   # only circuits we race today
    lo, hi = float(moves.min()), float(moves.max())

    # --- pit loss: median stationary+lane time, 2018+, sane range ---
    pit = pd.read_csv(d / "pit_stops.csv").merge(
        races[["raceId", "circuitId", "year"]], on="raceId").merge(
        circuits[["circuitId", "circuitRef"]], on="circuitId")
    pit = pit[pit["year"] >= 2018].copy()
    pit["dur"] = pd.to_numeric(pit["duration"], errors="coerce")
    pit = pit[pit["dur"].between(15, 40)]
    pit_med = pit.groupby("circuitRef")["dur"].median()

    circuits_out: dict[str, dict] = {}
    for ref, mv in moves.items():
        key = CROSSWALK[ref]
        ease = (mv - lo) / (hi - lo) if hi > lo else 0.5      # 0..1 higher=easier
        difficulty = round((1.0 - ease) * 0.8 + 0.15, 3)      # keep in [0.15,0.95]
        entry = {"overtaking_difficulty": difficulty}
        if ref in pit_med.index:
            entry["pit_loss_s"] = round(float(pit_med[ref]), 1)
        circuits_out[key] = entry

    # --- global DNF rate: share of entries not classified as finished ---
    fin = m["status"].str.contains("Finish", na=False) | m["status"].str.startswith("+", na=False)
    dnf_rate = round(float((~fin).mean()), 3)
    return circuits_out, dnf_rate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kaggle", type=Path, default=None,
                    help="root to search for the CSVs (auto-locates if omitted)")
    args = ap.parse_args()

    d = _find_csv_dir(args.kaggle)
    if d is None:
        print("Kaggle CSVs not found (need races/results/circuits/status/pit_stops"
              ".csv).\nSearched data/kaggle, kaggle/, data/, project root.\nGet them"
              " via:\n  " + KAGGLE_HINT)
        return
    print(f"Using CSVs in: {d}")
    circuits_out, dnf_rate = build(d)

    # field-level merge so calibrated sc_rate / hazard / compounds survive
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        pri = json.loads(PRIORS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pri = {}
    cir = pri.setdefault("circuits", {})
    for key, vals in circuits_out.items():
        cir.setdefault(key, {}).update(vals)
    pri["dnf"] = {**pri.get("dnf", {}), "default": dnf_rate}
    PRIORS_PATH.write_text(json.dumps(pri, indent=2, sort_keys=True))

    print(f"Wrote {PRIORS_PATH}")
    print(f"  overtaking_difficulty + pit_loss_s for {len(circuits_out)} circuits "
          f"(keyed by circuit_short_name)")
    print(f"  global dnf_rate = {dnf_rate}")
    for key in sorted(circuits_out):
        v = circuits_out[key]
        print(f"    {key:<20} diff={v['overtaking_difficulty']}"
              f"  pit={v.get('pit_loss_s', '—')}")


if __name__ == "__main__":
    main()
