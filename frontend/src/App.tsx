import { useEffect, useMemo, useRef, useState } from "react";

import { CarPanel } from "./features/car-panel/CarPanel";
import { FlagToast } from "./features/shell/FlagToast";
import { Leaderboard } from "./features/leaderboard/Leaderboard";
import { LiveStandby } from "./features/shell/LiveStandby";
import { PageTabs, type Page } from "./features/shell/PageTabs";
import { StatusBar } from "./features/shell/StatusBar";
import { Track3D } from "./features/track-3d/Track3D";
import { TrackMap } from "./features/track-map/TrackMap";
import { RaceSocket } from "./lib/ws/client";
import type { ClientMessage } from "./lib/ws/types";
import { useRaceStore } from "./store/raceStore";

import "./styles/global.css";
import "./features/shell/shell.css";
import "./features/leaderboard/leaderboard.css";

const LIVE_ID = "live";

interface SessionLite { session_id: string; name: string; }

function wsUrl(): string {
  const env = import.meta.env.VITE_WS_URL as string | undefined;
  if (env) return env;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

export default function App() {
  const apply = useRaceStore((s) => s.apply);
  const setConn = useRaceStore((s) => s.setConn);

  const socket = useMemo(() => new RaceSocket(wsUrl(), apply, setConn), [apply, setConn]);
  useEffect(() => {
    socket.connect();
    return () => socket.close();
  }, [socket]);

  const send = (c: ClientMessage) => socket.send(c);
  const flag = useRaceStore((s) => s.session?.flag ?? "GREEN");
  const [navOpen, setNavOpen] = useState(false);

  const page = useRaceStore((s) => s.page);
  const setPage = useRaceStore((s) => s.setPage);
  const session = useRaceStore((s) => s.session);

  // Session list drives both the Replay picker and whether Live is offered
  // (the backend only includes a "live" entry when a token is configured).
  const [sessions, setSessions] = useState<SessionLite[]>([]);
  useEffect(() => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then((list) => setSessions(Array.isArray(list) ? list : []))
      .catch(() => setSessions([]));
  }, []);
  const liveAvailable = sessions.some((s) => s.session_id === LIVE_ID);
  const replaySessions = useMemo(
    () => sessions.filter((s) => s.session_id !== LIVE_ID),
    [sessions],
  );

  // remember the last replay race so returning to the Replay tab restores it
  const lastReplay = useRef<string | null>(null);
  useEffect(() => {
    if (page === "replay" && session?.session_id && session.session_id !== LIVE_ID) {
      lastReplay.current = session.session_id;
    }
  }, [page, session?.session_id]);

  function switchPage(next: Page) {
    if (next === page) return;
    setPage(next);
    setNavOpen(false);
    if (next === "live") {
      if (liveAvailable) send({ kind: "select_session", session_id: LIVE_ID });
    } else {
      const target = lastReplay.current ?? replaySessions[0]?.session_id;
      if (target) send({ kind: "select_session", session_id: target });
    }
  }

  // On the Live page, only show the dashboard when a race is actually streaming;
  // otherwise show the standby/waiting screen.
  const liveStreaming = session?.mode === "live" && !/no live/i.test(session?.name ?? "");
  const showStandby = page === "live" && !liveStreaming;

  return (
    <div className="app-root">
      <PageTabs page={page} onChange={switchPage} liveAvailable={liveAvailable} />
      <div className="app-body">
        <div className="shell" data-flag={flag} data-page={page}
             data-nav={navOpen ? "open" : "closed"}>
          <StatusBar send={send} page={page} sessions={replaySessions}
                     onToggleNav={() => setNavOpen((o) => !o)} />
          {showStandby ? (
            <LiveStandby liveAvailable={liveAvailable} />
          ) : (
            <>
              <Leaderboard onSelect={() => setNavOpen(false)} />
              <div className="shell-backdrop" onClick={() => setNavOpen(false)} />
              <MainArea />
            </>
          )}
          <FlagToast />
        </div>
      </div>
    </div>
  );
}

function MainArea() {
  const view3D = useRaceStore((s) => s.view3D);
  return (
    <main className="main">
      <TrackMap />
      <CarPanel />
      {view3D && <Track3D />}
    </main>
  );
}
