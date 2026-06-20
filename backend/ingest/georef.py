"""Fit a similarity transform between the telemetry-derived track outline
(asset frame) and the real-world circuit polyline (lon/lat, from the open
f1-circuits dataset, OSM-derived).

Solves rotation + uniform scale + translation + optional reflection +
unknown start offset / direction via complex cross-correlation over all
circular shifts. Output maps asset XY -> lat/lon so the frontend can place
real map tiles underneath the live map.
"""
from __future__ import annotations

import numpy as np

N = 256
EARTH_M_PER_DEG_LAT = 110540.0
EARTH_M_PER_DEG_LON_EQ = 111320.0


def _resample_closed(pts: np.ndarray, n: int) -> np.ndarray:
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, cum[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, cum, closed[:, 0]),
                            np.interp(t, cum, closed[:, 1])])


def solve(asset_pts: np.ndarray, lonlat: np.ndarray) -> dict:
    """asset_pts: (n,2) outline in asset units. lonlat: (m,2) [lon, lat]."""
    lonlat = np.asarray(lonlat, dtype=float)
    lat0 = float(lonlat[:, 1].mean())
    lon0 = float(lonlat[:, 0].mean())
    mx = EARTH_M_PER_DEG_LON_EQ * np.cos(np.radians(lat0))
    my = EARTH_M_PER_DEG_LAT

    G = np.column_stack([(lonlat[:, 0] - lon0) * mx, (lonlat[:, 1] - lat0) * my])
    A = np.asarray(asset_pts, dtype=float)

    A = _resample_closed(A, N)
    G = _resample_closed(G, N)
    ca = A.mean(axis=0)
    cg = G.mean(axis=0)

    z = (A[:, 0] - ca[0]) + 1j * (A[:, 1] - ca[1])
    w = (G[:, 0] - cg[0]) + 1j * (G[:, 1] - cg[1])
    zz = float(np.sum(np.abs(z) ** 2))
    ww = float(np.sum(np.abs(w) ** 2))

    best = None
    for flip in (1.0, -1.0):
        zf = z.real + 1j * flip * z.imag
        fz = np.fft.fft(zf)
        for rev in (False, True):
            wf = w[::-1] if rev else w
            # corr[k] = sum_j wf[j] * conj(zf[j - k])  (circular)
            corr = np.fft.ifft(np.fft.fft(wf) * np.conj(fz))
            k = int(np.argmax(np.abs(corr)))
            a = corr[k] / zz
            err = ww - (np.abs(corr[k]) ** 2) / zz
            if best is None or err < best[0]:
                best = (err, a, flip, rev, k)

    err, a, flip, rev, k = best
    residual_m = float(np.sqrt(max(err, 0.0) / N))
    return {
        "lat0": lat0,
        "lon0": lon0,
        "asset_cx": float(ca[0]),
        "asset_cy": float(ca[1]),
        "geo_cx_m": float(cg[0]),
        "geo_cy_m": float(cg[1]),
        "scale_m_per_unit": float(np.abs(a)),
        "rot_rad": float(np.angle(a)),
        "flip": int(flip),
        "residual_m": residual_m,
    }


def asset_to_lonlat(pts: np.ndarray, g: dict) -> np.ndarray:
    """Reference implementation of the forward map (mirrored in TS)."""
    x = pts[:, 0] - g["asset_cx"]
    y = (pts[:, 1] - g["asset_cy"]) * g["flip"]
    c, s = np.cos(g["rot_rad"]), np.sin(g["rot_rad"])
    qx = g["scale_m_per_unit"] * (c * x - s * y) + g["geo_cx_m"]
    qy = g["scale_m_per_unit"] * (s * x + c * y) + g["geo_cy_m"]
    mx = EARTH_M_PER_DEG_LON_EQ * np.cos(np.radians(g["lat0"]))
    return np.column_stack([g["lon0"] + qx / mx, g["lat0"] + qy / EARTH_M_PER_DEG_LAT])
