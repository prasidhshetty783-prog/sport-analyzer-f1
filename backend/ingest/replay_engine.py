"""Replay engine: re-emits a recorded fixture through the event bus under a
virtual clock (1x/2x/10x, play/pause/seek). Live ingest (Phase 5) will be an
interchangeable producer on the same bus."""
from __future__ import annotations

import asyncio
import bisect

from backend.api.schema import (CarPosition, CarTelemetryMsg, PositionsMsg,
                                RaceControlMsg, SessionMsg)
from backend.core.event_bus import EventBus
from backend.ingest.fixture_store import Fixture
from backend.models.predictor import Predictor
from backend.state.race_state import RaceState

TICK_S = 0.05
LEADERBOARD_MIN_GAP_S = 0.5   # session-time throttle
SESSION_MSG_GAP_S = 1.0
PREDICT_GAP_S = 30.0          # routine prediction refresh (session time)
PREDICT_SIMS = 1200           # Monte-Carlo runs per refresh
RETIRE_GAP_S = 12.0           # no GPS for this long (session time) => retired
                              # (retired cars emit (0,0,0), filtered at load, so
                              #  their position frames simply stop)


class ReplayEngine:
    def __init__(self, fixture: Fixture, bus: EventBus):
        self.fx = fixture
        self.bus = bus
        self.state = RaceState(fixture)
        self._times = [e[0] for e in fixture.events]
        self.t = 0.0
        self.speed = 1.0
        self.paused = True
        self._cursor = 0
        self._last_lb_t = -1e9
        self._last_session_t = -1e9
        self._last_pred_t = -1e9
        self._pred_dirty = False  # set by flag/pit events -> recompute now
        self._last_predictions: list = []
        self._last_pos_frame: PositionsMsg | None = None
        self._last_seen_t: dict[str, float] = {}  # drv code -> last GPS time
        self._num_of_code = {d.code: n for n, d in fixture.drivers.items()}
        self._stopped = False
        self.predictor = Predictor(self.state.circuit(), fixture.total_laps,
                                  n_sims=PREDICT_SIMS)
        # The race ends at the leader's chequered flag (fall back to the last
        # lap + a slow-lap buffer). The fixture often keeps recording for minutes
        # afterwards, so we clamp the clock here instead of running to data-end.
        chequered = [t for t, k, p in fixture.events
                     if k == "rc" and len(p) >= 2 and str(p[1]) == "CHEQUERED"]
        last_lap = max((t for t, k, _ in fixture.events if k == "lap_start"),
                       default=fixture.duration_s)
        end = (min(chequered) + 12.0) if chequered else (last_lap + 120.0)
        self.end_s = max(fixture.race_start_s + 1.0, min(end, fixture.duration_s))
        self._apply_until(0.0, emit=False)  # stints (t=-1) etc.

    # ---------- transport ----------

    def play(self) -> None:
        self.paused = False
        self._emit_session(force=True)

    def pause(self) -> None:
        self.paused = True
        self._emit_session(force=True)

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.1, min(float(speed), 50.0))
        self._emit_session(force=True)

    def seek(self, t_s: float) -> None:
        """Rebuild state at t_s and broadcast a full snapshot."""
        t_s = max(0.0, min(float(t_s), self.end_s))
        if t_s < self.t:
            self.state.reset()
            self._cursor = 0
            self._last_seen_t.clear()
        self.t = t_s
        self._apply_until(t_s, emit=False)
        self._refresh_retired()
        if t_s >= self.end_s:
            self.state.finish()
        self._compute_predictions(publish=False)  # refresh for the new position
        self.snapshot()

    def stop(self) -> None:
        self._stopped = True

    # ---------- loop ----------

    async def run(self) -> None:
        while not self._stopped:
            await asyncio.sleep(TICK_S)
            if self.paused:
                continue
            self.t = min(self.t + TICK_S * self.speed, self.end_s)
            self._apply_until(self.t, emit=True)
            self._refresh_retired()
            if self.state.dirty and self.t - self._last_lb_t >= LEADERBOARD_MIN_GAP_S:
                self._last_lb_t = self.t
                self.bus.publish(self.state.leaderboard())
            self._maybe_predict()
            self._emit_session()
            if self.t >= self.end_s:
                self.state.finish()
                self.bus.publish(self.state.leaderboard())
                self.bus.publish(RaceControlMsg(
                    flag=self.state.flag, message="CHEQUERED FLAG", t=self.t))
                self.pause()

    def _apply_until(self, t_s: float, *, emit: bool) -> None:
        end = bisect.bisect_right(self._times, t_s)
        for i in range(self._cursor, end):
            t, kind, p = self.fx.events[i]
            if kind == "pos_frame":
                for c in p:
                    self._last_seen_t[c[0]] = t  # car is still circulating
                msg = PositionsMsg(t=t, cars=[
                    CarPosition(drv=c[0], x=c[1], y=c[2], z=c[3]) for c in p])
                self._last_pos_frame = msg
                if emit:
                    self.bus.publish(msg)
            elif kind == "car_tel":
                if emit:
                    self.bus.publish(CarTelemetryMsg(
                        drv=p[0], speed=p[1], gear=p[2], throttle=p[3],
                        brake=p[4], drs=p[5]))
            else:
                rc = self.state.apply(kind, p)
                if emit and (rc is not None or kind == "pit"):
                    # flag change or a pit stop -> predictions must recompute now
                    self._pred_dirty = True
                if rc is not None and emit:
                    self.bus.publish(RaceControlMsg(flag=rc.flag,
                                                    message=rc.message, t=t))
        self._cursor = end

    # ---------- messages ----------

    def session_msg(self) -> SessionMsg:
        return self.state.session(
            session_id=self.fx.session_id, name=self.fx.name,
            total_laps=self.fx.total_laps, t_s=self.t,
            duration_s=self.end_s, speed=self.speed,
            paused=self.paused)

    def _emit_session(self, force: bool = False) -> None:
        if force or self.t - self._last_session_t >= SESSION_MSG_GAP_S:
            self._last_session_t = self.t
            self.bus.publish(self.session_msg())

    # ---------- predictions (Phase 3) ----------

    def _maybe_predict(self) -> None:
        due = self.t - self._last_pred_t >= PREDICT_GAP_S
        if self._pred_dirty or due:
            self._compute_predictions(publish=True)

    def _compute_predictions(self, *, publish: bool) -> None:
        cars = self.state.predict_inputs()  # active cars only (excludes retired)
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
        # retired cars get an explicit DNF card instead of a stale podium chance
        for code in retired:
            msgs.append(Predictor.dnf_prediction(code, field, self.t))
        self._last_predictions = msgs
        if publish:
            for m in msgs:
                self.bus.publish(m)

    def _refresh_retired(self) -> None:
        """A car with no GPS for RETIRE_GAP_S of session time has retired."""
        retired = {self._num_of_code[code]
                   for code, seen in self._last_seen_t.items()
                   if code in self._num_of_code and self.t - seen > RETIRE_GAP_S}
        if retired != self.state.retired:
            self.state.retired = retired
            self.state.dirty = True  # leaderboard must drop them

    def snapshot(self) -> None:
        """Full current state for new/seeking clients."""
        self.bus.publish(self.session_msg())
        self.bus.publish(self.state.leaderboard())
        if self.state.weather is not None:
            self.bus.publish(self.state.weather)
        if self._last_pos_frame is not None:
            self.bus.publish(self._last_pos_frame)
        for m in self._last_predictions:
            self.bus.publish(m)
        self.bus.publish(RaceControlMsg(flag=self.state.flag,
                                        message=self.state.last_rc_message,
                                        t=self.t))

    # test helper: run to a point without wall-clock pacing
    def fast_forward(self, t_s: float) -> None:
        self.t = min(t_s, self.end_s)
        self._apply_until(self.t, emit=False)
        self._refresh_retired()
