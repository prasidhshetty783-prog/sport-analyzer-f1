// Car Detail panel (§4.2): right-side slide-in for the selected driver.
// Every field is tagged LIVE / EST / AI so model output is never mistaken for
// telemetry. AI cards (tyre life, pit window, predicted finish) come from the
// Phase 3 prediction engine and show their freshness.
import { useMemo, useState } from "react";

import { fmtLap, intervalSeconds } from "../../lib/format";
import type { LeaderboardRow } from "../../lib/ws/types";
import { useRaceStore } from "../../store/raceStore";
import "./car-panel.css";

type Tag = "LIVE" | "EST" | "AI";

const COMPOUND: Record<string, { label: string; cls: string }> = {
  SOFT: { label: "SOFT", cls: "tyre-soft" },
  MEDIUM: { label: "MED", cls: "tyre-medium" },
  HARD: { label: "HARD", cls: "tyre-hard" },
  INTERMEDIATE: { label: "INTER", cls: "tyre-inter" },
  WET: { label: "WET", cls: "tyre-wet" },
};

function TagChip({ t }: { t: Tag }) {
  return <span className={`tag tag-${t.toLowerCase()}`}>{t}</span>;
}

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

export function CarPanel() {
  const drv = useRaceStore((s) => s.selectedDrv);
  const rows = useRaceStore((s) => s.rows);
  const tel = useRaceStore((s) => (drv ? s.telemetry[drv] : undefined));
  const pred = useRaceStore((s) => (drv ? s.predictions[drv] : undefined));
  const best = useRaceStore((s) => (drv ? s.bestLap[drv] : undefined));
  const meta = useRaceStore((s) => (drv ? s.driverMeta[drv] : undefined));
  const session = useRaceStore((s) => s.session);
  const setSelected = useRaceStore((s) => s.setSelected);
  const [tab, setTab] = useState<"overview" | "car">("overview");

  const row = useMemo(() => rows.find((r) => r.drv === drv), [rows, drv]);
  const behind = useMemo(
    () => (row ? rows.find((r) => r.pos === row.pos + 1) : undefined),
    [rows, row],
  );

  if (!drv || !row) return null;

  const dirty = (intervalSeconds(row.interval) ?? Infinity) < 2.0 && row.pos > 1;
  const tyre = row.compound ? COMPOUND[row.compound] : null;
  const freshness =
    pred && session ? Math.max(0, Math.round(session.t_s - pred.updated_at)) : null;

  const driverName = formatName(meta, row.drv);

  return (
    <aside className="car-panel" data-open="true">
      <header className="cp-photo" style={{ ["--team" as string]: `#${row.colour}` }}>
        <button className="cp-close" onClick={() => setSelected(null)} aria-label="Close">
          ✕
        </button>
        <DriverAvatar url={meta?.headshot_url ?? null} drv={row.drv} colour={row.colour} />
        <div className="cp-photo-info">
          <span className="cp-photo-num">#{meta?.num ?? "—"}</span>
          <span className="cp-photo-name">{driverName}</span>
          <span className="cp-photo-team">{row.team}</span>
        </div>
        <span className="cp-photo-pos">
          <em>POS</em>
          <strong>P{row.pos}</strong>
        </span>
      </header>

      <div className="cp-body">
        <div className="cp-tabs" role="tablist">
          <button
            className={`cp-tab${tab === "overview" ? " on" : ""}`}
            onClick={() => setTab("overview")}
            role="tab"
            aria-selected={tab === "overview"}
          >
            Overview
          </button>
          <button
            className={`cp-tab${tab === "car" ? " on" : ""}`}
            onClick={() => setTab("car")}
            role="tab"
            aria-selected={tab === "car"}
          >
            Car
          </button>
        </div>

        {tab === "car" ? (
          <CarSchematic tel={tel} row={row} pred={pred} />
        ) : (
        <>
        {/* ---------------- LIVE telemetry ---------------- */}
        <section className="cp-card">
          <div className="cp-card-h">
            <span>Telemetry</span>
            <TagChip t="LIVE" />
          </div>
          <div className="cp-speed">
            <strong>{tel ? Math.round(tel.speed) : "—"}</strong>
            <em>km/h</em>
            <span className={`cp-drs${tel?.drs ? " on" : ""}`}>DRS</span>
            <span className="cp-gear">{tel ? `G${tel.gear}` : "—"}</span>
          </div>
          <PedalBar label="THR" value={tel?.throttle ?? 0} cls="thr" />
          <PedalBar label="BRK" value={tel?.brake ?? 0} cls="brk" />
        </section>

        {/* ---------------- LIVE timing ---------------- */}
        <section className="cp-card">
          <div className="cp-card-h">
            <span>Timing</span>
            <TagChip t="LIVE" />
          </div>
          <div className="cp-grid2">
            <Stat label="Last lap" value={fmtLap(row.last_lap)} />
            <Stat label="Best lap" value={fmtLap(best ?? null)} />
            <Stat label="Gap ahead" value={row.pos === 1 ? "LEADER" : gapStr(row)} />
            <Stat label="Gap behind" value={behind ? gapStr(behind) : "—"} />
          </div>
        </section>

        {/* ---------------- Tyres: LIVE compound + AI life ---------------- */}
        <section className="cp-card">
          <div className="cp-card-h">
            <span>Tyres</span>
            <span className="cp-tags">
              <TagChip t="LIVE" />
              <TagChip t="AI" />
            </span>
          </div>
          <div className="cp-tyre-row">
            {tyre && <i className={`tyre-dot ${tyre.cls}`} />}
            <strong>{tyre?.label ?? "—"}</strong>
            <em>{row.tyre_age ?? "—"} laps</em>
            {pred && (
              <span className="cp-cliff">
                {pred.tyre.laps_to_cliff <= 0.5
                  ? "past the cliff"
                  : `~${Math.round(pred.tyre.laps_to_cliff)} laps to cliff`}
              </span>
            )}
          </div>
          {pred && (
            <>
              <DegSparkline degRate={pred.tyre.deg_rate} cliff={pred.tyre.laps_to_cliff} />
              <div className="cp-sub">
                deg {pred.tyre.deg_rate.toFixed(2)} s/lap
                <span className={`cp-air ${dirty ? "dirty" : "clean"}`}>
                  {dirty ? "dirty air" : "clean air"} <TagChip t="EST" />
                </span>
              </div>
            </>
          )}
        </section>

        {/* ---------------- Fuel (EST) ---------------- */}
        <section className="cp-card">
          <div className="cp-card-h">
            <span>Fuel</span>
            <TagChip t="EST" />
          </div>
          {pred ? (
            <div className="cp-grid2">
              <Stat label="Remaining" value={`${pred.fuel.kg.toFixed(1)} kg`} />
              <Stat label="Laps of fuel" value={`${pred.fuel.laps.toFixed(1)}`} />
            </div>
          ) : (
            <p className="cp-empty">awaiting estimate…</p>
          )}
        </section>

        {/* ---------------- Strategy (AI) ---------------- */}
        <section className="cp-card">
          <div className="cp-card-h">
            <span>Strategy</span>
            <TagChip t="AI" />
          </div>
          <div className="cp-grid2">
            <Stat label="Stops made" value={`${row.pits ?? 0}`} />
            <Stat label="Stops left" value={pitWindow(pred, session)} />
          </div>
        </section>

        {/* ---------------- Predicted finish (AI) ---------------- */}
        <section className="cp-card cp-card-accent">
          <div className="cp-card-h">
            <span>Predicted finish</span>
            <span className="cp-tags">
              <TagChip t="AI" />
              {freshness != null && <span className="cp-fresh">updated {freshness}s ago</span>}
            </span>
          </div>
          {pred ? (
            <>
              <div className="cp-exp">
                <strong>P{Math.round(pred.finish.exp)}</strong>
                <em>expected (avg {pred.finish.exp.toFixed(1)})</em>
              </div>
              <div className="cp-probs">
                <Prob label="WIN" v={pred.finish.p_win} />
                <Prob label="PODIUM" v={pred.finish.p_podium} />
                <Prob label="POINTS" v={pred.finish.p_points} />
              </div>
              <FinishDist dist={pred.finish.dist} exp={pred.finish.exp} />
            </>
          ) : (
            <p className="cp-empty">running simulation…</p>
          )}
        </section>
        </>
        )}
      </div>
    </aside>
  );
}

