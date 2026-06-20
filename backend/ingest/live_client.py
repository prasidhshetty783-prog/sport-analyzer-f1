"""LiveClient: the live-mode event producer (Phase 5).

It is an *interchangeable* producer with `ReplayEngine` — same public surface
(`run` / `stop` / `snapshot` / `play` / `pause` / `set_speed` / `seek`), same
`EventBus`, same `RaceState` + `Predictor`, same WS message kinds. So every
downstream feature (leaderboard, track map, predictions, Car/Track panels) works
identically whether the producer is replaying a fixture or polling a live race —
the spec's "replay mode is indistinguishable in features" bar.

Pipeline:  LiveSource.poll() -> openf1_normalize -> RaceState.apply / bus
The only live-specific bits are the real **data-delay** (wall clock minus the
newest sample timestamp; honestly surfaced as `delay_s`), session discovery, and
reconnect / empty-session handling. Live can't scrub or change speed, so those
transport calls are no-ops.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.api.schema import (CarPosition, CarTelemetryMsg, LeaderboardMsg,
                                PositionsMsg, RaceControlMsg, SessionMsg)
from backend.core.event_bus import EventBus
from backend.ingest.fixture_store import DriverInfo, Fixture
from backend.ingest.live_source import LiveSource
from backend.ingest.openf1_normalize import normalize, parse_dt
from backend.models.predictor import Predictor
from backend.state.race_state import RaceState

POLL_S = 1.0                  # wall seconds between polls
LEADERBOARD_MIN_GAP_S = 0.5   # session-time throttle (mirrors the engine)
SESSION_MSG_GAP_S = 1.0
PREDICT_GAP_S = 30.0
PREDICT_SIMS = 1200
RETIRE_GAP_S = 20.0           # no GPS for this long (session time) => retired
DISCOVER_RETRY_S = 20.0       # re-check for a live session this often
MAX_BACKOFF_S = 15.0

CIRCUIT_FACTS = (Path(__file__).resolve().parents[2] / "data" / "circuit_facts")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lookup_total_laps(session: dict) -> int:
    """Scheduled lap count from data/circuit_facts/<circuit_key>.json if a host
    run cached it (OpenF1 doesn't broadcast it). 0 when unknown — never faked."""
    key = str(session.get("circuit_key", "") or "")
    path = CIRCUIT_FACTS / f"{key}.json"
    if key and path.exists():
        try:
            return int(json.loads(path.read_text()).get("laps") or 0)
        except Exception:  # noqa: BLE001
            return 0
    return 0


class LiveClient:
    def __init__(self, source: LiveSource, bus: EventBus, *,
                 now_fn=_utcnow, poll_s: float = POLL_S,
                 discover_retry_s: float = DISCOVER_RETRY_S):
        self.source = source
        self.bus = bus
        self.now_fn = now_fn
        self.poll_s = poll_s
        self.discover_retry_s = discover_retry_s

        self.session_id = "live"
        self.name = "Live session"
        self.total_laps = 0
        self.mode = "live"
        self.paused = False
        self.conn = "connecting"  # connecting | live | no_session | reconnecting

        self.state: RaceState | None = None
        self.predictor: Predictor | None = None
        self.t0: datetime | None = None
        self.t = 0.0
        self._latest_dt: datetime | None = None

        self._code_of: dict[int, str] = {}
        self._num_of_code: dict[str, int] = {}
        self._last_seen_t: dict[str, float] = {}
        self._last_pos_frame: PositionsMsg | None = None
        self._last_predictions: list = []
        self._last_lb_t = -1e9
        self._last_session_t = -1e9
        self._last_pred_t = -1e9
        self._pred_dirty = False
        self._stopped = False
        self._backoff = 0.0
        self.last_error: str | None = None

    # ---------- transport (live: only play/pause are meaningful) ----------

    def play(self) -> None:
        self.paused = False
        self._emit_session(force=True)

    def pause(self) -> None:
        self.paused = True
        self._emit_session(force=True)

    def set_speed(self, speed: float) -> None:
        """No-op: live runs at 1x wall-clock by definition."""
        self._emit_session(force=True)

    def seek(self, t_s: float) -> None:
        """No-op: you can't scrub a live broadcast."""
        self._emit_session(force=True)

    def stop(self) -> None:
        self._stopped = True
        self.source.close()

    # ---------- session bootstrap ----------

    def _build_state(self, session: dict, roster: list[dict]) -> None:
        drivers: dict[int, DriverInfo] = {}
        for r in roster:
            try:
                n = int(r["driver_number"])
            except (KeyError, TypeError, ValueError):
                continue
            drivers[n] = DriverInfo(
                n, r.get("name_acronym") or str(n), r.get("team_name") or "",
                (r.get("team_colour") or "808080"))
        self.total_laps = self.source.total_laps_hint() or _lookup_total_laps(session)
        meeting_name = (session.get("circuit_short_name")
                        or session.get("country_name") or "Live")
        self.name = f"{meeting_name} {session.get('year', '')} (LIVE)".strip()
        fx = Fixture(
            session_id="live", name=self.name,
            year=int(session.get("year") or 0),
            country=str(session.get("country_name") or "?"),
            total_laps=self.total_laps, duration_s=0.0, race_start_s=0.0,
            drivers=drivers, events=[], meta={"session": session})
        self.state = RaceState(fx)
        self.predictor = Predictor(self.state.circuit(), self.total_laps,
                                   n_sims=PREDICT_SIMS)
        self._code_of = {n: d.code for n, d in drivers.items()}
        self._num_of_code = {d.code: n for n, d in drivers.items()}
        self.t0 = parse_dt(session.get("date_start")) or self.now_fn()
        self.t = 0.0
        self._last_seen_t.clear()

    # ---------- main loop ----------

    async def run(self) -> None:
        while not self._stopped:
            try:
                if self.state is None:
                    if not self._discover():
                        self.conn = "no_session"
                        self._emit_no_session()
                        await asyncio.sleep(self.discover_retry_s)
                        continue
                    self.conn = "live"
                    self.snapshot()
                if not self.paused:
                    self._tick(self.source.poll())
                self._backoff = 0.0
                self.conn = "live"
                await asyncio.sleep(self.poll_s)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - live feed is best-effort
                self._on_error(e)
                await asyncio.sleep(self._next_backoff())

    def _discover(self) -> bool:
        sess = self.source.open()
        if not sess:
            return False
        self._build_state(sess, self.source.drivers())
        return True

    # ---------- one poll's worth of rows ----------

    def _tick(self, poll: dict[str, list[dict]]) -> None:
        """Apply a batch of polled rows, then emit on the usual cadence. Public
        so tests can drive the client deterministically with canned polls."""
        if self.state is None or not poll:
            return
        self._track_delay(poll)
        events: list[tuple] = []
        for endpoint, rows in poll.items():
            events.extend(normalize(endpoint, rows, self._code_of, self.t0))
        # stints (t=-1) apply first, then everything in chronological order —
        # same ordering guarantee the fixture loader provides.
        for t_s, kind, payload in sorted(events, key=lambda e: e[0]):
            self._apply(t_s, kind, payload)
        self._refresh_retired()
        self._emit_cadence()

    def _apply(self, t_s: float, kind: str, p) -> None:
        if t_s > self.t:
            self.t = t_s
        if kind == "pos_frame":
            for c in p:
                self._last_seen_t[c[0]] = t_s
            msg = PositionsMsg(t=t_s, cars=[
                CarPosition(drv=c[0], x=c[1], y=c[2], z=c[3]) for c in p])
            self._last_pos_frame = msg
            self.bus.publish(msg)
        elif kind == "car_tel":
            self.bus.publish(CarTelemetryMsg(
                drv=p[0], speed=p[1], gear=p[2], throttle=p[3],
                brake=p[4], drs=p[5]))
        else:
            rc = self.state.apply(kind, p)
            if rc is not None or kind == "pit":
                self._pred_dirty = True
            if rc is not None:
                self.bus.publish(RaceControlMsg(
                    flag=rc.flag, message=rc.message, t=t_s))

    def _refresh_retired(self) -> None:
        retired = {self._num_of_code[code]
                   for code, seen in self._last_seen_t.items()
                   if code in self._num_of_code and self.t - seen > RETIRE_GAP_S}
        if retired != self.state.retired:
            self.state.retired = retired
            self.state.dirty = True

    # ---------- delay (the honest live indicator) ----------

    def _track_delay(self, poll: dict[str, list[dict]]) -> None:
        newest = self._latest_dt
        for endpoint, rows in poll.items():
            field = "date_start" if endpoint == "laps" else "date"
            for r in rows:
                dt = parse_dt(r.get(field))
                if dt and (newest is None or dt > newest):
                    newest = dt
        self._latest_dt = newest

    def _delay_s(self) -> float:
        if self._latest_dt is None:
            return 0.0
        return max(0.0, (self.now_fn() - self._latest_dt).total_seconds())

    # ---------- emit cadence ----------

    def _emit_cadence(self) -> None:
        if self.state.dirty and self.t - self._last_lb_t >= LEADERBOARD_MIN_GAP_S:
            self._last_lb_t = self.t
            self.bus.publish(self.state.leaderboard())
        self._maybe_predict()
        self._emit_session()

    def session_msg(self) -> SessionMsg:
        return self.state.session(
            session_id=self.session_id, name=self.name,
            total_laps=self.total_laps, t_s=self.t, duration_s=self.t,
            speed=1.0, paused=self.paused, mode="live", delay_s=round(self._delay_s(), 1))

    def _emit_session(self, force: bool = False) -> None:
        if self.state is None:
            return
        if force or self.t - self._last_session_t >= SESSION_MSG_GAP_S:
            self._last_session_t = self.t
            self.bus.publish(self.session_msg())

    def _emit_no_session(self) -> None:
        """Token present but no race is live right now — clear the board and tell
        the UI so it can show an honest empty state (never a stale grid)."""
        self.bus.publish(SessionMsg(
            session_id="live", name="No live session", lap=0, total_laps=0,
            mode="live", delay_s=0.0, flag="GREEN", t_s=0.0, duration_s=0.0,
            speed=1.0, paused=True))
        self.bus.publish(LeaderboardMsg(rows=[]))

    # ---------- predictions ----------

    def _maybe_predict(self) -> None:
        due = self.t - self._last_pred_t >= PREDICT_GAP_S
        if self._pred_dirty or due:
            self._compute_predictions(publish=True)

    def _compute_predictions(self, *, publish: bool) -> None:
        cars = self.state.predict_inputs()
        self._last_pred_t = self.t
        self._pred_dirty = False
        retired = [self.state.cars[n].code for n in self.state.retired
                   if n in self.state.cars]
        if not cars and not retired:
            self._last_predictions = []
            return
        field = len(cars) + len(retired)
        msgs = self.predictor.predict(
            cars, race_lap=self.state.lap, flag=self.state.flag,
            weather=self.state.weather, sc_laps=self.state.sc_laps,
            t_s=self.t) if cars else []
        for code in retired:
            msgs.append(Predictor.dnf_prediction(code, field, self.t))
        self._last_predictions = msgs
        if publish:
            for m in msgs:
                self.bus.publish(m)

    # ---------- snapshot for new/seeking clients ----------

    def snapshot(self) -> None:
        if self.state is None:
            self._emit_no_session()
            return
        self.bus.publish(self.session_msg())
        self.bus.publish(self.state.leaderboard())
        if self.state.weather is not None:
            self.bus.publish(self.state.weather)
        if self._last_pos_frame is not None:
            self.bus.publish(self._last_pos_frame)
        for m in self._last_predictions:
            self.bus.publish(m)
        self.bus.publish(RaceControlMsg(
            flag=self.state.flag, message=self.state.last_rc_message, t=self.t))

    # ---------- error / reconnect ----------

    def _on_error(self, e: Exception) -> None:
        self.conn = "reconnecting"
        self.last_error = f"{type(e).__name__}: {e}"
        # keep the last good state on screen; the rising delay_s signals staleness
        if self.state is not None:
            self._emit_session(force=True)

    def _next_backoff(self) -> float:
        self._backoff = min(MAX_BACKOFF_S, (self._backoff or 0.5) * 2)
        return self._backoff
