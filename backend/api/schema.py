"""Single-source WebSocket protocol schema (protocol v1).

Every message on the wire is one of these Pydantic models, discriminated by
`kind`. Frontend TypeScript types are GENERATED from this file:

    python -m backend.api.gen_types

Working agreement: changing this schema requires explicit user approval.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

PROTOCOL_VERSION = 1


# ---------- server -> client ----------

class CarPosition(BaseModel):
    drv: str  # 3-letter driver code
    x: float
    y: float
    z: float


class PositionsMsg(BaseModel):
    kind: Literal["positions"] = "positions"
    t: float  # session time, seconds
    cars: list[CarPosition]


class LeaderboardRow(BaseModel):
    pos: int
    drv: str
    team: str
    colour: str  # hex from data (no '#'), e.g. "27F4D2"
    gap_leader: Optional[str] = None  # "12.345" | "+1 LAP" | None for leader
    interval: Optional[str] = None
    last_lap: Optional[float] = None  # seconds
    compound: Optional[str] = None  # SOFT/MEDIUM/HARD/INTERMEDIATE/WET
    tyre_age: Optional[int] = None  # laps
    pits: int = 0


class LeaderboardMsg(BaseModel):
    kind: Literal["leaderboard"] = "leaderboard"
    rows: list[LeaderboardRow]


class CarTelemetryMsg(BaseModel):
    kind: Literal["car_telemetry"] = "car_telemetry"
    drv: str
    speed: float
    gear: int
    throttle: float
    brake: float
    drs: bool


class FinishDist(BaseModel):
    exp: float
    p_win: float
    p_podium: float
    p_points: float
    dist: list[float]


class TyrePred(BaseModel):
    deg_rate: float
    laps_to_cliff: float


class FuelEst(BaseModel):
    kg: float
    laps: float


class PredictionMsg(BaseModel):
    """Phase 3 emits these; shape is fixed now so the protocol is stable."""
    kind: Literal["prediction"] = "prediction"
    drv: str
    finish: FinishDist
    tyre: TyrePred
    fuel: FuelEst
    updated_at: float  # session time, seconds


FlagState = Literal["GREEN", "YELLOW", "SC", "VSC", "RED", "CHEQUERED"]


class RaceControlMsg(BaseModel):
    kind: Literal["race_control"] = "race_control"
    flag: FlagState
    message: str
    t: float


class WeatherMsg(BaseModel):
    kind: Literal["weather"] = "weather"
    air: float
    track: float
    humidity: float
    rain: bool
    wind: float


class SessionMsg(BaseModel):
    kind: Literal["session"] = "session"
    session_id: str
    name: str
    lap: int
    total_laps: int
    mode: Literal["replay", "live"]
    delay_s: float
    flag: FlagState
    # playback state (approved control-plane extension)
    t_s: float
    duration_s: float
    speed: float
    paused: bool


# ---------- client -> server ----------

class TransportCmd(BaseModel):
    kind: Literal["transport"] = "transport"
    action: Literal["play", "pause", "seek", "speed"]
    speed: Optional[float] = None  # 1 | 2 | 10
    seek_s: Optional[float] = None


class SelectSessionCmd(BaseModel):
    kind: Literal["select_session"] = "select_session"
    session_id: str


SERVER_MESSAGES = [PositionsMsg, LeaderboardMsg, CarTelemetryMsg,
                   PredictionMsg, RaceControlMsg, WeatherMsg, SessionMsg]
CLIENT_MESSAGES = [TransportCmd, SelectSessionCmd]
