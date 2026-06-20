"""Georef solver: synthetic round-trip + real Canada fit."""
import json

import numpy as np
import pytest

from backend.ingest.georef import asset_to_lonlat, solve
from backend.tests.conftest import CANADA, FIXTURES


def _curve(n=300):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    # lumpy closed loop (not symmetric, so orientation is unambiguous)
    r = 1000 + 320 * np.cos(2 * t) + 140 * np.sin(5 * t) + 60 * np.cos(3 * t + 1.1)
    return np.column_stack([r * np.cos(t), r * np.sin(t)])


@pytest.mark.parametrize("flip", [1, -1])
@pytest.mark.parametrize("rot", [0.4, -2.2])
def test_synthetic_roundtrip(flip, rot):
    asset = _curve()
    scale = 0.1  # decimeters -> meters
    c, s = np.cos(rot), np.sin(rot)
    pts = asset.copy()
    pts[:, 1] *= flip
    geo_m = scale * pts @ np.array([[c, s], [-s, c]])
    lat0, lon0 = 45.5, -73.52
    mx = 111320 * np.cos(np.radians(lat0))
    lonlat = np.column_stack([lon0 + geo_m[:, 0] / mx, lat0 + geo_m[:, 1] / 110540])
    lonlat = np.roll(lonlat, 57, axis=0)  # unknown start offset

    g = solve(asset, lonlat)
    assert abs(g["scale_m_per_unit"] - scale) / scale < 0.02
    assert g["flip"] == flip
    assert g["residual_m"] < 5.0

    back = asset_to_lonlat(asset, g)
    d_m = np.hypot((back[:, 0] - lonlat[:, 0].mean()) * mx,
                   (back[:, 1] - lonlat[:, 1].mean()) * 110540)
    span = d_m.max()
    assert span > 50  # sanity: the curve is non-degenerate


def test_canada_fit_quality():
    from backend.ingest.track_outline import build_track_asset

    fdir = FIXTURES / CANADA
    if not (fdir / "meta.json").exists():
        pytest.skip("fixture missing")
    meta = json.loads((fdir / "meta.json").read_text())
    key = meta["session"]["circuit_key"]
    geo_path = FIXTURES.parent / "circuit_geo" / f"{key}.json"
    if not geo_path.exists():
        pytest.skip("circuit geo not baked")

    asset = build_track_asset(fdir)
    coords = np.array(json.loads(geo_path.read_text())["coordinates"], dtype=float)
    g = solve(np.array(asset["points"]), coords)

    # telemetry units are ~decimeters; racing line vs centerline => small residual
    assert 0.07 < g["scale_m_per_unit"] < 0.14, g["scale_m_per_unit"]
    assert g["residual_m"] < 25, f"poor fit: {g['residual_m']:.1f} m"
