// GENERATED FILE - do not edit.
// Source of truth: backend/api/schema.py  (python -m backend.api.gen_types)

export const PROTOCOL_VERSION = 1;

export interface CarPosition {
  drv: string;
  x: number;
  y: number;
  z: number;
}

export interface PositionsMsg {
  kind: "positions";
  t: number;
  cars: CarPosition[];
}

export interface LeaderboardRow {
  pos: number;
  drv: string;
  team: string;
  colour: string;
  gap_leader?: string | null;
  interval?: string | null;
  last_lap?: number | null;
  compound?: string | null;
  tyre_age?: number | null;
  pits?: number;
}

export interface LeaderboardMsg {
  kind: "leaderboard";
  rows: LeaderboardRow[];
}

export interface CarTelemetryMsg {
  kind: "car_telemetry";
  drv: string;
  speed: number;
  gear: number;
  throttle: number;
  brake: number;
  drs: boolean;
}

export interface FinishDist {
  exp: number;
  p_win: number;
  p_podium: number;
  p_points: number;
  dist: number[];
}

export interface TyrePred {
  deg_rate: number;
  laps_to_cliff: number;
}

export interface FuelEst {
  kg: number;
  laps: number;
}

export interface PredictionMsg {
  kind: "prediction";
  drv: string;
  finish: FinishDist;
  tyre: TyrePred;
  fuel: FuelEst;
  updated_at: number;
}

export interface RaceControlMsg {
  kind: "race_control";
  flag: "GREEN" | "YELLOW" | "SC" | "VSC" | "RED" | "CHEQUERED";
  message: string;
  t: number;
}

export interface WeatherMsg {
  kind: "weather";
  air: number;
  track: number;
  humidity: number;
  rain: boolean;
  wind: number;
}

export interface SessionMsg {
  kind: "session";
  session_id: string;
  name: string;
  lap: number;
  total_laps: number;
  mode: "replay" | "live";
  delay_s: number;
  flag: "GREEN" | "YELLOW" | "SC" | "VSC" | "RED" | "CHEQUERED";
  t_s: number;
  duration_s: number;
  speed: number;
  paused: boolean;
}

export interface TransportCmd {
  kind: "transport";
  action: "play" | "pause" | "seek" | "speed";
  speed?: number | null;
  seek_s?: number | null;
}

export interface SelectSessionCmd {
  kind: "select_session";
  session_id: string;
}

export type ServerMessage = PositionsMsg | LeaderboardMsg | CarTelemetryMsg | PredictionMsg | RaceControlMsg | WeatherMsg | SessionMsg;
export type ClientMessage = TransportCmd | SelectSessionCmd;
