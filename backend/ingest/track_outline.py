"""Derive a 2D track outline from a fixture's position data.

Method: take the cleanest fast lap (no pit-out, post-lap-3, shortest duration
with dense GPS coverage), extract that driver's x/y trace over the lap window,
light-smooth, resample to N points by arc length, then rotate so the track's
principal axis is horizontal (deterministic broadcast-ish framing with no
FastF1 dependency).

Corner numbers overlay only if fetched on the host beforehand:
    python scripts/fetch_circuit_info.py  ->  data/circuit_info/<circuit_key>.json
(the sandbox cannot reach FastF1; the map omits corners gracefully).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

N_POINTS = 512
SMOOTH_WINDOW = 5


def build_track_asset(fixture_dir: Path) -> dict:
    d = Path(fixture_dir)
    laps = pd.read_parquet(d / "laps.parquet")
    loc = pd.read_parquet(d / "location.parquet")
    meta = json.loads((d / "meta.json").read_text())

    candidates = laps[
        laps.lap_duration.notna() & (~laps.is_pit_out_lap.astype(bool))
        & (laps.lap_number > 3)
    ].nsmallest(8, "lap_duration")

    loc = loc.copy()
    loc["ts"] = pd.to_datetime(loc["date"], utc=True, format="ISO8601")

    trace = None
    for r in candidates.itertuples():
        start = pd.to_datetime(r.date_start, utc=True)
        end = start + pd.Timedelta(seconds=float(r.lap_duration))
        seg = loc[(loc.driver_number == r.driver_number)
                  & (loc.ts >= start) & (loc.ts < end)].sort_values("ts")
        if len(seg) >= 150:
            trace = seg
            break
    if trace is None:
        raise RuntimeError("no sufficiently dense clean lap found for outline")

    pts = trace[["x", "y"]].to_numpy(dtype=float)
    zs = trace["z"].to_numpy(dtype=float) if "z" in trace else np.zeros(len(pts))
    pts = _smooth_closed(pts, SMOOTH_WINDOW)
    zs = _smooth_closed_1d(zs, SMOOTH_WINDOW)
    pts, zs = _resample_closed(pts, N_POINTS, extra=zs)

    theta = _principal_angle(pts)
    c, s = np.cos(-theta), np.sin(-theta)
    rot = np.array([[c, -s], [s, c]])
    pts = pts @ rot.T  # z is a vertical axis, unaffected by the in-plane rotation

    sf = pts[0]
    sf_dir = pts[1] - pts[0]
    norm = float(np.linalg.norm(sf_dir)) or 1.0
    sf_dir = sf_dir / norm

    corners = _load_corners(d, meta, rot)
    geo = _load_geo(d, meta, pts)

    mins, maxs = pts.min(axis=0), pts.max(axis=0)
    elevation = (zs - float(zs.min()))  # relative height, same units as x/y
    return {
        "session_id": d.name,
        "points": np.round(pts, 1).tolist(),
        "elevation": np.round(elevation, 1).tolist(),  # per-point height (3D view)
        "bounds": {"min_x": float(mins[0]), "min_y": float(mins[1]),
                   "max_x": float(maxs[0]), "max_y": float(maxs[1])},
        "start_finish": {"x": float(sf[0]), "y": float(sf[1]),
                         "dx": float(sf_dir[0]), "dy": float(sf_dir[1])},
        "corners": corners,
        "geo": geo,
        "rotation_rad": float(theta),
    }


def _smooth_closed(pts: np.ndarray, window: int) -> np.ndarray:
    """Circular moving average (the track is a loop)."""
    n = len(pts)
    pad = window // 2
    ext = np.vstack([pts[-pad:], pts, pts[:pad]])
    kernel = np.ones(window) / window
    return np.column_stack([
        np.convolve(ext[:, 0], kernel, mode="valid"),
        np.convolve(ext[:, 1], kernel, mode="valid"),
    ])[:n]


def _smooth_closed_1d(a: np.ndarray, window: int) -> np.ndarray:
    """Circular moving average of a scalar series (the track is a loop)."""
    n = len(a)
    pad = window // 2
    ext = np.concatenate([a[-pad:], a, a[:pad]])
    kernel = np.ones(window) / window
    return np.convolve(ext, kernel, mode="valid")[:n]


def _resample_closed(pts: np.ndarray, n: int, extra: np.ndarray | None = None):
    """Resample the closed loop to n points by arc length. If ``extra`` (a scalar
    per-point series such as elevation) is given, it is resampled on the same
    parameterisation and returned alongside the points."""
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    targets = np.linspace(0.0, cum[-1], n, endpoint=False)
    out = np.column_stack([
        np.interp(targets, cum, closed[:, 0]),
        np.interp(targets, cum, closed[:, 1]),
    ])
    if extra is None:
        return out
    e_closed = np.concatenate([extra, extra[:1]])
    e_res = np.interp(targets, cum, e_closed)
    return out, e_res


def _principal_angle(pts: np.ndarray) -> float:
    centered = pts - pts.mean(axis=0)
    eigvals, eigvecs = np.linalg.eigh(np.cov(centered.T))
    major = eigvecs[:, int(np.argmax(eigvals))]
    return float(np.arctan2(major[1], major[0]))


def _load_geo(fixture_dir: Path, meta: dict, pts_final: np.ndarray) -> dict | None:
    """Similarity transform asset frame -> lat/lon, if circuit geometry was
    baked (data/circuit_geo/<circuit_key>.json from the f1-circuits dataset).
    Lets the frontend place real map tiles under the live map."""
    key = meta.get("session", {}).get("circuit_key")
    repo_root = Path(fixture_dir).resolve().parents[2]
    path = repo_root / "data" / "circuit_geo" / f"{key}.json"
    if not path.exists():
        return None
    try:
        from backend.ingest.georef import solve

        raw = json.loads(path.read_text())
        coords = np.asarray(raw["coordinates"], dtype=float)
        g = solve(pts_final, coords)
        if g["residual_m"] > 60:  # refuse a bad fit rather than mislead
            print(f"circuit_geo fit too poor ({g['residual_m']:.0f} m), ignoring")
            return None
        g["attribution"] = raw.get("source", "OSM-derived")
        return g
    except Exception as e:  # noqa: BLE001
        print(f"circuit_geo {path} unusable: {e}")
        return None


def _load_corners(fixture_dir: Path, meta: dict, rot: np.ndarray) -> list[dict]:
    key = meta.get("session", {}).get("circuit_key")
    repo_root = Path(fixture_dir).resolve().parents[2]
    path = repo_root / "data" / "circuit_info" / f"{key}.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
        out = []
        for c in raw.get("corners", []):
            p = np.array([float(c["x"]), float(c["y"])]) @ rot.T
            out.append({"n": int(c["number"]), "x": round(float(p[0]), 1),
                        "y": round(float(p[1]), 1)})
        return out
    except Exception as e:  # noqa: BLE001
        print(f"circuit_info {path} unreadable: {e}")
        return []
