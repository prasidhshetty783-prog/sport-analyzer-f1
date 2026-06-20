"""Load recorded race fixtures (data/fixtures/<slug>/, fixture_version 1)
into typed, replay-ready structures.

All timestamps are converted to *session seconds* (float, relative to the
earliest sample in the fixture) so the replay engine never touches wall time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.adapter import SessionInfo

POS_FRAME_S = 0.25   # positions bucketed to 4 Hz (matches ~3.7 Hz source)
TEL_FRAME_S = 1.0    # car telemetry downsampled to 1 Hz for the bus
DRS_OPEN = {10, 12, 14}


@dataclass
class DriverInfo:
    number: int
    code: str
    team: str
    colour: str


@dataclass
class Fixture:
    session_id: str
    name: str
    year: int
    country: str
    total_laps: int
    duration_s: float
    race_start_s: float
    drivers: dict[int, DriverInfo]
    events: list[tuple]  # (t_s, kind, payload) sorted by t_s
    meta: dict = field(repr=False, default_factory=dict)

    def info(self) -> SessionInfo:
        return SessionInfo(self.session_id, self.name, self.year, self.country,
                           self.total_laps, self.duration_s, "replay")


def _to_secs(series: pd.Series, t0: pd.Timestamp) -> np.ndarray:
    dt = pd.to_datetime(series, utc=True, format="ISO8601")
    return (dt - t0).dt.total_seconds().to_numpy()


def load_fixture(fixture_dir: Path) -> Fixture:
    d = Path(fixture_dir)
    meta = json.loads((d / "meta.json").read_text())
    frames = {p.stem: pd.read_parquet(p) for p in d.glob("*.parquet")}

    # A recorded stream can come back empty (a rate-limited window, or an OpenF1
    # endpoint with no rows for that race). An empty parquet has *no columns*,
    # which would blow up the column access below — normalise every expected
    # stream to an empty frame WITH the right columns, so a missing/empty
    # *optional* stream just contributes no events instead of crashing the load.
    expected = {
        "drivers": ["driver_number", "name_acronym", "team_name", "team_colour"],
        "location": ["driver_number", "date", "x", "y", "z"],
        "car_data": ["driver_number", "date", "speed", "n_gear", "throttle",
                     "brake", "drs"],
        "intervals": ["driver_number", "date", "gap_to_leader", "interval"],
        "position": ["driver_number", "date", "position"],
        "laps": ["driver_number", "lap_number", "date_start", "lap_duration"],
        "stints": ["driver_number", "stint_number", "compound", "lap_start",
                   "lap_end", "tyre_age_at_start"],
        "pit": ["driver_number", "date", "lap_number"],
        "weather": ["date", "air_temperature", "track_temperature", "humidity",
                    "rainfall", "wind_speed"],
        "race_control": ["date", "category", "flag", "scope", "message"],
    }
    for name, cols in expected.items():
        f = frames.get(name)
        if f is None or f.shape[1] == 0:
            frames[name] = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})

    # location + drivers are load-critical (time origin + the car roster); an
    # empty either means an unusable / future race — fail clearly so callers skip.
    if frames["location"].empty or frames["drivers"].empty:
        raise ValueError(f"{d.name}: empty location/driver streams "
                         "(unusable or not-yet-run race)")

    drivers = {
        int(r.driver_number): DriverInfo(int(r.driver_number), r.name_acronym,
                                         r.team_name, r.team_colour or "808080")
        for r in frames["drivers"].itertuples()
    }
    known = set(drivers)

    loc = frames["location"]
    t0 = pd.to_datetime(loc["date"], utc=True, format="ISO8601").min()

    events: list[tuple] = []

    # --- positions: bucket to POS_FRAME_S, last sample per driver per bucket
    loc = loc[loc.driver_number.isin(known)].copy()
    # retired/garaged cars emit exact (0,0,0) — invalid GPS, drop it
    loc = loc[~((loc.x == 0) & (loc.y == 0))]
    loc["t"] = _to_secs(loc["date"], t0)
    loc["bucket"] = (loc["t"] // POS_FRAME_S).astype(np.int64)
    last = (loc.groupby(["bucket", "driver_number"], sort=True)
            .last().reset_index())
    code_of = {n: d.code for n, d in drivers.items()}
    b_arr = last["bucket"].to_numpy()
    c_arr = last["driver_number"].map(code_of).to_numpy()
    x_arr = last["x"].to_numpy(dtype=float)
    y_arr = last["y"].to_numpy(dtype=float)
    z_arr = last["z"].to_numpy(dtype=float)
    cuts = np.flatnonzero(np.diff(b_arr)) + 1
    for idx in np.split(np.arange(len(last)), cuts):
        if len(idx) == 0:
            continue
        cars = [(c_arr[i], x_arr[i], y_arr[i], z_arr[i]) for i in idx]
        events.append((float(b_arr[idx[0]]) * POS_FRAME_S, "pos_frame", cars))

    # --- car telemetry: 1 Hz per driver
    car = frames["car_data"]
    car = car[car.driver_number.isin(known)].copy()
    car["t"] = _to_secs(car["date"], t0)
    car["bucket"] = (car["t"] // TEL_FRAME_S).astype(np.int64)
    tel = (car.groupby(["bucket", "driver_number"], sort=True)
           .last().reset_index())
    for r in tel.itertuples():
        events.append((float(r.bucket) * TEL_FRAME_S, "car_tel",
                       (code_of[int(r.driver_number)], float(r.speed),
                        int(r.n_gear), float(r.throttle), float(r.brake),
                        int(r.drs) in DRS_OPEN)))

    # --- intervals (gap strings preserved: "3.2" or "+1 LAP")
    iv = frames["intervals"]
    iv = iv[iv.driver_number.isin(known)].copy()
    iv["t"] = _to_secs(iv["date"], t0)
    for r in iv.itertuples():
        events.append((float(r.t), "interval",
                       (int(r.driver_number), _gap(r.gap_to_leader), _gap(r.interval))))

    # --- running order
    pos = frames["position"]
    pos = pos[pos.driver_number.isin(known)].copy()
    pos["t"] = _to_secs(pos["date"], t0)
    for r in pos.itertuples():
        events.append((float(r.t), "position", (int(r.driver_number), int(r.position))))

    # --- laps: start events (lap counter) + completion events (last-lap time)
    laps = frames["laps"].copy()
    laps = laps[laps.driver_number.isin(known)]
    laps["t"] = _to_secs(laps["date_start"], t0)
    for r in laps.itertuples():
        # A lap with no usable start time (NaT date_start) can't be placed on the
        # clock; a NaN event time would poison the global sort below (NaN compares
        # False, so Timsort leaves the list partially ordered and the engine's
        # bisect/seek then jump to the end of the race). Skip such rows.
        if pd.isna(r.t) or pd.isna(r.lap_number):
            continue
        events.append((float(r.t), "lap_start", (int(r.driver_number), int(r.lap_number))))
        if pd.notna(r.lap_duration):
            events.append((float(r.t) + float(r.lap_duration), "lap_done",
                           (int(r.driver_number), int(r.lap_number), float(r.lap_duration))))

    # --- stints (applied by lap range, but emitted as events at load so the
    #     state machine owns the bookkeeping). OpenF1 occasionally emits a stint
    #     row with NaN lap_start/lap_end (malformed) — skip those; default a
    #     missing tyre_age_at_start / stint_number to 0.
    for r in frames["stints"].itertuples():
        if int(r.driver_number) not in known:
            continue
        if pd.isna(r.lap_start) or pd.isna(r.lap_end):
            continue
        stint_no = 0 if pd.isna(r.stint_number) else int(r.stint_number)
        age0 = 0 if pd.isna(r.tyre_age_at_start) else int(r.tyre_age_at_start)
        events.append((-1.0, "stint",
                       (int(r.driver_number), stint_no, str(r.compound),
                        int(r.lap_start), int(r.lap_end), age0)))

    # --- pit stops
    pit = frames["pit"].copy()
    pit = pit[pit.driver_number.isin(known)]
    pit["t"] = _to_secs(pit["date"], t0)
    for r in pit.itertuples():
        events.append((float(r.t), "pit", (int(r.driver_number), int(r.lap_number))))

    # --- race control
    rc = frames["race_control"].copy()
    rc["t"] = _to_secs(rc["date"], t0)
    for r in rc.itertuples():
        events.append((float(r.t), "rc",
                       (str(r.category), None if pd.isna(r.flag) else str(r.flag),
                        None if pd.isna(r.scope) else str(r.scope), str(r.message))))

    # --- weather
    wx = frames["weather"].copy()
    wx["t"] = _to_secs(wx["date"], t0)
    for r in wx.itertuples():
        events.append((float(r.t), "weather",
                       (float(r.air_temperature), float(r.track_temperature),
                        float(r.humidity), bool(r.rainfall), float(r.wind_speed))))

    # Defensive: any non-finite event time corrupts the sort (and therefore the
    # replay engine's bisect-based seek), so drop them before ordering. NaN is the
    # only float that is not equal to itself.
    events = [e for e in events if e[0] == e[0]]
    events.sort(key=lambda e: e[0])
    duration = events[-1][0] if events else 0.0
    race_start = next((t for t, kind, _ in events if kind == "lap_start"), 0.0)
    session = meta.get("session", {})
    name = (meta.get("meeting", {}).get("meeting_official_name")
            or f"{session.get('country_name', '?')} {session.get('year', '?')} Race").strip()

    return Fixture(
        session_id=d.name,
        name=name,
        year=int(session.get("year", 0)),
        country=str(session.get("country_name", "?")),
        total_laps=int(laps["lap_number"].max()) if len(laps) else 0,
        duration_s=float(duration),
        race_start_s=float(race_start),
        drivers=drivers,
        events=events,
        meta=meta,
    )


def _gap(v) -> str | None:
    """Gaps arrive as float, numeric string, '+1 LAP', or null."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v)
    return None if s in ("nan", "None", "") else s


class FixtureStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._cache: dict[str, Fixture] = {}

    def list_sessions(self) -> list[SessionInfo]:
        """Lightweight listing for the session picker — reads meta.json ONLY,
        never the (large) parquet streams, so this stays fast with 80+ fixtures.
        Skips not-yet-run / empty races (no location rows)."""
        out = []
        for meta_path in sorted(self.root.glob("*/meta.json")):
            try:
                meta = json.loads(meta_path.read_text())
                s = meta.get("session", {})
                if meta.get("streams", {}).get("location", 0) == 0:
                    continue  # empty / future fixture — not selectable
                name = (meta.get("meeting", {}).get("meeting_official_name")
                        or f"{s.get('country_name', '?')} {s.get('year', '?')} Race").strip()
                out.append(SessionInfo(
                    meta_path.parent.name, name, int(s.get("year", 0) or 0),
                    str(s.get("country_name", "?")), 0, 0.0, "replay"))
            except Exception as e:  # noqa: BLE001 - skip broken fixtures
                print(f"fixture {meta_path.parent.name} meta unreadable: {e}")
        return out

    def load(self, session_id: str) -> Fixture:
        if session_id not in self._cache:
            self._cache[session_id] = load_fixture(self.root / session_id)
        return self._cache[session_id]
