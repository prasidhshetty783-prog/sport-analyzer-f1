import { useEffect, useRef, useState } from "react";

import { fmtClock } from "../../lib/format";
import { useRaceStore } from "../../store/raceStore";
import { MapEngine, MAX_ZOOM, MIN_ZOOM, type TrackAsset } from "./engine";

import "./trackmap.css";

const STEP = 1.4;

export function TrackMap() {
  const sessionId = useRaceStore((s) => s.session?.session_id ?? null);
  const setSelected = useRaceStore((s) => s.setSelected);
  const selectedDrv = useRaceStore((s) => s.selectedDrv);
  const [asset, setAsset] = useState<TrackAsset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<MapEngine | null>(null);
  const drag = useRef({ active: false, moved: false, x: 0, y: 0 });

  useEffect(() => {
    if (!sessionId) return;
    let dead = false;
    setAsset(null);
    setError(null);
    fetch(`/api/track/${sessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((a: TrackAsset) => { if (!dead) setAsset(a); })
      .catch((e: Error) => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, [sessionId]);

  useEffect(() => {
    if (!asset || !canvasRef.current || !wrapRef.current) return;
    const engine = new MapEngine(canvasRef.current, wrapRef.current, asset);
    engineRef.current = engine;
    engine.start();
    setZoom(1);
    return () => {
      engine.stop();
      engineRef.current = null;
    };
  }, [asset]);

  // Wheel-to-zoom (non-passive so we can prevent the page from scrolling).
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const onWheel = (e: WheelEvent) => {
      const eng = engineRef.current;
      if (!eng) return;
      e.preventDefault();
      const rect = cv.getBoundingClientRect();
      eng.zoomAt(e.deltaY < 0 ? STEP : 1 / STEP, e.clientX - rect.left, e.clientY - rect.top);
      setZoom(eng.getZoom());
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    return () => cv.removeEventListener("wheel", onWheel);
  }, [asset]);

  const zoomCenter = (factor: number) => {
    const eng = engineRef.current;
    const cv = canvasRef.current;
    if (!eng || !cv) return;
    eng.zoomAt(factor, cv.clientWidth / 2, cv.clientHeight / 2);
    setZoom(eng.getZoom());
  };
  const resetZoom = () => {
    engineRef.current?.setZoom(MIN_ZOOM);
    setZoom(MIN_ZOOM);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { active: true, moved: false, x: e.clientX, y: e.clientY };
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current.active) return;
    const dx = e.clientX - drag.current.x;
    const dy = e.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true;
    engineRef.current?.panByCss(dx, dy);
    drag.current.x = e.clientX;
    drag.current.y = e.clientY;
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const wasDrag = drag.current.moved;
    drag.current.active = false;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
    if (wasDrag) return; // a pan, not a selection
    const hit = engineRef.current?.hitTest(e.clientX, e.clientY) ?? null;
    const cur = useRaceStore.getState().selectedDrv;
    setSelected(hit === cur ? null : hit);
  };

  const zoomedIn = zoom > MIN_ZOOM + 0.01;
  const following = zoomedIn && selectedDrv;

  return (
    <div className="trackmap" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        className={zoomedIn && !following ? "is-pannable" : ""}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => { drag.current.active = false; }}
      />
      <MapHeader />

      <div className="trackmap-zoom" role="group" aria-label="Zoom">
        <button onClick={() => zoomCenter(STEP)} disabled={zoom >= MAX_ZOOM - 0.01} aria-label="Zoom in">+</button>
        <span className="tz-level">{zoom.toFixed(1)}×</span>
        <button onClick={() => zoomCenter(1 / STEP)} disabled={!zoomedIn} aria-label="Zoom out">−</button>
        <button className="tz-reset" onClick={resetZoom} disabled={!zoomedIn} aria-label="Reset zoom" title="Fit whole track">⤢</button>
      </div>

      {zoomedIn && (
        <div className="trackmap-follow">
          {following ? `following ${selectedDrv}` : "select a car to follow · drag to pan"}
        </div>
      )}

      <button
        className="trackmap-info"
        onClick={() => useRaceStore.getState().setView3D(true)}
        title="Open the 3D Track Detail view"
      >
        Track info
      </button>
      <MapHud />
      {asset?.geo && (
        <div className="trackmap-attrib">map data © OpenStreetMap · tiles © CARTO</div>
      )}
      {!asset && !error && <div className="trackmap-note">deriving track outline…</div>}
      {error && <div className="trackmap-note">track outline unavailable ({error})</div>}
    </div>
  );
}

function MapHeader() {
  const name = useRaceStore((s) => s.session?.name ?? "");
  return <div className="trackmap-title">{name}</div>;
}

function MapHud() {
  const session = useRaceStore((s) => s.session);
  if (!session) return null;
  return (
    <div className="trackmap-hud">
      t {fmtClock(session.t_s)} · {session.speed}× {session.paused ? "· paused" : ""}
    </div>
  );
}
