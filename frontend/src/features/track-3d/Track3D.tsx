// 3D Track Detail overlay (Phase 4). Opened from the map's "Track info" button.
// 3D circuit with live cars on the elevation-aware surface + a Track Detail panel
// (live conditions, circuit stats, past winners) and an elevation-profile strip.
// Camera modes: Orbit / Chase (the selected car) / Flyover (auto lap).
import { useEffect, useMemo, useRef, useState } from "react";

import { PositionBuffers, RENDER_LAG_S } from "../track-map/buffer";
import { useRaceStore } from "../../store/raceStore";
import { Scene3D, type Asset3D, type CarState3D } from "./scene";

import "./track3d.css";

type Mode = "orbit" | "chase" | "flyover";

interface Facts {
  name: string; country: string | null; year: number | null;
  laps: number; length_m: number | null; distance_m: number | null;
  first_gp: number | null; lap_record: string | null; lap_record_holder: string | null;
  winners: { year: number; driver: string; constructor: string }[];
}

export function Track3D() {
  const sessionId = useRaceStore((s) => s.session?.session_id ?? null);
  const sessionName = useRaceStore((s) => s.session?.name ?? "");
  const setView3D = useRaceStore((s) => s.setView3D);
  const weather = useRaceStore((s) => s.weather);

  const [asset, setAsset] = useState<Asset3D | null>(null);
  const [facts, setFacts] = useState<Facts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("orbit");
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<Scene3D | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    let dead = false;
    setAsset(null); setFacts(null); setError(null);
    fetch(`/api/track/${sessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((a: Asset3D) => { if (!dead) setAsset(a); })
      .catch((e: Error) => { if (!dead) setError(e.message); });
    fetch(`/api/circuit/${sessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("no facts"))))
      .then((f: Facts) => { if (!dead) setFacts(f); })
      .catch(() => { /* panel shows dashes */ });
    return () => { dead = true; };
  }, [sessionId]);

  useEffect(() => {
    if (!asset || !hostRef.current) return;
    const dark = document.documentElement.dataset.theme === "dark";
    const scene = new Scene3D(hostRef.current, asset, dark);
    sceneRef.current = scene;

    const buffers = new PositionBuffers();
    let estT = 0;
    let raf = 0;
    let lastWall = performance.now();
    const unsub = useRaceStore.subscribe(
      (s) => s.positions,
      (p) => {
        if (!p) return;
        const jumped = buffers.push(p.t, p.cars);
        if (jumped || estT === 0) estT = p.t - RENDER_LAG_S;
      },
    );
    const seed = useRaceStore.getState().positions;
    if (seed) { buffers.push(seed.t, seed.cars); estT = seed.t - RENDER_LAG_S; }

    const mo = new MutationObserver(() =>
      scene.setTheme(document.documentElement.dataset.theme === "dark"));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const ro = new ResizeObserver(() => scene.resize());
    ro.observe(hostRef.current);

    const loop = (now: number) => {
      const dt = Math.min((now - lastWall) / 1000, 0.25);
      lastWall = now;
      const st = useRaceStore.getState();
      const speed = st.session?.speed ?? 1;
      const paused = st.session?.paused ?? true;
      const newest = buffers.newestT;
      if (!paused && newest > 0) {
        const target = newest - RENDER_LAG_S;
        estT += dt * speed;
        const err = target - estT;
        if (Math.abs(err) > 3) estT = target;
        else estT += err * Math.min(1, dt * 2.0);
      }
      const colors = new Map<string, string>();
      for (const r of st.rows) colors.set(r.drv, `#${r.colour}`);
      const cars: CarState3D[] = [];
      for (const drv of buffers.drivers()) {
        const pos = buffers.at(drv, estT);
        if (!pos) continue;
        cars.push({ drv, x: pos.x, y: pos.y, color: colors.get(drv) ?? "#808080" });
      }
      scene.render(cars, useRaceStore.getState().selectedDrv);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      unsub(); mo.disconnect(); ro.disconnect();
      scene.dispose();
      sceneRef.current = null;
    };
  }, [asset]);

  useEffect(() => { sceneRef.current?.setMode(mode); }, [mode]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (sceneRef.current?.isPointerLocked()) return; // 1st Esc just exits the drone capture
      setView3D(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setView3D]);

  const km = (m: number | null) => (m ? `${(m / 1000).toFixed(3)} km` : "—");

  return (
    <div className="track3d">
      <div className="t3d-canvas" ref={hostRef} />

      <div className="t3d-bar">
        <div className="t3d-title">
          <span className="t3d-kicker">Track Detail · 3D</span>
          <span className="t3d-name">{sessionName}</span>
        </div>
        <div className="t3d-actions">
          <div className="t3d-modes">
            {(["orbit", "chase", "flyover"] as Mode[]).map((m) => (
              <button
                key={m}
                className={`t3d-mode${mode === m ? " on" : ""}`}
                onClick={() => setMode(m)}
                title={m === "chase" ? "Chase the selected car"
                  : m === "flyover" ? "Drone flyover — glides the lap with full free control"
                    : "Free orbit / pan"}
              >
                <ModeIcon mode={m} />
                <span>{m[0].toUpperCase() + m.slice(1)}</span>
              </button>
            ))}
          </div>
          <button className="t3d-btn t3d-close" onClick={() => setView3D(false)} aria-label="Close">✕</button>
        </div>
      </div>

      <aside className="t3d-panel">
        <Section title="Live conditions">
          {weather ? (
            <div className="t3d-grid">
              <Tile label="Air" value={`${weather.air.toFixed(0)}°C`} />
              <Tile label="Track" value={`${weather.track.toFixed(0)}°C`} />
              <Tile label="Wind" value={`${weather.wind.toFixed(1)} m/s`} />
              <Tile label="Rain" value={weather.rain ? "Yes" : "No"} />
            </div>
          ) : <p className="t3d-empty">awaiting conditions…</p>}
        </Section>

        <Section title="Circuit">
          <div className="t3d-grid">
            <Tile label="Laps" value={facts?.laps ? String(facts.laps) : "—"} />
            <Tile label="Lap length" value={km(facts?.length_m ?? null)} />
            <Tile label="Race distance" value={km(facts?.distance_m ?? null)} />
            <Tile label="First GP" value={facts?.first_gp ? String(facts.first_gp) : "—"} />
          </div>
          <div className="t3d-record">
            <span className="t3d-record-l">Fastest race lap</span>
            <span className="t3d-record-v">
              {facts?.lap_record ? `${facts.lap_record}` : "—"}
              {facts?.lap_record_holder ? ` · ${facts.lap_record_holder}` : ""}
            </span>
          </div>
        </Section>

        <Section title="Past winners">
          {facts && facts.winners.length ? (
            <ul className="t3d-winners">
              {facts.winners.map((w) => (
                <li key={`${w.year}-${w.driver}`}>
                  <span className="t3d-wy">{w.year}</span>
                  <span className="t3d-wd">{w.driver}</span>
                  <span className="t3d-wc">{w.constructor}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="t3d-empty">run scripts/fetch_circuit_facts.py (host) to populate</p>
          )}
        </Section>
      </aside>

      <ElevationStrip asset={asset} />

      {mode === "flyover" && asset && (
        <div className="t3d-fly-hint">
          <span className="t3d-fly-title">Drone</span>
          <span><kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> move</span>
          <span>mouse ←→ turn</span>
          <span>mouse ↑↓ altitude</span>
          <span className="t3d-fly-cap">click to capture · Esc to release</span>
        </div>
      )}

      {(error || !asset) && (
        <div className="t3d-hint">{error ? `track unavailable (${error})` : "building 3D track…"}</div>
      )}
    </div>
  );
}

function ModeIcon({ mode }: { mode: Mode }) {
  const p = {
    width: 13, height: 13, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
  };
  if (mode === "orbit") {
    return (
      <svg {...p}>
        <path d="M12 3v18M3 12h18" />
        <path d="M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5" />
      </svg>
    );
  }
  if (mode === "chase") {
    return (
      <svg {...p}>
        <path d="M4 14l1.8-4.5A2 2 0 0 1 7.7 8h8.6a2 2 0 0 1 1.9 1.5L20 14" />
        <rect x="3" y="14" width="18" height="3.5" rx="1" />
        <circle cx="7.5" cy="18" r="1.6" />
        <circle cx="16.5" cy="18" r="1.6" />
      </svg>
    );
  }
  return (
    <svg {...p}>
      <circle cx="5" cy="5" r="2.4" />
      <circle cx="19" cy="5" r="2.4" />
      <circle cx="5" cy="19" r="2.4" />
      <circle cx="19" cy="19" r="2.4" />
      <path d="M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1.2" />
    </svg>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section className={`t3d-section${open ? "" : " closed"}`}>
      <button className="t3d-sec-h" onClick={() => setOpen((v) => !v)}>
        <span>{title}</span><span className="t3d-caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="t3d-sec-body">{children}</div>}
    </section>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="t3d-tile">
      <span className="t3d-tile-v">{value}</span>
      <span className="t3d-tile-l">{label}</span>
    </div>
  );
}

function ElevationStrip({ asset }: { asset: Asset3D | null }) {
  const path = useMemo(() => {
    const e = asset?.elevation;
    if (!e || e.length < 4) return null;
    const W = 1000, H = 70;
    const max = Math.max(...e, 0.001);
    const step = W / (e.length - 1);
    const top = e.map((v, i) => `${(i * step).toFixed(1)},${(H - 6 - (v / max) * (H - 14)).toFixed(1)}`);
    return { line: `0,${H} ${top.join(" ")} ${W},${H}`, max };
  }, [asset]);
  if (!path) return null;
  return (
    <div className="t3d-elev" title="Lap elevation profile">
      <span className="t3d-elev-l">Elevation · +{path.max.toFixed(0)}</span>
      <svg viewBox="0 0 1000 70" preserveAspectRatio="none">
        <polygon points={path.line} />
      </svg>
    </div>
  );
}
