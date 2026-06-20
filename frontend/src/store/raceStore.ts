// Central client state, fed exclusively by typed server messages.
import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

import type { ConnStatus } from "../lib/ws/client";
import type {
  CarTelemetryMsg, LeaderboardRow, PositionsMsg, PredictionMsg, RaceControlMsg,
  ServerMessage, SessionMsg, WeatherMsg,
} from "../lib/ws/types";

// Roster metadata from GET /api/drivers/{session_id} (headshots load client-side).
export interface DriverMeta {
  drv: string;
  num: number;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  team: string;
  colour: string;
  headshot_url: string | null;
}

interface RaceStore {
  conn: ConnStatus;
  session: SessionMsg | null;
  rows: LeaderboardRow[];
  weather: WeatherMsg | null;
  raceControl: RaceControlMsg | null;
  positions: PositionsMsg | null; // consumed by the Phase 2 track map
  telemetry: Record<string, CarTelemetryMsg>;
  predictions: Record<string, PredictionMsg>; // Phase 3 AI cards
  bestLap: Record<string, number>; // accumulated session best per driver
  driverMeta: Record<string, DriverMeta>; // Phase 4 panel headshots
  selectedDrv: string | null;
  view3D: boolean; // Phase 4 Track Detail (3D) overlay open
  page: "replay" | "live"; // Phase 5: which top-level page is active

  setConn: (s: ConnStatus) => void;
  setSelected: (drv: string | null) => void;
  setView3D: (open: boolean) => void;
  setPage: (p: "replay" | "live") => void;
  loadDrivers: (sessionId: string) => void;
  apply: (m: ServerMessage) => void;
}

export const useRaceStore = create<RaceStore>()(subscribeWithSelector((set, get) => ({
  conn: "connecting",
  session: null,
  rows: [],
  weather: null,
  raceControl: null,
  positions: null,
  telemetry: {},
  predictions: {},
  bestLap: {},
  driverMeta: {},
  selectedDrv: null,
  view3D: false,
  page: "replay",

  setConn: (conn) => set({ conn }),
  setSelected: (selectedDrv) => set({ selectedDrv }),
  setView3D: (view3D) => set({ view3D }),
  setPage: (page) => set({ page }),

  loadDrivers: (sessionId) => {
    fetch(`/api/drivers/${sessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((list: DriverMeta[]) => {
        const map: Record<string, DriverMeta> = {};
        for (const d of list) map[d.drv] = d;
        set({ driverMeta: map });
      })
      .catch(() => { /* panel falls back to initials avatar */ });
  },

  apply: (m) => {
    switch (m.kind) {
      case "session": {
        if (m.session_id !== get().session?.session_id) {
          set({ driverMeta: {} });
          get().loadDrivers(m.session_id);
        }
        return set({ session: m });
      }
      case "leaderboard":
        return set((s) => {
          const bestLap = { ...s.bestLap };
          for (const r of m.rows) {
            if (r.last_lap != null) {
              const prev = bestLap[r.drv];
              if (prev == null || r.last_lap < prev) bestLap[r.drv] = r.last_lap;
            }
          }
          return { rows: m.rows, bestLap };
        });
      case "weather":
        return set({ weather: m });
      case "race_control":
        return set({ raceControl: m });
      case "positions":
        return set({ positions: m });
      case "car_telemetry":
        return set((s) => ({ telemetry: { ...s.telemetry, [m.drv]: m } }));
      case "prediction":
        return set((s) => ({ predictions: { ...s.predictions, [m.drv]: m } }));
    }
  },
})));