/** F1-25-style top-down car schematic. Honest by design: only real broadcast
 *  data is shown LIVE (speed, gear, throttle/brake, DRS); the tyre set is LIVE
 *  (compound + stint age), with AI tyre-life and EST fuel beneath. No tyre/brake
 *  temps or ERS — those aren't in the feed, so they're deliberately omitted. */
function CarSchematic({ tel, row, pred }: {
  tel?: { speed: number; gear: number; throttle: number; brake: number; drs: number | boolean };
  row: LeaderboardRow;
  pred?: { tyre: { laps_to_cliff: number }; fuel: { kg: number; laps: number } };
}) {
  const tyre = row.compound ? COMPOUND[row.compound] : null;
  const fill = tyreVar(row.compound);
  const age = row.tyre_age ?? null;
  const ageLabel = age != null ? String(age) : "";
  return (
    <div className="cp-car">
      <div className="cp-car-stage">
        <svg viewBox="0 0 200 320" className="cp-car-svg" aria-hidden="true">
          {/* front + rear wings */}
          <rect x="34" y="14" width="132" height="13" rx="5" className="cp-car-wing" />
          <rect x="30" y="288" width="140" height="16" rx="5" className="cp-car-wing" />
          {/* nose + chassis (team colour) */}
          <path d="M100 20 L116 70 L116 250 L84 250 L84 70 Z" fill={`#${row.colour}`} />
          <rect x="72" y="120" width="56" height="96" rx="10" fill={`#${row.colour}`} opacity="0.9" />
          {/* halo / cockpit hint */}
          <circle cx="100" cy="150" r="13" className="cp-car-cockpit" />
          {/* four wheels in the current compound colour */}
          <g>
            <rect x="26" y="60" width="26" height="52" rx="7" fill={fill} />
            <rect x="148" y="60" width="26" height="52" rx="7" fill={fill} />
            <rect x="22" y="214" width="30" height="58" rx="8" fill={fill} />
            <rect x="148" y="214" width="30" height="58" rx="8" fill={fill} />
          </g>
          {ageLabel && (
            <g className="cp-car-age">
              <text x="37" y="248" textAnchor="middle">{ageLabel}</text>
              <text x="163" y="248" textAnchor="middle">{ageLabel}</text>
            </g>
          )}
        </svg>

        <div className="cp-car-core">
          <span className="cp-car-speed">{tel ? Math.round(tel.speed) : "—"}</span>
          <span className="cp-car-unit">km/h</span>
          <span className="cp-car-gear">{tel ? `G${tel.gear}` : "—"}</span>
        </div>
        <span className={`cp-car-drs${tel?.drs ? " on" : ""}`}>DRS</span>
      </div>

      <div className="cp-car-pedals">
        <PedalBar label="THR" value={tel?.throttle ?? 0} cls="thr" />
        <PedalBar label="BRK" value={tel?.brake ?? 0} cls="brk" />
      </div>

      <div className="cp-car-foot">
        <div className="cp-car-line">
          <span className="cp-car-line-l">Tyre set</span>
          <span className="cp-car-line-v">
            {tyre && <i className={`tyre-dot ${tyre.cls}`} />}
            {tyre?.label ?? "—"} · {age ?? "—"} laps
          </span>
          <TagChip t="LIVE" />
        </div>
        {pred && (
          <div className="cp-car-line">
            <span className="cp-car-line-l">Tyre life</span>
            <span className="cp-car-line-v">
              {pred.tyre.laps_to_cliff <= 0.5
                ? "past the cliff"
                : `~${Math.round(pred.tyre.laps_to_cliff)} laps to cliff`}
            </span>
            <TagChip t="AI" />
          </div>
        )}
        {pred && (
          <div className="cp-car-line">
            <span className="cp-car-line-l">Fuel</span>
            <span className="cp-car-line-v">{pred.fuel.laps.toFixed(1)} laps · {pred.fuel.kg.toFixed(1)} kg</span>
            <TagChip t="EST" />
          </div>
        )}
      </div>
    </div>
  );
}

