"""REST: session discovery + health. Everything realtime rides the WS."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/sessions")
def sessions(request: Request) -> list[dict]:
    store = request.app.state.store
    out = [asdict(s) for s in store.list_sessions()]
    # Surface the live session only when a paid token is configured; without one
    # the app is replay-only and the picker shows fixtures alone.
    if getattr(request.app.state, "live_enabled", False):
        out.insert(0, {
            "session_id": "live", "name": "● LIVE SESSION", "year": 0,
            "country": "Live", "total_laps": 0, "duration_s": 0.0,
            "mode": "live"})
    return out


_track_cache: dict[str, dict] = {}


def _track_asset(session_id: str, request: Request) -> dict:
    if session_id not in _track_cache:
        from backend.ingest.track_outline import build_track_asset

        store = request.app.state.store
        try:
            _track_cache[session_id] = build_track_asset(store.root / session_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=f"no track asset: {e}")
    return _track_cache[session_id]


@router.get("/track/{session_id}")
def track(session_id: str, request: Request) -> dict:
    """2D outline + start/finish + optional corners for the track map."""
    return _track_asset(session_id, request)


_circuit_cache: dict[str, dict] = {}


@router.get("/circuit/{session_id}")
def circuit(session_id: str, request: Request) -> dict:
    """Track Detail facts: lap count + computed lap length / race distance (from
    the georeferenced outline), plus winners / lap record / first-GP merged from
    data/circuit_facts/<circuit_key>.json when a host run has cached them
    (scripts/fetch_circuit_facts.py). Missing fields come back null and the panel
    shows a dash — never a fake number."""
    import json
    import math

    if session_id in _circuit_cache:
        return _circuit_cache[session_id]

    store = request.app.state.store
    laps = 0
    skey = ""
    name = session_id
    country = None
    year = None
    try:
        fx = store.load(session_id)
        laps = int(fx.total_laps or 0)
        name = fx.name
        s = fx.meta.get("session", {})
        skey = str(s.get("circuit_key", "") or "")
        country = s.get("country_name")
        year = s.get("year")
    except Exception:  # noqa: BLE001
        pass

    length_m = None
    try:
        asset = _track_asset(session_id, request)
        geo = asset.get("geo")
        pts = asset.get("points", [])
        if geo and len(pts) > 2:
            spm = float(geo["scale_m_per_unit"])
            d = 0.0
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                d += math.hypot(b[0] - a[0], b[1] - a[1])
            length_m = round(d * spm)
    except HTTPException:
        pass
    except Exception:  # noqa: BLE001
        pass

    out: dict = {
        "name": name, "country": country, "year": year, "laps": laps,
        "length_m": length_m,
        "distance_m": round(length_m * laps) if (length_m and laps) else None,
        "first_gp": None, "lap_record": None, "lap_record_holder": None,
        "winners": [],
    }
    facts_path = store.root.parent / "circuit_facts" / f"{skey}.json"
    if skey and facts_path.exists():
        try:
            out.update({k: v for k, v in json.loads(facts_path.read_text()).items()
                        if v is not None})
        except Exception:  # noqa: BLE001
            pass
    _circuit_cache[session_id] = out
    return out


_drivers_cache: dict[str, list[dict]] = {}


@router.get("/drivers/{session_id}")
def drivers(session_id: str, request: Request) -> list[dict]:
    """Per-driver roster metadata for the Car Detail panel: code, name, team,
    colour, number and the OpenF1 headshot URL (loaded client-side by the
    browser — the backend never fetches it). Read straight from the fixture's
    drivers parquet so it stays cheap and avoids loading the full race."""
    if session_id not in _drivers_cache:
        import pandas as pd

        store = request.app.state.store
        path = store.root / session_id / "drivers.parquet"
        if not path.exists():
            raise HTTPException(status_code=404, detail="no drivers stream")
        try:
            df = pd.read_parquet(path)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=f"drivers unreadable: {e}")

        def _s(row, col):
            v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
            return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

        out: list[dict] = []
        seen: set[str] = set()
        for r in df.itertuples():
            code = _s(r, "name_acronym")
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({
                "drv": code,
                "num": int(r.driver_number) if not pd.isna(r.driver_number) else 0,
                "full_name": _s(r, "full_name") or code,
                "first_name": _s(r, "first_name"),
                "last_name": _s(r, "last_name"),
                "team": _s(r, "team_name") or "",
                "colour": (_s(r, "team_colour") or "808080").lstrip("#"),
                "headshot_url": _s(r, "headshot_url"),
            })
        _drivers_cache[session_id] = out
    return _drivers_cache[session_id]
