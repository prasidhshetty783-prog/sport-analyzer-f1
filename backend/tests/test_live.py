"""Phase 5 live mode — normalizer, REST source, and the LiveClient producer.

Everything runs offline: the REST source takes an injected `http_get`, and the
LiveClient is driven by a `MockLiveSource` (and, for the reality check, by the
recorded Canada race replayed as if it were streaming). No network, no token.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.core.event_bus import EventBus
from backend.ingest.live_client import LiveClient
from backend.ingest.live_source import (LiveSource, OpenF1MqttSource,
                                        OpenF1RestSource, make_live_source)
from backend.ingest.openf1_normalize import normalize

BASE = datetime(2024, 6, 9, 18, 0, 0, tzinfo=timezone.utc)
CODE_OF = {1: "VER", 4: "NOR", 63: "RUS"}
ROSTER = [
    {"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull", "team_colour": "3671C6"},
    {"driver_number": 4, "name_acronym": "NOR", "team_name": "McLaren", "team_colour": "FF8000"},
    {"driver_number": 63, "name_acronym": "RUS", "team_name": "Mercedes", "team_colour": "27F4D2"},
]
SESSION = {"session_key": 9999, "date_start": "2024-06-09T18:00:00Z",
           "date_end": "2024-06-09T20:00:00Z", "year": 2024,
           "country_name": "Canada", "circuit_short_name": "Montreal",
           "circuit_key": 23}


def iso(sec: float) -> str:
    return (BASE + timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")


# ───────────────────────── normalizer ─────────────────────────

def test_location_keeps_latest_and_drops_zero_and_unknown():
    rows = [
        {"driver_number": 1, "date": iso(5), "x": 10, "y": 20, "z": 0},
        {"driver_number": 1, "date": iso(8), "x": 11, "y": 21, "z": 0},  # newer wins
        {"driver_number": 4, "date": iso(7), "x": 0, "y": 0, "z": 0},     # (0,0) -> drop
        {"driver_number": 99, "date": iso(7), "x": 5, "y": 5, "z": 0},    # unknown -> drop
    ]
    ev = normalize("location", rows, CODE_OF, BASE)
    assert len(ev) == 1
    t_s, kind, cars = ev[0]
    assert kind == "pos_frame" and t_s == 8.0
    by = {c[0]: c for c in cars}
    assert set(by) == {"VER"}           # NOR dropped (0,0); unknown dropped
    assert by["VER"][1] == 11.0          # latest x


def test_car_data_drs_open_set_and_latest():
    rows = [
        {"driver_number": 1, "date": iso(4), "speed": 280, "n_gear": 6, "throttle": 90, "brake": 0, "drs": 0},
        {"driver_number": 1, "date": iso(6), "speed": 300, "n_gear": 7, "throttle": 100, "brake": 0, "drs": 12},
        {"driver_number": 4, "date": iso(6), "speed": 250, "n_gear": 6, "throttle": 80, "brake": 0, "drs": 8},
    ]
    ev = normalize("car_data", rows, CODE_OF, BASE)
    by = {e[2][0]: e[2] for e in ev}
    assert by["VER"][1] == 300.0 and by["VER"][5] is True   # drs 12 = open
    assert by["NOR"][5] is False                            # drs 8 = closed


def test_intervals_gap_strings_preserved():
    rows = [
        {"driver_number": 4, "date": iso(5), "gap_to_leader": 1.5, "interval": 1.5},
        {"driver_number": 63, "date": iso(5), "gap_to_leader": "+1 LAP", "interval": "+1 LAP"},
    ]
    by = {e[2][0]: e[2] for e in normalize("intervals", rows, CODE_OF, BASE)}
    assert by[4][1] == "1.5"
    assert by[63][1] == "+1 LAP"          # lapped string survives


def test_laps_emit_start_and_completion():
    rows = [{"driver_number": 1, "lap_number": 5, "date_start": iso(8), "lap_duration": 75.0}]
    ev = normalize("laps", rows, CODE_OF, BASE)
    kinds = {e[1] for e in ev}
    assert kinds == {"lap_start", "lap_done"}
    done = next(e for e in ev if e[1] == "lap_done")
    assert done[0] == 8.0 + 75.0 and done[2] == (1, 5, 75.0)


def test_laps_without_duration_is_start_only():
    ev = normalize("laps", [{"driver_number": 1, "lap_number": 5, "date_start": iso(8)}],
                   CODE_OF, BASE)
    assert [e[1] for e in ev] == ["lap_start"]


def test_stints_apply_at_minus_one():
    rows = [{"driver_number": 1, "stint_number": 2, "compound": "HARD",
             "lap_start": 21, "lap_end": 40, "tyre_age_at_start": 1}]
    ev = normalize("stints", rows, CODE_OF, BASE)
    assert ev[0][0] == -1.0 and ev[0][1] == "stint"
    assert ev[0][2] == (1, 2, "HARD", 21, 40, 1)


def test_race_control_maps_category_flag_scope():
    rows = [{"date": iso(30), "category": "SafetyCar", "flag": None,
             "scope": None, "message": "SAFETY CAR DEPLOYED"}]
    ev = normalize("race_control", rows, CODE_OF, BASE)
    assert ev[0][1] == "rc" and ev[0][2][0] == "SafetyCar"
    assert ev[0][2][3] == "SAFETY CAR DEPLOYED"


def test_unknown_endpoint_yields_nothing():
    assert normalize("telemetry_secret", [{"a": 1}], CODE_OF, BASE) == []


# ───────────────────────── REST source ─────────────────────────

class FakeHTTP:
    """Records calls; returns canned rows per endpoint."""

    def __init__(self, data: dict):
        self.data = data
        self.calls: list[tuple] = []

    def __call__(self, endpoint, **params):
        self.calls.append((endpoint, params))
        return list(self.data.get(endpoint, []))


def test_rest_source_discovers_live_session_in_window():
    http = FakeHTTP({"sessions": [SESSION], "drivers": ROSTER})
    src = OpenF1RestSource("tok", http_get=http,
                           now_fn=lambda: BASE + timedelta(minutes=30))
    assert src.open() == SESSION
    assert src.drivers() == ROSTER
    assert src.session_key == 9999


def test_rest_source_returns_none_when_not_live():
    http = FakeHTTP({"sessions": [SESSION], "drivers": ROSTER})
    src = OpenF1RestSource("tok", http_get=http,
                           now_fn=lambda: BASE + timedelta(days=2))  # long after end
    assert src.open() is None


def test_rest_source_cursor_advances_between_polls():
    data = {"sessions": [SESSION], "drivers": ROSTER,
            "location": [{"driver_number": 1, "date": iso(10), "x": 1, "y": 2, "z": 0}]}
    http = FakeHTTP(data)
    src = OpenF1RestSource("tok", http_get=http,
                           now_fn=lambda: BASE + timedelta(minutes=30))
    src.open()
    src.poll()
    assert src._cursor["location"] == iso(10)
    http.calls.clear()
    src.poll()
    loc_calls = [p for ep, p in http.calls if ep == "location"]
    assert loc_calls and loc_calls[0].get("date>") == iso(10)   # incremental


def test_make_live_source_and_mqtt_stub():
    assert isinstance(make_live_source("rest", token="x"), OpenF1RestSource)
    mqtt = make_live_source("mqtt", token="x")
    assert isinstance(mqtt, OpenF1MqttSource)
    with pytest.raises(NotImplementedError):
        mqtt.open()
    with pytest.raises(ValueError):
        make_live_source("carrier-pigeon", token="x")
    with pytest.raises(ValueError):
        OpenF1RestSource("")   # live needs a token


# ───────────────────────── LiveClient ─────────────────────────

class MockLiveSource(LiveSource):
    def __init__(self, session, roster, polls, total_laps=70):
        self._session = session
        self._roster = roster
        self._polls = list(polls)
        self._i = 0
        self._total = total_laps
        self.closed = False

    def open(self):
        return self._session

    def drivers(self):
        return self._roster

    def poll(self):
        if self._i < len(self._polls):
            p = self._polls[self._i]
            self._i += 1
            return p
        return {}

    def total_laps_hint(self):
        return self._total

    def close(self):
        self.closed = True


def _poll1():
    return {
        "location": [{"driver_number": n, "date": iso(10), "x": n, "y": n, "z": 0}
                     for n in (1, 4, 63)],
        "car_data": [{"driver_number": 1, "date": iso(10), "speed": 305, "n_gear": 7,
                      "throttle": 100, "brake": 0, "drs": 12}],
        "position": [{"driver_number": 1, "date": iso(10), "position": 1},
                     {"driver_number": 4, "date": iso(10), "position": 2},
                     {"driver_number": 63, "date": iso(10), "position": 3}],
        "intervals": [{"driver_number": 4, "date": iso(10), "gap_to_leader": 1.5, "interval": 1.5},
                      {"driver_number": 63, "date": iso(10), "gap_to_leader": 3.0, "interval": 1.5}],
        "laps": [{"driver_number": n, "lap_number": 5, "date_start": iso(8)} for n in (1, 4, 63)],
        "stints": [{"driver_number": 1, "stint_number": 1, "compound": "SOFT", "lap_start": 1, "lap_end": 20, "tyre_age_at_start": 0},
                   {"driver_number": 4, "stint_number": 1, "compound": "MEDIUM", "lap_start": 1, "lap_end": 25, "tyre_age_at_start": 0},
                   {"driver_number": 63, "stint_number": 1, "compound": "HARD", "lap_start": 1, "lap_end": 30, "tyre_age_at_start": 0}],
        "weather": [{"date": iso(10), "air_temperature": 22, "track_temperature": 41,
                     "humidity": 55, "rainfall": 0, "wind_speed": 3}],
        "race_control": [],
    }


def _poll2():
    # ~lap 5 completes (durations now known) and a safety car is deployed; all
    # cars still reporting GPS at iso(85) so none falsely retire.
    return {
        "location": [{"driver_number": n, "date": iso(85), "x": n, "y": n, "z": 0}
                     for n in (1, 4, 63)],
        "position": [{"driver_number": 1, "date": iso(85), "position": 1},
                     {"driver_number": 4, "date": iso(85), "position": 2},
                     {"driver_number": 63, "date": iso(85), "position": 3}],
        "laps": [{"driver_number": 1, "lap_number": 5, "date_start": iso(8), "lap_duration": 76.0},
                 {"driver_number": 4, "lap_number": 5, "date_start": iso(9), "lap_duration": 77.0},
                 {"driver_number": 63, "lap_number": 5, "date_start": iso(9), "lap_duration": 78.0}],
        "race_control": [{"date": iso(80), "category": "SafetyCar", "flag": None,
                          "scope": None, "message": "SAFETY CAR DEPLOYED"}],
    }


def _make_client(polls):
    src = MockLiveSource(SESSION, ROSTER, polls)
    bus = EventBus()
    # now = 3 s after the newest sample timestamp (iso(85)) -> delay 3.0
    client = LiveClient(src, bus, now_fn=lambda: BASE + timedelta(seconds=88))
    return client, src


def test_live_client_builds_state_and_session_msg():
    client, src = _make_client([_poll1(), _poll2()])
    assert client._discover() is True
    client._tick(_poll1())
    client._tick(_poll2())

    sm = client.session_msg()
    assert sm.mode == "live"
    assert sm.kind == "session"
    assert sm.delay_s == 3.0          # 88 - 85
    assert sm.lap == 5
    assert sm.total_laps == 70
    assert sm.flag == "SC"            # safety car derived from race_control


def test_live_client_leaderboard_and_tyres():
    client, _ = _make_client([_poll1(), _poll2()])
    client._discover()
    client._tick(_poll1())
    client._tick(_poll2())
    rows = client.state.leaderboard().rows
    assert [r.drv for r in rows] == ["VER", "NOR", "RUS"]
    assert rows[0].compound == "SOFT"
    assert rows[0].tyre_age == 4       # age0(0) + (lap5 - lap_start1)
    assert rows[0].last_lap == 76.0    # completion time captured


def test_live_client_publishes_all_message_kinds():
    client, _ = _make_client([_poll1(), _poll2()])
    client._discover()
    sent: list = []
    client.bus.publish = sent.append    # capture everything after bootstrap
    client._tick(_poll1())
    client._tick(_poll2())
    kinds = {m.kind for m in sent}
    assert {"positions", "car_telemetry", "leaderboard", "session",
            "prediction", "race_control"} <= kinds
    sc = [m for m in sent if m.kind == "race_control" and m.flag == "SC"]
    assert sc, "safety car race_control should be published"


def test_live_client_empty_session_state():
    src = MockLiveSource(SESSION, ROSTER, [])
    client = LiveClient(src, EventBus())
    sent: list = []
    client.bus.publish = sent.append
    client._emit_no_session()
    sess = [m for m in sent if m.kind == "session"][0]
    assert sess.mode == "live" and sess.name == "No live session"
    assert sess.total_laps == 0 and sess.paused is True
    assert any(m.kind == "leaderboard" and m.rows == [] for m in sent)


def test_live_client_reconnect_bookkeeping():
    client, _ = _make_client([_poll1()])
    client._discover()
    client._on_error(RuntimeError("connection reset"))
    assert client.conn == "reconnecting"
    assert client.last_error.startswith("RuntimeError")
    b1 = client._next_backoff()
    b2 = client._next_backoff()
    assert 0 < b1 < b2                    # exponential backoff grows


def test_live_client_seek_and_speed_are_noops():
    client, _ = _make_client([_poll1()])
    client._discover()
    client._tick(_poll1())
    before = client.t
    client.seek(0.0)        # can't scrub a live broadcast
    client.set_speed(10)    # can't fast-forward it either
    assert client.t == before


@pytest.mark.asyncio
async def test_live_client_run_loop_emits_session():
    client, src = _make_client([_poll1()])
    bus = client.bus
    q = bus.subscribe()
    client.poll_s = 0.01
    client.discover_retry_s = 0.01
    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.1)
    client.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    kinds = set()
    while not q.empty():
        kinds.add(q.get_nowait().kind)
    assert "session" in kinds          # the loop discovered + snapshotted
    assert src.closed                  # stop() released the source


# ─────────────────── reality check: replay Canada as "live" ───────────────────

USECOLS = {
    "location": ["driver_number", "date", "x", "y", "z"],
    "car_data": ["driver_number", "date", "speed", "n_gear", "throttle", "brake", "drs"],
    "intervals": ["driver_number", "date", "gap_to_leader", "interval"],
    "position": ["driver_number", "date", "position"],
    "laps": ["driver_number", "lap_number", "date_start", "lap_duration"],
    "pit": ["driver_number", "date", "lap_number"],
    "weather": ["date", "air_temperature", "track_temperature", "humidity", "rainfall", "wind_speed"],
    "race_control": ["date", "category", "flag", "scope", "message"],
}
DATE_COL = {ep: ("date_start" if ep == "laps" else "date") for ep in USECOLS}


def _canada_polls(fixture_dir, n_windows=30):
    """Slice the recorded Canada streams into time-ordered polls, as if the race
    were arriving live. DNF cars stop appearing in later windows, so the client's
    GPS-gap retirement logic fires just like in a real session."""
    import pandas as pd

    frames = {p.stem: pd.read_parquet(p) for p in fixture_dir.glob("*.parquet")}
    roster = frames["drivers"].to_dict("records")

    dated: list[tuple] = []
    for ep, cols in USECOLS.items():
        df = frames.get(ep)
        if df is None or df.empty:
            continue
        keep = [c for c in cols if c in df.columns]
        for row in df[keep].to_dict("records"):
            d = row.get(DATE_COL[ep])
            if d is not None and str(d) != "NaT":
                dated.append((str(d), ep, row))
    dated.sort(key=lambda x: x[0])

    polls = [dict() for _ in range(n_windows)]
    total = len(dated)
    for i, (_, ep, row) in enumerate(dated):
        w = min(n_windows - 1, i * n_windows // total)
        polls[w].setdefault(ep, []).append(row)
    # stints have no timestamp: apply once up front
    st = frames.get("stints")
    if st is not None and not st.empty:
        polls[0]["stints"] = st[[c for c in
            ["driver_number", "stint_number", "compound", "lap_start", "lap_end", "tyre_age_at_start"]
            if c in st.columns]].to_dict("records")
    return polls, roster


def test_canada_replayed_as_live_reaches_real_podium(canada):
    from pathlib import Path

    fixture_dir = Path(canada.meta["__dir__"]) if "__dir__" in canada.meta else None
    if fixture_dir is None:
        import os
        root = Path(os.environ.get("FIXTURES_DIR",
                    Path(__file__).resolve().parents[2] / "data" / "fixtures"))
        fixture_dir = root / "2024_canada_race"
    if not (fixture_dir / "location.parquet").exists():
        pytest.skip("Canada parquet streams not present")

    polls, roster = _canada_polls(fixture_dir)
    session = {**canada.meta.get("session", {}), "circuit_short_name": "Montreal"}
    src = MockLiveSource(session, roster, polls, total_laps=70)
    client = LiveClient(src, EventBus())
    client._discover()
    for p in polls:
        client._tick(p)

    rows = client.state.leaderboard().rows
    assert [r.drv for r in rows[:3]] == ["VER", "NOR", "RUS"]
    assert client.state.lap >= 68      # ran essentially the full distance
