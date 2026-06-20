"""Accumulates fixture/live events into current race state and renders the
typed WS messages (leaderboard, session, race_control snapshot)."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.api.schema import (FlagState, LeaderboardMsg, LeaderboardRow,
                                RaceControlMsg, SessionMsg, WeatherMsg)
from backend.ingest.fixture_store import Fixture
from backend.models.predictor import CarInput


def _parse_secs(gap: str | None) -> float | None:
    """Gap/interval strings are numeric seconds, '+1 LAP', or None."""
    if gap is None:
        return None
    try:
        return float(gap)
    except ValueError:
        return None  # lapped ('+1 LAP') — simulator falls back to spacing


@dataclass
class _Car:
    number: int
    code: str
    team: str
    colour: str
    position: int | None = None
    gap_leader: str | None = None
    interval: str | None = None
    last_lap: float | None = None
    current_lap: int = 0
    pits: int = 0
    stints: list[tuple] = field(default_factory=list)  # (stint_no, compound, lap_start, lap_end, age0)

    def tyre(self) -> tuple[str | None, int | None]:
        lap = max(self.current_lap, 1)
        for stint_no, compound, lap_start, lap_end, age0 in reversed(self.stints):
            if lap_start <= lap:
                return compound, age0 + max(0, lap - lap_start)
        if self.stints:
            s = self.stints[0]
            return s[1], s[4]
        return None, None


class RaceState:
    def __init__(self, fixture: Fixture):
        self.fx = fixture
        self.reset()

    def reset(self) -> None:
        self.cars: dict[int, _Car] = {
            n: _Car(n, d.code, d.team, d.colour)
            for n, d in self.fx.drivers.items()
        }
        self.lap = 0
        self.sc_laps = 0  # race laps run under SC/VSC (fuel-burn discount)
        self.retired: set[int] = set()  # car numbers no longer circulating
        self.flag: FlagState = "GREEN"
        self._sc_active = False
        self._vsc_active = False
        self._red_active = False
        self._yellow_scopes: set[str] = set()
        self._chequered = False
        self.last_rc_message = ""
        self.weather: WeatherMsg | None = None
        self.dirty = True  # leaderboard needs re-emit

    # ---------- event application ----------

    def apply(self, kind: str, p: tuple) -> RaceControlMsg | None:
        """Returns a RaceControlMsg when the event should be broadcast."""
        if kind == "interval":
            car = self.cars[p[0]]
            car.gap_leader, car.interval = p[1], p[2]
            self.dirty = True
        elif kind == "position":
            self.cars[p[0]].position = p[1]
            self.dirty = True
        elif kind == "lap_start":
            car = self.cars[p[0]]
            car.current_lap = max(car.current_lap, p[1])
            prev = self.lap
            self.lap = max(self.lap, p[1])
            if self.lap > prev and self.flag in ("SC", "VSC"):
                self.sc_laps += 1
            self.dirty = True
        elif kind == "lap_done":
            self.cars[p[0]].last_lap = p[2]
            self.dirty = True
        elif kind == "stint":
            n, stint_no, compound, lap_start, lap_end, age0 = p
            self.cars[n].stints.append((stint_no, compound, lap_start, lap_end, age0))
            self.cars[n].stints.sort()
            self.dirty = True
        elif kind == "pit":
            self.cars[p[0]].pits += 1
            self.dirty = True
        elif kind == "weather":
            air, track, hum, rain, wind = p
            self.weather = WeatherMsg(air=air, track=track, humidity=hum,
                                      rain=rain, wind=wind)
        elif kind == "rc":
            return self._apply_rc(*p)
        return None

    def _apply_rc(self, category: str, flag: str | None, scope: str | None,
                  message: str) -> RaceControlMsg | None:
        msg_upper = (message or "").upper()
        if category == "SafetyCar":
            # SC/VSC stay active ("IN THIS LAP" is a heads-up, not an ending);
            # both are cleared by the GREEN/CLEAR track flag below.
            if "VIRTUAL" in msg_upper:
                if "DEPLOYED" in msg_upper:
                    self._vsc_active = True
            elif "DEPLOYED" in msg_upper:
                self._sc_active = True
        elif category == "Flag" and flag:
            if flag == "RED":
                self._red_active = True
            elif flag in ("GREEN", "CLEAR"):
                if scope == "Track" or flag == "GREEN":
                    self._red_active = False
                    self._sc_active = False
                    self._vsc_active = False
                    self._yellow_scopes.clear()
                else:
                    self._yellow_scopes.discard(scope or "Track")
            elif flag in ("YELLOW", "DOUBLE YELLOW"):
                self._yellow_scopes.add(scope or "Track")
            elif flag == "CHEQUERED":
                self._chequered = True
        # BLUE / BLACK AND WHITE / Drs / Other: no global state change
        new_flag = self._derive_flag()
        changed = new_flag != self.flag or category in ("SafetyCar", "Flag")
        self.flag = new_flag
        self.last_rc_message = message
        self.dirty = True
        if changed and category in ("SafetyCar", "Flag", "SessionStatus"):
            return RaceControlMsg(flag=self.flag, message=message, t=0.0)
        return None

    def _derive_flag(self) -> FlagState:
        if self._red_active:
            return "RED"
        if self._chequered:
            return "CHEQUERED"
        if self._sc_active:
            return "SC"
        if self._vsc_active:
            return "VSC"
        if self._yellow_scopes:
            return "YELLOW"
        return "GREEN"

    def finish(self) -> None:
        """Race is over: clear any active SC/red/yellow and show the chequered
        flag (a red-flagged or SC finish must not stay red forever)."""
        self._red_active = False
        self._sc_active = False
        self._vsc_active = False
        self._yellow_scopes.clear()
        self._chequered = True
        if self.flag != "CHEQUERED":
            self.flag = "CHEQUERED"
            self.dirty = True

    # ---------- message rendering ----------

    def leaderboard(self) -> LeaderboardMsg:
        ranked = sorted((c for c in self.cars.values()
                         if c.position and c.number not in self.retired),
                        key=lambda c: c.position)
        rows = []
        for c in ranked:
            compound, age = c.tyre()
            rows.append(LeaderboardRow(
                pos=c.position, drv=c.code, team=c.team, colour=c.colour,
                gap_leader=None if c.position == 1 else c.gap_leader,
                interval=None if c.position == 1 else c.interval,
                last_lap=c.last_lap, compound=compound, tyre_age=age,
                pits=c.pits))
        self.dirty = False
        return LeaderboardMsg(rows=rows)

    # ---------- prediction inputs (Phase 3) ----------

    def circuit(self) -> str | None:
        sess = self.fx.meta.get("session", {})
        return sess.get("circuit_short_name") or self.fx.country

    def predict_inputs(self) -> list[CarInput]:
        """Snapshot of running cars for the prediction engine."""
        out: list[CarInput] = []
        for c in self.cars.values():
            if not c.position or c.number in self.retired:
                continue
            compound, age = c.tyre()
            out.append(CarInput(
                code=c.code, position=c.position,
                current_lap=max(c.current_lap, self.lap),
                gap_leader_s=_parse_secs(c.gap_leader),
                interval_s=_parse_secs(c.interval),
                compound=compound, tyre_age=age, pits=c.pits))
        return out

    def session(self, *, session_id: str, name: str, total_laps: int,
                t_s: float, duration_s: float, speed: float, paused: bool,
                mode: str = "replay", delay_s: float = 0.0) -> SessionMsg:
        # `mode`/`delay_s` default to the replay values; the live producer passes
        # mode="live" + the real broadcast delay. Same SessionMsg shape either way
        # (the wire fields already exist), so this is not a protocol change.
        return SessionMsg(session_id=session_id, name=name,
                          lap=min(self.lap, total_laps) if total_laps else self.lap,
                          total_laps=total_laps, mode=mode, delay_s=delay_s,
                          flag=self.flag, t_s=round(t_s, 2),
                          duration_s=round(duration_s, 2), speed=speed,
                          paused=paused)
