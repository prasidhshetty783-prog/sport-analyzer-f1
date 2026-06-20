"""Track outline derived from the real fixture must be a sane closed loop."""
import math

import pytest

from backend.ingest.track_outline import build_track_asset
from backend.tests.conftest import CANADA, FIXTURES


@pytest.fixture(scope="module")
def asset():
    path = FIXTURES / CANADA
    if not (path / "meta.json").exists():
        pytest.skip("real fixture not present")
    return build_track_asset(path)


def test_outline_shape(asset):
    pts = asset["points"]
    assert len(pts) == 512
    dx = pts[0][0] - pts[-1][0]
    dy = pts[0][1] - pts[-1][1]
    span = asset["bounds"]["max_x"] - asset["bounds"]["min_x"]
    assert math.hypot(dx, dy) < span * 0.05  # closed loop


def test_landscape_rotation(asset):
    b = asset["bounds"]
    assert (b["max_x"] - b["min_x"]) >= (b["max_y"] - b["min_y"])


def test_point_spacing_uniformish(asset):
    pts = asset["points"]
    dists = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
             for i in range(len(pts) - 1)]
    avg = sum(dists) / len(dists)
    assert max(dists) < avg * 3, "resampling left big gaps"


def test_start_finish_on_track_and_unit_dir(asset):
    sf = asset["start_finish"]
    pts = asset["points"]
    nearest = min(math.hypot(p[0] - sf["x"], p[1] - sf["y"]) for p in pts)
    span = asset["bounds"]["max_x"] - asset["bounds"]["min_x"]
    assert nearest < span * 0.02
    assert abs(math.hypot(sf["dx"], sf["dy"]) - 1.0) < 1e-6


def test_live_positions_lie_on_rotated_outline(asset):
    """Regression: car coords rotated by asset.rotation_rad must sit on the
    outline (this is the client's transform; a mismatch puts cars off-track)."""
    import numpy as np
    import pandas as pd

    loc = pd.read_parquet(FIXTURES / CANADA / "location.parquet")
    sample = loc.sample(min(400, len(loc)), random_state=7)

    th = asset["rotation_rad"]
    c, s = np.cos(-th), np.sin(-th)
    rot = np.array([[c, -s], [s, c]])
    pos = sample[["x", "y"]].to_numpy(dtype=float) @ rot.T

    pts = np.asarray(asset["points"], dtype=float)
    d = np.min(np.linalg.norm(pos[:, None, :] - pts[None, :, :], axis=2), axis=1)
    # units are ~decimeters: median within ~6 m of centerline, p90 within 35 m
    # (pit lane / grid samples are the far tail)
    assert np.median(d) < 60, f"median off-track distance {np.median(d):.0f}"
    assert np.percentile(d, 90) < 350, f"p90 off-track distance {np.percentile(d,90):.0f}"
