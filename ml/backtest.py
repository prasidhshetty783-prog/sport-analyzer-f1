"""§5.5 Backtest harness — reconstruct race state at lap *k* for recorded races,
run the full prediction stack, and score it against the real outcome.

Unlike the training scripts in this folder, the backtest runs **in-sandbox**: it
consumes the recorded fixtures in ``data/fixtures/`` (no external F1 data needed),
so a scorecard can always be regenerated. It evaluates the Monte-Carlo finish
prediction at several race fractions and reports:

  * MAE of predicted finish position (vs. a persistence baseline)
  * top-3 hit rate (set overlap of predicted vs. actual podium)
  * Spearman rank correlation of predicted order vs. actual

Results are printed and written to ``ml/reports/``.

    python -m ml.backtest                 # all fixtures, default lap fractions
    python -m ml.backtest --fractions 0.25 0.5 0.75
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from backend.ingest.fixture_store import load_fixture
from backend.ingest.replay_engine import ReplayEngine

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"
REPORTS = ROOT / "ml" / "reports"


class _NullBus:
    def publish(self, msg):  # backtest doesn't broadcast
        pass


def actual_classification(fx) -> dict[str, int]:
    """Final finishing position per driver from the fixture's last position
    events (lower = better). Cars that retire keep their last seen position."""
    last_pos: dict[str, tuple[float, int]] = {}
    code = {n: d.code for n, d in fx.drivers.items()}
    for t, kind, p in fx.events:
        if kind == "position":
            drv = code.get(p[0])
            if drv is not None and (drv not in last_pos or t >= last_pos[drv][0]):
                last_pos[drv] = (t, int(p[1]))
    order = sorted(last_pos.items(), key=lambda kv: kv[1][1])
    return {drv: i + 1 for i, (drv, _) in enumerate(order)}


def lap_time(fx, target_lap: int) -> float:
    """Session time at which the race first reaches ``target_lap``."""
    for t, kind, p in fx.events:
        if kind == "lap_start" and int(p[1]) >= target_lap:
            return float(t)
    return fx.duration_s


def spearman(pred: list[int], actual: list[int]) -> float:
    n = len(pred)
    if n < 2:
        return float("nan")
    d2 = sum((a - b) ** 2 for a, b in zip(pred, actual))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def evaluate_fixture(fixture_dir: Path, fractions: list[float]) -> dict:
    fx = load_fixture(fixture_dir)
    actual = actual_classification(fx)
    eng = ReplayEngine(fx, _NullBus())
    rows = []
    for frac in fractions:
        target_lap = max(1, int(round(frac * fx.total_laps)))
        eng.seek(lap_time(fx, target_lap))
        eng._compute_predictions(publish=False)
        preds = eng._last_predictions
        if not preds:
            continue
        # predicted classification = order by expected finish
        pred_order = sorted(preds, key=lambda m: m.finish.exp)
        pred_pos = {m.drv: i + 1 for i, m in enumerate(pred_order)}
        # persistence baseline = current running order at this lap
        inputs = eng.state.predict_inputs()
        base_pos = {c.code: c.position for c in inputs}

        drivers = [m.drv for m in preds if m.drv in actual]
        ae_model = [abs(pred_pos[d] - actual[d]) for d in drivers]
        ae_base = [abs(base_pos.get(d, pred_pos[d]) - actual[d]) for d in drivers]
        pred_top3 = {m.drv for m in pred_order[:3]}
        actual_top3 = {d for d, p in actual.items() if p <= 3}
        sp = spearman([pred_pos[d] for d in drivers], [actual[d] for d in drivers])
        rows.append({
            "fraction": frac,
            "lap": target_lap,
            "flag": eng.state.flag,
            "n_cars": len(drivers),
            "mae_model": round(sum(ae_model) / len(ae_model), 3),
            "mae_persistence": round(sum(ae_base) / len(ae_base), 3),
            "top3_overlap": len(pred_top3 & actual_top3),
            "spearman": round(sp, 3),
        })
    return {
        "fixture": fixture_dir.name,
        "name": fx.name,
        "total_laps": fx.total_laps,
        "evaluations": rows,
        "mae_model": round(_avg(rows, "mae_model"), 3),
        "mae_persistence": round(_avg(rows, "mae_persistence"), 3),
        "top3_hit_rate": round(_avg([{"v": r["top3_overlap"] / 3} for r in rows], "v"), 3),
    }


def _avg(rows, key) -> float:
    vals = [r[key] for r in rows if key in r]
    return sum(vals) / len(vals) if vals else float("nan")


def render_markdown(results: list[dict]) -> str:
    lines = ["# Backtest scorecard — F1 finish prediction", ""]
    lines.append("Finish-position prediction (Model B Monte-Carlo) vs. the actual")
    lines.append("classification, evaluated mid-race on recorded fixtures. The")
    lines.append("persistence baseline simply freezes the running order at lap *k*.")
    lines.append("")
    for r in results:
        lines.append(f"## {r['name']}  ({r['fixture']}, {r['total_laps']} laps)")
        lines.append("")
        lines.append("| race frac | lap | flag | cars | MAE model | MAE persistence | top-3 | Spearman |")
        lines.append("|---:|---:|:--:|---:|---:|---:|:--:|---:|")
        for e in r["evaluations"]:
            lines.append(
                f"| {e['fraction']:.2f} | {e['lap']} | {e['flag']} | {e['n_cars']} "
                f"| {e['mae_model']} | {e['mae_persistence']} | {e['top3_overlap']}/3 "
                f"| {e['spearman']} |")
        lines.append("")
        verdict = ("beats" if r["mae_model"] <= r["mae_persistence"] else "trails")
        lines.append(f"**Summary:** mean MAE {r['mae_model']} ({verdict} persistence "
                     f"{r['mae_persistence']}); top-3 hit rate {r['top3_hit_rate']}.")
        lines.append("")

    if len(results) > 1:
        agg = _overall(results)
        lines.append("## Overall (all fixtures)")
        lines.append("")
        lines.append(f"| fixtures | mean MAE model | mean MAE persistence | top-3 hit rate |")
        lines.append(f"|---:|---:|---:|---:|")
        lines.append(f"| {agg['n']} | {agg['mae_model']} | {agg['mae_persistence']} "
                     f"| {agg['top3_hit_rate']} |")
        verdict = ("beats" if agg["mae_model"] <= agg["mae_persistence"] else "trails")
        lines.append("")
        lines.append(f"**Across {agg['n']} races the simulator {verdict} the "
                     f"persistence baseline** ({agg['mae_model']} vs "
                     f"{agg['mae_persistence']}).")
        lines.append("")

    lines.append("> Add more fixtures (especially a clean race and a chaotic one) to")
    lines.append("> tighten these estimates and to calibrate the SC hazard (Model C).")
    return "\n".join(lines)


def _overall(results: list[dict]) -> dict:
    return {
        "n": len(results),
        "mae_model": round(_avg(results, "mae_model"), 3),
        "mae_persistence": round(_avg(results, "mae_persistence"), 3),
        "top3_hit_rate": round(_avg(results, "top3_hit_rate"), 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fractions", type=float, nargs="+",
                    default=[0.3, 0.5, 0.7])
    ap.add_argument("--fixtures-dir", type=Path, default=FIXTURES)
    args = ap.parse_args()

    dirs = sorted(p.parent for p in args.fixtures_dir.glob("*/meta.json"))
    if not dirs:
        print(f"No fixtures in {args.fixtures_dir} — record one with "
              "scripts/record_fixture.py")
        return

    results = []
    skipped = []
    for d in dirs:
        try:
            r = evaluate_fixture(d, args.fractions)
        except Exception as e:  # noqa: BLE001 - skip broken/empty/future fixtures
            skipped.append((d.name, f"{type(e).__name__}: {e}"))
            continue
        if r and r["evaluations"]:
            results.append(r)
        else:
            skipped.append((d.name, "no usable laps (empty or future race)"))

    if skipped:
        print(f"Skipped {len(skipped)} fixture(s):")
        for name, why in skipped:
            print(f"  - {name}: {why}")
        print()
    if not results:
        print("No evaluable fixtures — nothing to score.")
        return

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "backtest.json").write_text(json.dumps(results, indent=2))
    md = render_markdown(results)
    (REPORTS / "backtest.md").write_text(md)
    print(md)
    print(f"\nScored {len(results)} race(s); skipped {len(skipped)}.")
    print(f"Wrote {REPORTS/'backtest.md'} and {REPORTS/'backtest.json'}")


if __name__ == "__main__":
    main()
