"""Plain "state → finish position" GBT baseline (§5.2 sanity check).

Run on the **host**. Trains an XGBoost regressor mapping (grid, recent form,
circuit, constructor) to finishing position from the Kaggle Ergast dump. The
Monte-Carlo simulator must beat this baseline's finish-MAE on the backtest
before it can be trusted; this script prints that baseline number.

    python -m ml.train_finish_baseline --kaggle data/kaggle
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "models" / "artifacts"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kaggle", type=Path, default=ROOT / "data" / "kaggle")
    ap.add_argument("--test-year", type=int, default=2025)
    args = ap.parse_args()
    needed = ["races.csv", "results.csv"]
    if not all((args.kaggle / f).exists() for f in needed):
        print("Kaggle CSVs not found. Download rohanrao/formula-1-world-"
              "championship-1950-2020 into data/kaggle and retry.")
        return

    import numpy as np
    import pandas as pd

    races = pd.read_csv(args.kaggle / "races.csv")
    res = pd.read_csv(args.kaggle / "results.csv")
    df = res.merge(races[["raceId", "year", "round", "circuitId"]], on="raceId")
    df["grid"] = pd.to_numeric(df["grid"], errors="coerce")
    df["finish"] = pd.to_numeric(df["positionOrder"], errors="coerce")
    df = df.dropna(subset=["grid", "finish"])
    df = df[(df["grid"] > 0) & (df["year"] >= 2012)]

    # rolling driver form: mean finish over previous 5 races
    df = df.sort_values(["driverId", "year", "round"])
    df["form"] = (df.groupby("driverId")["finish"]
                  .transform(lambda s: s.shift().rolling(5, min_periods=1).mean()))
    df["form"] = df["form"].fillna(df["finish"].mean())
    feats = ["grid", "form", "circuitId", "constructorId"]
    X = df[feats].to_numpy(float)
    y = df["finish"].to_numpy(float)
    tr = df["year"] < args.test_year
    te = df["year"] == args.test_year
    if te.sum() == 0:
        tr = df["year"] < df["year"].max()
        te = ~tr

    try:
        from xgboost import XGBRegressor
        model = XGBRegressor(n_estimators=400, max_depth=4, learning_rate=0.05)
    except ImportError:
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(n_estimators=300, max_depth=3)
    model.fit(X[tr], y[tr])
    pred = model.predict(X[te])
    mae = float(np.mean(np.abs(pred - y[te])))
    grid_mae = float(np.mean(np.abs(df.loc[te, "grid"] - y[te])))
    print(f"Baseline finish MAE (test {args.test_year}): {mae:.3f}  "
          f"(grid-only baseline {grid_mae:.3f}, n={int(te.sum())})")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump(model, ARTIFACTS / "finish_baseline.joblib")
        print(f"Saved -> {ARTIFACTS/'finish_baseline.joblib'}")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
