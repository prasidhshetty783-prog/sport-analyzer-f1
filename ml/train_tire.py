"""Train Model A (tyre degradation) and distil it into served priors (§5.1).

Run on the **host** after `ml/build_training_set.py`. Fits a gradient-boosted
regressor (XGBoost → LightGBM → sklearn, whichever is importable) that predicts
fuel-corrected lap-time delta from compound, tyre life, temps, and dirty-air
share, then distils per-compound linear-deg slope + cliff age and writes them to
``models/artifacts/priors.json`` (compounds section). The served model
(`backend/models/tire.py`) is dependency-free and consumes those coefficients.

    python -m ml.train_tire
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ml._artifacts import merge_priors

ROOT = Path(__file__).resolve().parents[1]
STINTS = ROOT / "data" / "processed" / "stints.parquet"
ARTIFACTS = ROOT / "models" / "artifacts"


def _fit_gbt(X, y):
    """Return (model, predict_fn) for whichever GBT lib is available."""
    try:
        from xgboost import XGBRegressor
        m = XGBRegressor(n_estimators=400, max_depth=5, learning_rate=0.05,
                         subsample=0.8, colsample_bytree=0.8)
        m.fit(X, y)
        return m, m.predict
    except ImportError:
        pass
    try:
        from lightgbm import LGBMRegressor
        m = LGBMRegressor(n_estimators=400, max_depth=5, learning_rate=0.05)
        m.fit(X, y)
        return m, m.predict
    except ImportError:
        from sklearn.ensemble import GradientBoostingRegressor
        m = GradientBoostingRegressor(n_estimators=300, max_depth=3)
        m.fit(X, y)
        return m, m.predict


def distil_compounds(df) -> dict:
    """Per-compound linear deg slope (s/lap) and cliff age from the data."""
    out = {}
    for comp, g in df.groupby("compound"):
        g = g[(g["delta_to_stint_best"] >= 0) & (g["delta_to_stint_best"] < 8)]
        if len(g) < 50:
            continue
        age = g["tyre_life"].to_numpy(float)
        loss = g["delta_to_stint_best"].to_numpy(float)
        # robust linear slope for the pre-cliff region (age <= 75th pct)
        cut = np.percentile(age, 75)
        pre = age <= cut
        slope = float(np.polyfit(age[pre], loss[pre], 1)[0]) if pre.sum() > 10 else 0.04
        # cliff ≈ age where median loss exceeds 2× the linear projection
        ages = np.arange(int(age.min()), int(age.max()) + 1)
        cliff = float(cut)
        for a in ages:
            sel = (age >= a) & (age < a + 2)
            if sel.sum() >= 5 and np.median(loss[sel]) > 2.0 * slope * a + 0.3:
                cliff = float(a)
                break
        out[str(comp).upper()] = {"deg": round(max(0.01, slope), 4),
                                  "cliff": round(max(8.0, cliff), 1)}
    return out


def main() -> None:
    if not STINTS.exists():
        print(f"Missing {STINTS} — run `python -m ml.build_training_set` first.")
        return
    import pandas as pd
    df = pd.read_parquet(STINTS)
    df = df.dropna(subset=["tyre_life", "delta_to_stint_best", "compound"])

    # full GBT (saved for inspection / future serving; distilled coeffs power the app)
    feat = df[["tyre_life", "air_temp", "track_temp"]].fillna(df.median(numeric_only=True))
    feat["rain"] = df["rainfall"].astype(int)
    feat["comp_code"] = df["compound"].astype("category").cat.codes
    model, _ = _fit_gbt(feat.to_numpy(), df["delta_to_stint_best"].to_numpy())

    coeffs = distil_compounds(df)
    merge_priors("compounds", coeffs)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump(model, ARTIFACTS / "tire_gbt.joblib")
        print(f"Saved GBT -> {ARTIFACTS/'tire_gbt.joblib'}")
    except ImportError:
        pass
    print("Distilled compound coefficients:", coeffs)


if __name__ == "__main__":
    main()
