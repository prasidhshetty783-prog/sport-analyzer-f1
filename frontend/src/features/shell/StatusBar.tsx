import { useEffect, useMemo, useState } from "react";

import { fmtClock } from "../../lib/format";
import type { ClientMessage } from "../../lib/ws/types";
import { useRaceStore } from "../../store/raceStore";
import type { Page } from "./PageTabs";

interface SessionLite { session_id: string; name: string; }

export function StatusBar({ send, page, sessions, onToggleNav }: {
  send: (c: ClientMessage) => void;
  page: Page;
  sessions: SessionLite[];
  onToggleNav?: () => void;
}) {
  const session = useRaceStore((s) => s.session);
  const weather = useRaceStore((s) => s.weather);
  const conn = useRaceStore((s) => s.conn);
  const flag = session?.flag ?? "GREEN";
  const isLive = page === "live";
  const liveStreaming = session?.mode === "live" && !/no live/i.test(session?.name ?? "");
  const showInfo = isLive ? liveStreaming : true;

  return (
    <header className="statusbar" data-flag={flag} data-page={page}>
      <div className="sb-left">
        <button className="sb-nav" onClick={onToggleNav} aria-label="Toggle leaderboard">☰</button>
        {isLive ? (
          <span className="sb-name sb-name-live">{liveStreaming ? session?.name : "Live timing"}</span>
        ) : (
          <RaceFilter send={send} sessions={sessions} />
        )}
        {isLive ? (
          liveStreaming && (
            <span className="sb-mode sb-mode-live">
              ● LIVE
              <span className="sb-delay">broadcast +{(session?.delay_s ?? 0).toFixed(0)}s</span>
            </span>
          )
        ) : (
          <span className="sb-mode">
            REPLAY<span className="sb-delay">broadcast-synced</span>
          </span>
        )}
        <span className={`sb-conn sb-conn-${conn}`} title={`connection: ${conn}`} />
      </div>

      <div className="sb-center">
        {showInfo && (
          <span className="sb-lap">
            LAP <b>{session?.lap ?? 0}</b>/{session?.total_laps ? session.total_laps : "–"}
          </span>
        )}
        {showInfo && weather && (
          <span className="sb-weather" title="air / track / wind">
            {weather.rain ? "🌧" : "☁"} {weather.air.toFixed(0)}° air ·{" "}
            {weather.track.toFixed(0)}° track · {weather.wind.toFixed(0)} m/s
          </span>
        )}
      </div>

      <div className="sb-right">
        <Transport send={send} page={page} />
        <ThemeToggle />
      </div>
    </header>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<string>(
    () => localStorage.getItem("sa-theme") ?? "light",
  );
  useEffect(() => {
    if (theme === "dark") document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    localStorage.setItem("sa-theme", theme);
  }, [theme]);
  return (
    <button
      className="sb-icon"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      title={`switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? "☀" : "☾"}
    </button>
  );
}

interface SessionMeta { session_id: string; name: string; year: string; label: string; }

/** Strip the leading "FORMULA 1" and the year so the race dropdown reads cleanly
 *  (e.g. "ROLEX AUSTRALIAN GRAND PRIX"). Year is the last 4-digit run in the name. */
function parseSession(s: SessionLite): SessionMeta {
  const years = s.name.match(/(?:19|20)\d{2}/g);
  const year = years ? years[years.length - 1] : "—";
  const label = s.name
    .replace(/^formula\s*1\s+/i, "")
    .replace(/(?:19|20)\d{2}/g, "")
    .replace(/\s{2,}/g, " ")
    .trim() || s.name;
  return { ...s, year, label };
}

/** Replay-only race picker: Year then Grand Prix (the live entry lives in the
 *  page tabs now, not here). Sessions are passed in from App (already filtered). */
function RaceFilter({ send, sessions }: {
  send: (c: ClientMessage) => void;
  sessions: SessionLite[];
}) {
  const current = useRaceStore((s) => s.session?.session_id);
  const name = useRaceStore((s) => s.session?.name);

  const parsed = useMemo(() => sessions.map(parseSession), [sessions]);
  const years = useMemo(
    () => Array.from(new Set(parsed.map((p) => p.year))).sort().reverse(),
    [parsed],
  );
  const currentYear = parsed.find((p) => p.session_id === current)?.year;

  const [year, setYear] = useState<string>("");
  useEffect(() => {
    if (currentYear) setYear(currentYear);
    else if (years.length && !year) setYear(years[0]);
  }, [currentYear, years, year]);

  if (sessions.length <= 1) return <span className="sb-name">{name ?? "—"}</span>;

  const racesInYear = parsed
    .filter((p) => p.year === year)
    .sort((a, b) => a.label.localeCompare(b.label));
  const raceValue = racesInYear.some((r) => r.session_id === current) ? current : "";

  return (
    <div className="sb-filters" title="Filter races by year, then pick the Grand Prix">
      <select
        className="sb-sel sb-sel-year"
        value={year}
        onChange={(e) => setYear(e.target.value)}
        aria-label="Season"
      >
        {years.map((y) => (
          <option key={y} value={y}>{y}</option>
        ))}
      </select>
      <select
        className="sb-sel sb-sel-race"
        value={raceValue ?? ""}
        onChange={(e) => send({ kind: "select_session", session_id: e.target.value })}
        aria-label="Grand Prix"
      >
        {raceValue === "" && <option value="" disabled>Select Grand Prix…</option>}
        {racesInYear.map((r) => (
          <option key={r.session_id} value={r.session_id}>{r.label}</option>
        ))}
      </select>
    </div>
  );
}

const SPEEDS = [1, 2, 10];

function Transport({ send, page }: {
  send: (c: ClientMessage) => void;
  page: Page;
}) {
  const session = useRaceStore((s) => s.session);
  const [scrub, setScrub] = useState<number | null>(null);
  const liveStreaming = session?.mode === "live" && !/no live/i.test(session?.name ?? "");

  // Live: only freeze/resume (you can't scrub or fast-forward a broadcast); and
  // nothing at all while on the standby screen.
  if (page === "live") {
    if (!liveStreaming) return null;
    return (
      <div className="sb-transport sb-transport-live">
        <button
          className="sb-play"
          onClick={() => send({ kind: "transport", action: session?.paused ? "play" : "pause" })}
          title={session?.paused ? "Resume live" : "Freeze"}
        >
          {session?.paused ? "▶" : "⏸"}
        </button>
        <span className="sb-time sb-time-live">{fmtClock(session?.t_s ?? 0)}</span>
      </div>
    );
  }

  const t = scrub ?? session?.t_s ?? 0;
  const dur = session?.duration_s ?? 1;
  return (
    <div className="sb-transport">
      <button
        className="sb-play"
        onClick={() => send({ kind: "transport", action: session?.paused ? "play" : "pause" })}
      >
        {session?.paused ? "▶" : "⏸"}
      </button>
      <div className="sb-speeds">
        {SPEEDS.map((sp) => (
          <button
            key={sp}
            className={session?.speed === sp ? "active" : ""}
            onClick={() => send({ kind: "transport", action: "speed", speed: sp })}
          >
            {sp}×
          </button>
        ))}
      </div>
      <input
        type="range"
        min={0}
        max={dur}
        step={1}
        value={t}
        onChange={(e) => setScrub(Number(e.target.value))}
        onMouseUp={() => {
          if (scrub != null) send({ kind: "transport", action: "seek", seek_s: scrub });
          setScrub(null);
        }}
        onTouchEnd={() => {
          if (scrub != null) send({ kind: "transport", action: "seek", seek_s: scrub });
          setScrub(null);
        }}
      />
      <span className="sb-time">
        {fmtClock(t)} / {fmtClock(dur)}
      </span>
    </div>
  );
}
