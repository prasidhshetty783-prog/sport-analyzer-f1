"""Turn raw OpenF1 rows (live REST/MQTT) into the SAME normalized events the
replay path uses, so live ingest and replay are genuinely interchangeable
producers (Phase 5).

`fixture_store.load_fixture` does this transformation in bulk (vectorised pandas)
for a finished race. Live data trickles in a few rows at a time, so this module
does the *same mapping* per batch — emitting `(t_s, kind, payload)` tuples whose
payloads are byte-for-byte what `RaceState.apply` (and the engine's pos_frame /
car_tel handling) already expect. One semantics, two delivery shapes.

Kinds produced (identical to the fixture event vocabulary):
    pos_frame, car_tel, interval, position, lap_start, lap_done, stint, pit,
    weather, rc
"""
from __future__ import annotations

from datetime import datetime, timezone

# Reuse the single source of truth for these two mappings so live and recorded
# data can never drift apart.
from backend.ingest.fixture_store import DRS_OPEN, _gap

# OpenF1 endpoint -> the (kind, builder) it feeds. Streaming order within a poll
# is the row order from OpenF1 (already date-sorted by our cursor query).
STREAM_ENDPOINTS = ("location", "car_data", "intervals", "position", "laps",
                    "stints", "pit", "weather", "race_control")


def parse_dt(s: str | None) -> datetime | None:
    """Parse an OpenF1 ISO-8601 timestamp ('...Z' or '+00:00') to aware UTC."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _secs(date_str: str | None, t0: datetime) -> float:
    dt = parse_dt(date_str)
    return (dt - t0).total_seconds() if dt else 0.0


def _num(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def normalize(endpoint: str, rows: list[dict], code_of: dict[int, str],
              t0: datetime) -> list[tuple]:
    """Map a batch of raw rows from one OpenF1 endpoint to engine events.

    `code_of` maps driver_number -> 3-letter code; rows for unknown drivers are
    dropped (mirrors the `isin(known)` filter in the fixture loader). `t0` is the
    session time-origin used to express every event in session seconds.
    """
    if not rows:
        return []
    if endpoint == "location":
        return _location(rows, code_of, t0)
    if endpoint == "car_data":
        return _car_data(rows, code_of, t0)
    if endpoint == "intervals":
        return _intervals(rows, code_of, t0)
    if endpoint == "position":
        return _position(rows, code_of, t0)
    if endpoint == "laps":
        return _laps(rows, code_of, t0)
    if endpoint == "stints":
        return _stints(rows, code_of)
    if endpoint == "pit":
        return _pit(rows, code_of, t0)
    if endpoint == "weather":
        return _weather(rows, t0)
    if endpoint == "race_control":
        return _race_control(rows, t0)
    return []


def _location(rows, code_of, t0) -> list[tuple]:
    """Collapse a batch of GPS samples into ONE position frame holding the latest
    valid sample per driver — matches the engine's downsampled pos_frame cadence
    and avoids flooding the bus at the raw ~3.7 Hz x 20 cars rate. Retired/garaged
    cars emit exact (0,0,0); those are invalid GPS and dropped (as at load)."""
    latest: dict[int, tuple] = {}  # number -> (date_str, x, y, z)
    for r in rows:
        n = _num(r.get("driver_number"))
        if n is None or n not in code_of:
            continue
        x, y, z = _f(r.get("x")), _f(r.get("y")), _f(r.get("z"))
        if x == 0 and y == 0:
            continue
        d = r.get("date")
        prev = latest.get(n)
        if prev is None or str(d) >= str(prev[0]):
            latest[n] = (d, x, y, z)
    if not latest:
        return []
    cars = [(code_of[n], xyz[1], xyz[2], xyz[3]) for n, xyz in latest.items()]
    t_s = max(_secs(xyz[0], t0) for xyz in latest.values())
    return [(t_s, "pos_frame", cars)]


def _car_data(rows, code_of, t0) -> list[tuple]:
    """One car_tel per driver, the latest sample in the batch (1 Hz-ish)."""
    latest: dict[int, dict] = {}
    for r in rows:
        n = _num(r.get("driver_number"))
        if n is None or n not in code_of:
            continue
        prev = latest.get(n)
        if prev is None or str(r.get("date")) >= str(prev.get("date")):
            latest[n] = r
    out = []
    for n, r in latest.items():
        out.append((_secs(r.get("date"), t0), "car_tel",
                    (code_of[n], _f(r.get("speed")), _num(r.get("n_gear"), 0),
                     _f(r.get("throttle")), _f(r.get("brake")),
                     _num(r.get("drs"), 0) in DRS_OPEN)))
    return out


def _intervals(rows, code_of, t0) -> list[tuple]:
    out = []
    for r in rows:
        n = _num(r.get("driver_number"))
        if n is None or n not in code_of:
            continue
        out.append((_secs(r.get("date"), t0), "interval",
                    (n, _gap(r.get("gap_to_leader")), _gap(r.get("interval")))))
    return out


def _position(rows, code_of, t0) -> list[tuple]:
    out = []
    for r in rows:
        n, pos = _num(r.get("driver_number")), _num(r.get("position"))
        if n is None or pos is None or n not in code_of:
            continue
        out.append((_secs(r.get("date"), t0), "position", (n, pos)))
    return out


def _laps(rows, code_of, t0) -> list[tuple]:
    """A lap row yields a start event (lap counter) and, once the lap time is
    known, a completion event placed at start + duration (matches the loader)."""
    out = []
    for r in rows:
        n, lap = _num(r.get("driver_number")), _num(r.get("lap_number"))
        if n is None or lap is None or n not in code_of:
            continue
        ds = r.get("date_start")
        if not ds:
            continue
        t = _secs(ds, t0)
        out.append((t, "lap_start", (n, lap)))
        dur = r.get("lap_duration")
        if dur not in (None, ""):
            out.append((t + _f(dur), "lap_done", (n, lap, _f(dur))))
    return out


def _stints(rows, code_of) -> list[tuple]:
    """Stints are applied by lap range (t = -1, like the loader)."""
    out = []
    for r in rows:
        n = _num(r.get("driver_number"))
        ls, le = _num(r.get("lap_start")), _num(r.get("lap_end"))
        if n is None or n not in code_of or ls is None or le is None:
            continue
        out.append((-1.0, "stint",
                    (n, _num(r.get("stint_number"), 0), str(r.get("compound")),
                     ls, le, _num(r.get("tyre_age_at_start"), 0))))
    return out


def _pit(rows, code_of, t0) -> list[tuple]:
    out = []
    for r in rows:
        n = _num(r.get("driver_number"))
        if n is None or n not in code_of:
            continue
        out.append((_secs(r.get("date"), t0), "pit",
                    (n, _num(r.get("lap_number"), 0))))
    return out


def _weather(rows, t0) -> list[tuple]:
    out = []
    for r in rows:
        out.append((_secs(r.get("date"), t0), "weather",
                    (_f(r.get("air_temperature")), _f(r.get("track_temperature")),
                     _f(r.get("humidity")), bool(r.get("rainfall")),
                     _f(r.get("wind_speed")))))
    return out


def _race_control(rows, t0) -> list[tuple]:
    out = []
    for r in rows:
        flag = r.get("flag")
        scope = r.get("scope")
        out.append((_secs(r.get("date"), t0), "rc",
                    (str(r.get("category")),
                     None if flag in (None, "") else str(flag),
                     None if scope in (None, "") else str(scope),
                     str(r.get("message") or ""))))
    return out
