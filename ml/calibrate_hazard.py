"""§5.3 Model C calibration — fit the safety-car hazard from recorded fixtures.

Unlike the FastF1/Kaggle training scripts, this runs **in-sandbox**: it reads the
`race_control` stream already inside `data/fixtures/` (no external data needed).

For every fixture it detects full safety-car *deployments* (`category=="SafetyCar"`
with message "SAFETY CAR DEPLOYED" — not the "IN THIS LAP"/"THROUGH THE PIT LANE"
heads-ups, and not VSC), then:

  1. writes an empirical-Bayes-**shrunk** P(>=1 SC) per circuit into
     `models/artifacts/priors.json`, **keyed by `circuit_short_name`** — the key
     the runtime actually uses (the shipped CIRCUITS dict is keyed "monaco" etc.,
     which never matched "Monte Carlo", so those priors were being bypassed);
  2. fits global per-lap **multipliers** (lap-1 chaos, rain) from the deployment
     laps and writes them to `priors["hazard"]` (consumed by HazardModel);
  3. self-evaluates a **Brier score + reliability table** for "SC within the next
     N laps" against a base-rate baseline, and prints a scorecard.

    python -m ml.calibrate_hazard            # N=10, shrinkage K=6
    python -m ml.calibrate_hazard --within 8 --shrink 8
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"
ARTIFACTS = ROOT / "models" / "artifacts"
REPORTS = ROOT / "ml" / "reports"
MAX_LAP_PROB = 0.55


def _circuit_key(meta: dict) -> str:
    sess = meta.get("session", {})
    name = sess.get("circuit_short_name") or sess.get("country_name") or "unknown"
    return str(name).strip().lower()


def gather() -> list[dict]:
    import pandas as pd

    out = []
    for meta_path in sorted(glob.glob(str(FIXTURES / "*" / "meta.json"))):
        d = Path(meta_path).parent
        rc_path = d / "race_control.parquet"
        if not rc_path.exists():
            continue
        rc = pd.read_parquet(rc_path)
        if "category" not in rc.columns or "message" not in rc.columns:
            continue  # older fixtures without the structured stream
        meta = json.loads(Path(meta_path).read_text())
        key = _circuit_key(meta)

        # total laps from the laps stream (fallback to race_control max)
        total_laps = 0
        laps_path = d / "laps.parquet"
        if laps_path.exists():
            lp = pd.read_parquet(laps_path)
            if "lap_number" in lp.columns and len(lp):
                total_laps = int(lp["lap_number"].max())
        if total_laps <= 0 and "lap_number" in rc.columns:
            total_laps = int(rc["lap_number"].max() or 0)
        if total_laps <= 1:
            continue

        # rain: any measurable rainfall during the race
        rain = False
        w_path = d / "weather.parquet"
        if w_path.exists():
            w = pd.read_parquet(w_path)
            if "rainfall" in w.columns and len(w):
                rain = bool((w["rainfall"].fillna(0) > 0).any())

        sc = rc[rc["category"].astype(str) == "SafetyCar"].copy()
        msg = sc["message"].astype(str).str.upper()
        is_dep = msg.str.contains("DEPLOYED", na=False)
        is_vsc = msg.str.contains("VIRTUAL", na=False) | msg.str.contains("VSC", na=False)
        full = sc[is_dep & ~is_vsc]
        dep_laps = sorted(int(x) for x in full.get("lap_number", []).fillna(1))
        out.append({
            "key": key, "year": meta.get("session", {}).get("year"),
            "total_laps": total_laps, "rain": rain,
            "dep_laps": dep_laps, "n_sc": len(dep_laps),
        })
    return out


def fit(records: list[dict], shrink_k: float):
    per = defaultdict(lambda: {"races": 0, "with_sc": 0, "deps": 0,
                               "green_laps": 0, "dep_laps": []})
    g = {"races": 0, "with_sc": 0, "deps": 0, "green_laps": 0,
         "lap1_deps": 0, "rain_races": 0, "rain_deps": 0, "rain_green": 0,
         "dry_deps": 0, "dry_green": 0}
    for r in records:
        p = per[r["key"]]
        p["races"] += 1; g["races"] += 1
        has = r["n_sc"] > 0
        p["with_sc"] += int(has); g["with_sc"] += int(has)
        p["deps"] += r["n_sc"]; g["deps"] += r["n_sc"]
        p["green_laps"] += r["total_laps"]; g["green_laps"] += r["total_laps"]
        p["dep_laps"] += r["dep_laps"]
        g["lap1_deps"] += sum(1 for L in r["dep_laps"] if L <= 1)
        if r["rain"]:
            g["rain_races"] += 1; g["rain_deps"] += r["n_sc"]; g["rain_green"] += r["total_laps"]
        else:
            g["dry_deps"] += r["n_sc"]; g["dry_green"] += r["total_laps"]

    p0 = g["with_sc"] / max(1, g["races"])               # global P(>=1 SC)
    sc_rate = {}
    for key, p in per.items():
        sc_rate[key] = round((p["with_sc"] + shrink_k * p0) / (p["races"] + shrink_k), 3)

    # per-lap multipliers
    base_nonlap1 = (g["deps"] - g["lap1_deps"]) / max(1, g["green_laps"] - g["races"])
    p_lap1 = g["lap1_deps"] / max(1, g["races"])         # P(SC on lap 1)
    lap1_mult = round(min(8.0, max(1.0, p_lap1 / max(1e-6, base_nonlap1))), 2)
    base_rain = g["rain_deps"] / max(1, g["rain_green"])
    base_dry = g["dry_deps"] / max(1, g["dry_green"])
    rain_mult = round(min(3.0, max(1.0, base_rain / max(1e-6, base_dry))), 2)
    return sc_rate, {"lap1_mult": lap1_mult, "rain_mult": rain_mult}, p0, g


def per_lap_prob(sc_rate, total_laps, lap, rain, hz):
    base = 1.0 - (1.0 - sc_rate) ** (1.0 / max(1, total_laps))
    p = base * hz.get("prob_scale", 1.0)
    if lap <= 1:
        p *= hz["lap1_mult"]
    if rain:
        p *= hz["rain_mult"]
    return min(MAX_LAP_PROB, p)


def brier(records, sc_rate, hz, p0, within: int):
    """In-sample Brier + reliability for 'a full SC starts within the next N laps'."""
    preds, acts = [], []
    for r in records:
        rate = sc_rate.get(r["key"], p0)
        dep = set(r["dep_laps"])
        for k in range(1, r["total_laps"] - 1):
            # P(>=1 deployment in laps k+1..k+within)
            q = 1.0
            for j in range(1, within + 1):
                lap = k + j
                if lap > r["total_laps"]:
                    break
                q *= (1.0 - per_lap_prob(rate, r["total_laps"], lap, r["rain"], hz))
            pred = 1.0 - q
            actual = int(any(k < L <= k + within for L in dep))
            preds.append(pred); acts.append(actual)
    n = len(preds)
    base_rate = sum(acts) / max(1, n)
    pred_mean = sum(preds) / max(1, n)
    bs_model = sum((p - a) ** 2 for p, a in zip(preds, acts)) / max(1, n)
    bs_base = sum((base_rate - a) ** 2 for a in acts) / max(1, n)
    # reliability bins (deciles, since most predictions are small)
    bins = [[0, 0.0, 0] for _ in range(10)]  # [count, pred_sum, pos]
    for p, a in zip(preds, acts):
        b = min(9, int(p * 10))
        bins[b][0] += 1; bins[b][1] += p; bins[b][2] += a
    return n, base_rate, pred_mean, bs_model, bs_base, bins


def render_md(g, p0, hz, sc_rate, raw, n, base_rate, pred_mean, bs_model, bs_base,
              bins, within, shrink) -> str:
    L = ["# Safety-car hazard calibration (Model C)", "",
         f"Fit from {g['races']} recorded fixtures' `race_control` (in-sandbox, "
         "no external data needed).", "",
         f"- Global P(>=1 SC) **{p0:.3f}**; per-lap multipliers lap-1 "
         f"**x{hz['lap1_mult']}**, rain **x{hz['rain_mult']}**, mean-scale "
         f"**x{hz['prob_scale']}**", "",
         f"## SC-within-{within}-laps calibration", "",
         f"- observed **{base_rate:.3f}** vs mean predicted **{pred_mean:.3f}** "
         "(mean-calibrated)",
         f"- Brier **{bs_model:.4f}** vs no-skill baseline **{bs_base:.4f}**  ->  "
         f"skill **{1 - bs_model / bs_base:+.1%}**  ({n} lap-points)", "",
         "| pred bin | n | mean pred | observed |", "|---|---:|---:|---:|"]
    for i, (c, ps, pos) in enumerate(bins):
        if c:
            L.append(f"| {i/10:.1f}-{(i+1)/10:.1f} | {c} | {ps/c:.3f} | {pos/c:.3f} |")
    L += ["", f"## Shrunk per-circuit P(>=1 SC) - empirical-Bayes (K={shrink:g})", "",
          "| circuit | P(>=1 SC) | raw |", "|---|---:|---:|"]
    for key in sorted(sc_rate, key=lambda k: -sc_rate[k]):
        w, tot = raw[key]
        L.append(f"| {key} | {sc_rate[key]:.3f} | {w}/{tot} |")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--within", type=int, default=10)
    ap.add_argument("--shrink", type=float, default=6.0)
    ap.add_argument("--dry-run", action="store_true", help="don't write priors.json")
    args = ap.parse_args()

    records = gather()
    if not records:
        print("No fixtures with a race_control stream found.")
        return
    sc_rate, hz, p0, g = fit(records, args.shrink)
    # mean-calibrate the per-lap base so predicted SC-within-N matches observed
    hz["prob_scale"] = 1.0
    _, base_rate, pred_mean, *_ = brier(records, sc_rate, hz, p0, args.within)
    hz["prob_scale"] = round(min(1.5, max(0.3, base_rate / max(1e-6, pred_mean))), 3)
    n, base_rate, pred_mean, bs_model, bs_base, bins = brier(
        records, sc_rate, hz, p0, args.within)

    print(f"Fixtures used: {g['races']}  |  with >=1 SC: {g['with_sc']}  "
          f"(global P>=1 SC = {p0:.3f})")
    print(f"Per-lap multipliers — lap-1: x{hz['lap1_mult']}   rain: x{hz['rain_mult']}   "
          f"prob_scale: x{hz['prob_scale']}")
    print("\nShrunk per-circuit P(>=1 SC) (empirical-Bayes, K="
          f"{args.shrink:g}):")
    raw = defaultdict(lambda: [0, 0])
    for r in records:
        raw[r["key"]][0] += int(r["n_sc"] > 0); raw[r["key"]][1] += 1
    for key in sorted(sc_rate, key=lambda k: -sc_rate[k]):
        w, tot = raw[key]
        print(f"  {key:<18} {sc_rate[key]:.3f}   (raw {w}/{tot})")

    print(f"\nSC-within-{args.within}-laps calibration ({n} lap-points):")
    print(f"  observed rate: {base_rate:.3f}   mean predicted: {pred_mean:.3f}")
    print(f"  Brier  model: {bs_model:.4f}   baseline(const): {bs_base:.4f}   "
          f"skill: {1 - bs_model / bs_base:+.1%}")
    print("  reliability (pred bin -> observed freq):")
    for i, (c, ps, pos) in enumerate(bins):
        if c:
            print(f"    [{i/10:.1f}-{(i+1)/10:.1f})  n={c:5d}  pred~{ps/c:.3f}  obs={pos/c:.3f}")

    if args.dry_run:
        print("\n--dry-run: priors.json not written.")
        return

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS / "priors.json"
    try:
        pri = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pri = {}
    circuits = pri.setdefault("circuits", {})
    for key, rate in sc_rate.items():
        circuits.setdefault(key, {})["sc_rate"] = rate
    pri["hazard"] = {**pri.get("hazard", {}), **hz, "calibrated_from": g["races"],
                     "within": args.within}
    path.write_text(json.dumps(pri, indent=2))
    print(f"\nWrote {path}  (circuits: {len(sc_rate)} sc_rates + hazard multipliers)")

    REPORTS.mkdir(parents=True, exist_ok=True)
    md = render_md(g, p0, hz, sc_rate, raw, n, base_rate, pred_mean,
                   bs_model, bs_base, bins, args.within, args.shrink)
    (REPORTS / "hazard_calibration.md").write_text(md)
    print(f"Wrote {REPORTS / 'hazard_calibration.md'}")


if __name__ == "__main__":
    main()
