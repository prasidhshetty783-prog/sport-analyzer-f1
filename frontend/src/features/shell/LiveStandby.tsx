import { useRaceStore } from "../../store/raceStore";

/** Shown on the Live page when there's nothing live to display. Two honest
 *  cases: no token configured (live disabled), or token set but no race is
 *  currently green. Never shows a stale grid. */
export function LiveStandby({ liveAvailable }: { liveAvailable: boolean }) {
  const conn = useRaceStore((s) => s.conn);

  if (!liveAvailable) {
    return (
      <div className="live-standby">
        <div className="live-standby-card">
          <div className="live-standby-mark off">●</div>
          <h2>Live timing is off</h2>
          <p>
            Live race mode needs a paid OpenF1 token. Add{" "}
            <code>OPENF1_TOKEN</code> to your <code>.env</code> file and restart
            the backend to turn it on.
          </p>
          <p className="live-standby-muted">
            Meanwhile, the <strong>Replay</strong> page has every recorded race
            with the full track map and AI predictions.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="live-standby">
      <div className="live-standby-card">
        <div className="live-standby-mark pulse">●</div>
        <h2>Waiting for a live session…</h2>
        <p>
          No Formula&nbsp;1 session is live right now. This page fills in
          automatically the moment a race goes green — leave it open.
        </p>
        <p className="live-standby-muted">
          Feed connection: <span className={`live-standby-conn ${conn}`}>{conn}</span>
        </p>
      </div>
    </div>
  );
}
