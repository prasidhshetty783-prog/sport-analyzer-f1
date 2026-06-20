import { useEffect, useRef, useState } from "react";

import { fmtGap, fmtLap, intervalSeconds } from "../../lib/format";
import type { LeaderboardRow } from "../../lib/ws/types";
import { useRaceStore } from "../../store/raceStore";

const COMPOUND_STYLE: Record<string, { label: string; cls: string }> = {
  SOFT: { label: "S", cls: "tyre-soft" },
  MEDIUM: { label: "M", cls: "tyre-medium" },
  HARD: { label: "H", cls: "tyre-hard" },
  INTERMEDIATE: { label: "I", cls: "tyre-inter" },
  WET: { label: "W", cls: "tyre-wet" },
};

export function Leaderboard({ onSelect }: { onSelect?: () => void } = {}) {
  const rows = useRaceStore((s) => s.rows);
  const selected = useRaceStore((s) => s.selectedDrv);
  const setSelected = useRaceStore((s) => s.setSelected);
  const trends = usePositionTrends(rows);

  return (
    <aside className="leaderboard">
      <div className="lb-head">
        <span className="lb-h-pos">P</span>
        <span />
        <span>DRIVER</span>
        <span className="num">GAP</span>
        <span className="num">INT</span>
        <span className="num">LAST</span>
        <span className="num">TYRE</span>
        <span className="num">PIT</span>
      </div>
      <div className="lb-rows" style={{ height: rows.length * 44 }}>
        {rows.map((r) => (
          <Row
            key={r.drv}
            row={r}
            trend={trends.get(r.drv) ?? 0}
            selected={selected === r.drv}
            onClick={() => { setSelected(selected === r.drv ? null : r.drv); onSelect?.(); }}
          />
        ))}
      </div>
    </aside>
  );
}

function Row({ row, trend, selected, onClick }: {
  row: LeaderboardRow; trend: number; selected: boolean; onClick: () => void;
}) {
  const battle = (intervalSeconds(row.interval) ?? Infinity) < 1.0 && row.pos > 1;
  const tyre = row.compound ? COMPOUND_STYLE[row.compound] : null;

  return (
    <div
      className={`lb-row${selected ? " selected" : ""}${battle ? " battle" : ""}`}
      style={{ transform: `translateY(${(row.pos - 1) * 44}px)` }}
      onClick={onClick}
    >
      <span className="lb-pos">
        {row.pos}
        {trend !== 0 && (
          <i className={trend < 0 ? "up" : "down"}>{trend < 0 ? "▲" : "▼"}</i>
        )}
      </span>
      <span className="lb-team" style={{ background: `#${row.colour}` }} />
      <span className="lb-drv">{row.drv}</span>
      <span className="lb-gap num">{row.pos === 1 ? "LEADER" : fmtGap(row.gap_leader)}</span>
      <span className="lb-int num">{row.pos === 1 ? "—" : fmtGap(row.interval)}</span>
      <span className="lb-last num">{fmtLap(row.last_lap)}</span>
      <span className="lb-tyre num">
        {tyre && <i className={`tyre ${tyre.cls}`}>{tyre.label}</i>}
        <em>{row.tyre_age ?? "—"}</em>
      </span>
      <span className="lb-pits num">{row.pits ?? 0}</span>
    </div>
  );
}

/** -1 = gained places recently, +1 = lost. Decays after 4 s. */
function usePositionTrends(rows: LeaderboardRow[]): Map<string, number> {
  const prev = useRef<Map<string, number>>(new Map());
  const [trends, setTrends] = useState<Map<string, number>>(new Map());
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    const next = new Map(trends);
    let changed = false;
    for (const r of rows) {
      const before = prev.current.get(r.drv);
      if (before !== undefined && before !== r.pos) {
        next.set(r.drv, r.pos > before ? 1 : -1);
        changed = true;
        const old = timers.current.get(r.drv);
        if (old) clearTimeout(old);
        timers.current.set(r.drv, setTimeout(() => {
          setTrends((t) => {
            const copy = new Map(t);
            copy.delete(r.drv);
            return copy;
          });
        }, 4000));
      }
      prev.current.set(r.drv, r.pos);
    }
    if (changed) setTrends(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  return trends;
}