function tyreVar(c: string | null | undefined): string {
  switch (c) {
    case "SOFT": return "var(--color-tyre-soft)";
    case "MEDIUM": return "var(--color-tyre-medium)";
    case "HARD": return "var(--color-tyre-hard)";
    case "INTERMEDIATE": return "var(--color-tyre-inter)";
    case "WET": return "var(--color-tyre-wet)";
    default: return "var(--color-text-muted)";
  }
}

/** Headshot with graceful fallback to a team-coloured initials avatar when the
 *  URL is missing or the image fails to load (e.g. offline / blocked). */
function DriverAvatar({ url, drv, colour }: { url: string | null; drv: string; colour: string }) {
  const [failed, setFailed] = useState(false);
  if (url && !failed) {
    return (
      <img
        className="cp-avatar"
        src={url}
        alt={drv}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <div className="cp-avatar cp-avatar-fb" style={{ background: `#${colour}` }}>
      {drv}
    </div>
  );
}

function formatName(
  meta: { full_name: string; first_name: string | null; last_name: string | null } | undefined,
  fallback: string,
): string {
  if (!meta) return fallback;
  if (meta.first_name && meta.last_name) return `${meta.first_name} ${meta.last_name}`;
  if (meta.full_name) {
    // OpenF1 ships "Max VERSTAPPEN" — title-case the SHOUTED surname.
    return meta.full_name
      .split(" ")
      .map((w) => (w.length > 1 ? w[0] + w.slice(1).toLowerCase() : w))
      .join(" ");
  }
  return fallback;
}

function gapStr(r: LeaderboardRow): string {
  const s = intervalSeconds(r.interval);
  if (s == null) return r.interval ?? "—";
  return `+${s.toFixed(3)}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="cp-stat">
      <span className="cp-stat-l">{label}</span>
      <span className="cp-stat-v">{value}</span>
    </div>
  );
}

function PedalBar({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <div className="cp-pedal">
      <span>{label}</span>
      <div className="cp-pedal-track">
        <div className={`cp-pedal-fill ${cls}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}

function Prob({ label, v }: { label: string; v: number }) {
  return (
    <div className="cp-prob">
      <span className="cp-prob-v">{pct(v)}</span>
      <span className="cp-prob-l">{label}</span>
    </div>
  );
}

function pitWindow(
  pred: { tyre: { laps_to_cliff: number } } | undefined,
  session: { lap: number; total_laps: number } | null,
): string {
  if (!pred || !session) return "—";
  const remaining = session.total_laps - session.lap;
  const cliff = pred.tyre.laps_to_cliff;
  if (cliff >= remaining - 1) return "can run to flag";
  const a = session.lap + Math.max(1, Math.round(cliff) - 2);
  const b = session.lap + Math.round(cliff) + 2;
  return `≈1 more · L${a}–L${b}`;
}

/** Degradation sparkline synthesised from deg rate + laps-to-cliff (no extra
 *  protocol payload): linear wear then a quadratic ramp past the cliff. */
function DegSparkline({ degRate, cliff }: { degRate: number; cliff: number }) {
  const H = 14;
  const W = 220;
  const HT = 46;
  const pts: number[] = [];
  for (let k = 0; k <= H; k++) {
    const over = Math.max(0, k - cliff);
    pts.push(degRate * k + 0.07 * over * over);
  }
  const max = Math.max(0.5, ...pts);
  const path = pts
    .map((v, i) => `${(i / H) * W},${HT - (v / max) * (HT - 4) - 2}`)
    .join(" ");
  const cliffX = cliff <= H ? (cliff / H) * W : null;
  return (
    <svg className="cp-spark" viewBox={`0 0 ${W} ${HT}`} preserveAspectRatio="none">
      {cliffX != null && (
        <line className="cp-spark-cliff" x1={cliffX} y1="0" x2={cliffX} y2={HT} />
      )}
      <polyline className="cp-spark-line" points={path} fill="none" />
    </svg>
  );
}

/** Finish-position distribution bar chart from the Monte-Carlo output. */
function FinishDist({ dist, exp }: { dist: number[]; exp: number }) {
  const max = Math.max(0.01, ...dist);
  const expIdx = Math.round(exp) - 1;
  return (
    <div className="cp-dist" title="P(finish position)">
      {dist.map((p, i) => (
        <div
          key={i}
          className={`cp-dist-bar${i === expIdx ? " exp" : ""}`}
          style={{ height: `${(p / max) * 100}%` }}
          title={`P${i + 1}: ${pct(p)}`}
        />
      ))}
    </div>
  );
}
