// Canvas render engine for the live track map.
//  - Real-world map tiles underneath (CARTO light/dark rasters, OSM data)
//    when the track asset carries a georeference; clean card look otherwise.
//  - Spring-smoothed render clock (no stall/jump jitter from bursty WS input).
//  - F1-TV-style markers: big team-colored dots, white ring, label above.
//  - Phase 4: camera zoom + smooth follow-cam. The track ribbon scales with the
//    zoom (a real "move closer" feel); markers/labels grow gently but stay
//    legible. When zoomed in, the camera eases to keep the selected car centred
//    (north-up); with nothing selected the user free-pans by dragging.
// React-free; reads the zustand store imperatively each frame.
import { useRaceStore } from "../../store/raceStore";
import type { PositionsMsg } from "../../lib/ws/types";
import { PositionBuffers, RENDER_LAG_S } from "./buffer";

export interface GeoRef {
  lat0: number; lon0: number;
  asset_cx: number; asset_cy: number;
  geo_cx_m: number; geo_cy_m: number;
  scale_m_per_unit: number; rot_rad: number; flip: number;
  residual_m: number; attribution: string;
}

export interface TrackAsset {
  session_id: string;
  points: [number, number][];
  bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
  start_finish: { x: number; y: number; dx: number; dy: number };
  corners: { n: number; x: number; y: number }[];
  rotation_rad: number;
  geo?: GeoRef | null;
}

const PAD = 52;
const EARTH_C = 40075016.686;
const M_PER_DEG_LAT = 110540.0;
const M_PER_DEG_LON_EQ = 111320.0;
const TILE = 256;
const MAX_TILES = 150;
export const MAX_ZOOM = 5;
export const MIN_ZOOM = 1;
const CSS_VARS = [
  "--color-track-bed", "--color-track-edge", "--color-map-label",
  "--color-text-primary", "--color-text-secondary", "--color-accent",
  "--color-bg-surface", "--color-text-muted",
] as const;

interface View { scale: number; ox: number; oy: number; w: number; h: number; dpr: number; }
type Mat = [number, number, number, number, number, number]; // [a b c d e f]: x'=ax+cy+e, y'=bx+dy+f

const compose = (m: Mat, n: Mat): Mat => [
  m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
];
const invert = (m: Mat): Mat => {
  const det = m[0] * m[3] - m[1] * m[2];
  const [a, b, c, d] = [m[3] / det, -m[1] / det, -m[2] / det, m[0] / det];
  return [a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5])];
};
const apply = (m: Mat, x: number, y: number): [number, number] =>
  [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];

export class MapEngine {
  private buffers = new PositionBuffers();
  private estT = 0;
  private lastWall = 0;
  private raf = 0;
  private view: View = { scale: 1, ox: 0, oy: 0, w: 0, h: 0, dpr: 1 };
  private trackPath: Path2D | null = null;
  private sectorTicks: { x: number; y: number; nx: number; ny: number }[] = [];
  private sectorLabels: { x: number; y: number; label: string }[] = [];
  private lastScreen = new Map<string, { x: number; y: number }>(); // FIT-space coords
  private unsubs: (() => void)[] = [];
  private ro: ResizeObserver | null = null;
  private mo: MutationObserver | null = null;
  private css: Record<string, string> = {};
  private dark = false;
  private rc = 1;
  private rs = 0;
  private zoom = 15;            // tile pyramid level (geo maps only)
  private canvasFromMerc: Mat | null = null;
  private tiles = new Map<string, HTMLImageElement>();

  // ---- camera (Phase 4) ----  centre is in FIT-space CSS px
  private camZoom = 1;
  private camX = 0;
  private camY = 0;
  private camTX = 0;            // eased target
  private camTY = 0;
  private camReady = false;

  constructor(
    private canvas: HTMLCanvasElement,
    private wrap: HTMLElement,
    private asset: TrackAsset,
  ) {
    const th = -(asset.rotation_rad ?? 0);
    this.rc = Math.cos(th);
    this.rs = Math.sin(th);
  }

  start(): void {
    this.readCss();
    this.mo = new MutationObserver(() => { this.readCss(); });
    this.mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    this.ro = new ResizeObserver(() => this.fit());
    this.ro.observe(this.wrap);
    this.fit();

    this.unsubs.push(useRaceStore.subscribe(
      (s) => s.positions,
      (p: PositionsMsg | null) => {
        if (!p) return;
        const jumped = this.buffers.push(p.t, p.cars);
        if (jumped || this.estT === 0) this.estT = p.t - RENDER_LAG_S;
      },
    ));

    this.lastWall = performance.now();
    const loop = (now: number) => {
      this.tick(Math.min((now - this.lastWall) / 1000, 0.25));
      this.lastWall = now;
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    this.mo?.disconnect();
    this.unsubs.forEach((u) => u());
  }

  // ---------- public camera API ----------

  getZoom(): number { return this.camZoom; }

  /** Set absolute zoom; snapping to MIN recentres on the whole track. */
  setZoom(z: number): void {
    const nz = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
    if (Math.abs(nz - this.camZoom) < 1e-3) return;
    this.camZoom = nz;
    this.fitGeo();
    if (nz <= MIN_ZOOM + 1e-3) {
      this.camTX = this.view.w / 2;
      this.camTY = this.view.h / 2;
    } else {
      this.clampCam();
    }
  }

  /** Zoom by a factor while keeping the point under (cssX,cssY) fixed. */
  zoomAt(factor: number, cssX: number, cssY: number): void {
    const z0 = this.camZoom;
    const nz = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z0 * factor));
    if (Math.abs(nz - z0) < 1e-3) return;
    const { w, h } = this.view;
    const fx = (cssX - w / 2) / z0 + this.camX; // fit point under cursor
    const fy = (cssY - h / 2) / z0 + this.camY;
    this.camZoom = nz;
    this.fitGeo();
    if (nz <= MIN_ZOOM + 1e-3) {
      this.camX = this.camTX = w / 2;
      this.camY = this.camTY = h / 2;
      return;
    }
    this.camX = this.camTX = fx - (cssX - w / 2) / nz;
    this.camY = this.camTY = fy - (cssY - h / 2) / nz;
    this.clampCam();
  }

  /** Free-pan by a screen delta (ignored while auto-following). */
  panByCss(dxCss: number, dyCss: number): void {
    if (this.camZoom <= MIN_ZOOM + 1e-3) return;
    this.camX = this.camTX = this.camX - dxCss / this.camZoom;
    this.camY = this.camTY = this.camY - dyCss / this.camZoom;
    this.clampCam();
  }

  private clampCam(): void {
    const { w, h } = this.view;
    const m = 0.2; // allow a little overscroll past the edges
    const cx = (v: number) => Math.max(-w * m, Math.min(w * (1 + m), v));
    const cy = (v: number) => Math.max(-h * m, Math.min(h * (1 + m), v));
    this.camX = cx(this.camX); this.camTX = cx(this.camTX);
    this.camY = cy(this.camY); this.camTY = cy(this.camTY);
  }

  hitTest(clientX: number, clientY: number): string | null {
    const rect = this.canvas.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const z = this.camZoom;
    const fx = (px - this.view.w / 2) / z + this.camX; // -> fit-space
    const fy = (py - this.view.h / 2) / z + this.camY;
    let best: string | null = null;
    let bestD = 18; // screen-px tolerance
    for (const [drv, p] of this.lastScreen) {
      const d = Math.hypot(p.x - fx, p.y - fy) * z;
      if (d < bestD) { bestD = d; best = drv; }
    }
    return best;
  }

  private readCss(): void {
    const style = getComputedStyle(document.documentElement);
    for (const v of CSS_VARS) this.css[v] = style.getPropertyValue(v).trim();
    this.dark = document.documentElement.dataset.theme === "dark";
  }

  // ---------- geometry ----------

  private fit(): void {
    const r = this.wrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(r.width * dpr));
    this.canvas.height = Math.max(1, Math.round(r.height * dpr));
    this.canvas.style.width = `${r.width}px`;
    this.canvas.style.height = `${r.height}px`;
    const b = this.asset.bounds;
    const dx = b.max_x - b.min_x || 1;
    const dy = b.max_y - b.min_y || 1;
    const scale = Math.min((r.width - PAD * 2) / dx, (r.height - PAD * 2) / dy);
    this.view = {
      scale, dpr, w: r.width, h: r.height,
      ox: (r.width - dx * scale) / 2 - b.min_x * scale,
      oy: (r.height - dy * scale) / 2 + b.max_y * scale,
    };
    if (!this.camReady || this.camZoom <= MIN_ZOOM + 1e-3) {
      this.camX = this.camTX = r.width / 2;
      this.camY = this.camTY = r.height / 2;
      this.camReady = true;
    }
    this.trackPath = new Path2D();
    const pts = this.asset.points;
    this.trackPath.moveTo(this.sx(pts[0][0]), this.sy(pts[0][1]));
    for (let i = 1; i < pts.length; i++) this.trackPath.lineTo(this.sx(pts[i][0]), this.sy(pts[i][1]));
    this.trackPath.closePath();
    this.computeSectors();
    this.fitGeo();
  }

  /** Three stylized sectors split by equal arc length, anchored at the
   *  start/finish line (points[0]). These are evenly-spaced regions for
   *  orientation — not the official timed-sector boundaries (FastF1 does not
   *  expose those as track positions). Recomputed on resize. */
  private computeSectors(): void {
    this.sectorTicks = [];
    this.sectorLabels = [];
    const pts = this.asset.points;
    if (!pts || pts.length < 8) return;
    const scr = pts.map(([x, y]) => ({ x: this.sx(x), y: this.sy(y) }));
    const n = scr.length;
    const cum = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) {
      const a = scr[i];
      const b = scr[(i + 1) % n];
      cum[i + 1] = cum[i] + Math.hypot(b.x - a.x, b.y - a.y);
    }
    const total = cum[n];
    if (total <= 0) return;
    const cx = scr.reduce((s, p) => s + p.x, 0) / n;
    const cy = scr.reduce((s, p) => s + p.y, 0) / n;
    const idxAt = (target: number): number => {
      let i = 0;
      while (i < n && cum[i + 1] < target) i++;
      return Math.min(i, n - 1);
    };
    // two interior boundaries at 1/3 and 2/3 of the lap
    for (const f of [1 / 3, 2 / 3]) {
      const i = idxAt(f * total);
      const p = scr[i];
      const a = scr[(i - 2 + n) % n];
      const b = scr[(i + 2) % n];
      let tx = b.x - a.x;
      let ty = b.y - a.y;
      const tl = Math.hypot(tx, ty) || 1;
      tx /= tl; ty /= tl;
      this.sectorTicks.push({ x: p.x, y: p.y, nx: -ty, ny: tx });
    }
    // S1/S2/S3 labels at the midpoint of each third, nudged outward
    for (let k = 0; k < 3; k++) {
      const i = idxAt((k + 0.5) / 3 * total);
      const p = scr[i];
      const ox = p.x - cx;
      const oy = p.y - cy;
      const ol = Math.hypot(ox, oy) || 1;
      this.sectorLabels.push({ x: p.x + (ox / ol) * 20, y: p.y + (oy / ol) * 20, label: `S${k + 1}` });
    }
  }

  private fitGeo(): void {
    const g = this.asset.geo;
    this.canvasFromMerc = null;
    if (!g) return;
    // pick the tile level for the EFFECTIVE (camera-zoomed) scale so tiles stay
    // crisp when zoomed in; the camera transform supplies the rest of the zoom.
    const pxPerMeter = (this.view.scale * this.camZoom) / g.scale_m_per_unit;
    const ideal = Math.log2((pxPerMeter * EARTH_C * Math.cos((g.lat0 * Math.PI) / 180)) / TILE);
    this.zoom = Math.max(3, Math.min(19, Math.ceil(ideal)));
    // exact asset->mercator at 3 probe points -> affine
    const D = 10000;
    const [x0, y0] = this.assetToMerc(0, 0);
    const [x1, y1] = this.assetToMerc(D, 0);
    const [x2, y2] = this.assetToMerc(0, D);
    const mercFromAsset: Mat = [
      (x1 - x0) / D, (y1 - y0) / D,
      (x2 - x0) / D, (y2 - y0) / D,
      x0, y0,
    ];
    const canvasFromAsset: Mat = [this.view.scale, 0, 0, -this.view.scale, this.view.ox, this.view.oy];
    this.canvasFromMerc = compose(canvasFromAsset, invert(mercFromAsset));
  }

  private assetToMerc(x: number, y: number): [number, number] {
    const g = this.asset.geo!;
    const ax = x - g.asset_cx;
    const ay = (y - g.asset_cy) * g.flip;
    const c = Math.cos(g.rot_rad);
    const s = Math.sin(g.rot_rad);
    const qx = g.scale_m_per_unit * (c * ax - s * ay) + g.geo_cx_m;
    const qy = g.scale_m_per_unit * (s * ax + c * ay) + g.geo_cy_m;
    const lon = g.lon0 + qx / (M_PER_DEG_LON_EQ * Math.cos((g.lat0 * Math.PI) / 180));
    const lat = g.lat0 + qy / M_PER_DEG_LAT;
    const n = TILE * 2 ** this.zoom;
    const phi = (lat * Math.PI) / 180;
    return [
      ((lon + 180) / 360) * n,
      ((1 - Math.asinh(Math.tan(phi)) / Math.PI) / 2) * n,
    ];
  }

  private sx(x: number): number { return x * this.view.scale + this.view.ox; }
  private sy(y: number): number { return -y * this.view.scale + this.view.oy; }

  /** FIT-space CSS px -> on-screen CSS px under the current camera. */
  private proj(fx: number, fy: number): [number, number] {
    return [
      (fx - this.camX) * this.camZoom + this.view.w / 2,
      (fy - this.camY) * this.camZoom + this.view.h / 2,
    ];
  }

  /** Gentle marker/label growth so they read "closer" without ballooning. */
  private markerScale(): number {
    return Math.min(2, Math.sqrt(this.camZoom));
  }

  // ---------- clock ----------

  private tick(dt: number): void {
    const st = useRaceStore.getState();
    const speed = st.session?.speed ?? 1;
    const paused = st.session?.paused ?? true;
    const newest = this.buffers.newestT;
    if (!paused && newest > 0) {
      const target = newest - RENDER_LAG_S;
      this.estT += dt * speed;
      const err = target - this.estT;
      if (Math.abs(err) > 3) this.estT = target;          // hard resync (seek)
      else this.estT += err * Math.min(1, dt * 2.0);      // gentle spring
    }
    this.draw(st.selectedDrv, this.colorMap(st.rows));
  }

  private colorMap(rows: { drv: string; colour: string }[]): Map<string, string> {
    const m = new Map<string, string>();
    for (const r of rows) m.set(r.drv, `#${r.colour}`);
    return m;
  }

  /** Ease the camera toward its target: the selected car when zoomed in,
   *  the viewport centre at full-track zoom, or the user's pan otherwise. */
  private updateCamera(selected: string | null): void {
    const { w, h } = this.view;
    if (this.camZoom <= MIN_ZOOM + 1e-3) {
      this.camTX = w / 2;
      this.camTY = h / 2;
    } else if (selected) {
      const p = this.buffers.at(selected, this.estT);
      if (p) {
        const ax = this.rc * p.x - this.rs * p.y;
        const ay = this.rs * p.x + this.rc * p.y;
        this.camTX = this.sx(ax);
        this.camTY = this.sy(ay);
      }
      // else: selected car has no current sample (e.g. retired) — hold target
    }
    // free-pan (nothing selected): camTX/camTY were set by panByCss; keep them.
    const k = 0.18;
    this.camX += (this.camTX - this.camX) * k;
    this.camY += (this.camTY - this.camY) * k;
  }

  // ---------- drawing ----------

  private draw(selected: string | null, colors: Map<string, string>): void {
    const ctx = this.canvas.getContext("2d");
    if (!ctx || !this.trackPath) return;
    const { dpr, w, h } = this.view;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    this.updateCamera(selected);

    const onMap = this.drawTiles(ctx);

    // --- track ribbon: drawn under the camera transform so it scales with zoom
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.translate(w / 2, h / 2);
    ctx.scale(this.camZoom, this.camZoom);
    ctx.translate(-this.camX, -this.camY);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (onMap) {
      ctx.strokeStyle = "rgba(255,255,255,0.92)";
      ctx.lineWidth = 16;
      ctx.stroke(this.trackPath);
      ctx.strokeStyle = "#16171d";
      ctx.lineWidth = 10.5;
      ctx.stroke(this.trackPath);
    } else {
      ctx.strokeStyle = this.css["--color-track-edge"];
      ctx.lineWidth = 17;
      ctx.stroke(this.trackPath);
      ctx.strokeStyle = this.css["--color-track-bed"];
      ctx.lineWidth = 12;
      ctx.stroke(this.trackPath);
    }
    ctx.restore();

    // --- glyphs: drawn in screen space (constant-ish size) over scaled geometry
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.drawSectors(ctx, onMap);
    this.drawStartFinish(ctx);
    this.drawCorners(ctx, onMap);
    this.drawCars(ctx, selected, colors, onMap);
  }

  /** Fetch-or-cache a single CARTO raster tile (requests it lazily). */
  private getTile(style: string, z: number, x: number, y: number): HTMLImageElement {
    const key = `${style}/${z}/${x}/${y}`;
    let img = this.tiles.get(key);
    if (!img) {
      img = new Image();
      img.crossOrigin = "anonymous";
      const sub = "abcd"[(x + y) % 4];
      img.src = `https://${sub}.basemaps.cartocdn.com/${style}/${z}/${x}/${y}.png`;
      this.tiles.set(key, img);
    }
    return img;
  }

  private static loaded(img: HTMLImageElement | undefined): img is HTMLImageElement {
    return !!img && img.complete && img.naturalWidth > 0;
  }

  /** Returns true when a tile underlay was drawn.
   *  Slippy-map rendering with **parent-tile fallback**: the target-level tile is
   *  always requested, but if it hasn't loaded yet we draw the matching slice of
   *  an already-cached coarser ancestor so the surroundings never go blank while
   *  the camera pans with a moving car. A one-tile prefetch margin smooths panning. */
  private drawTiles(ctx: CanvasRenderingContext2D): boolean {
    if (!this.canvasFromMerc || !this.asset.geo) return false;
    const inv = invert(this.canvasFromMerc); // fit-CSS -> merc
    const { w, h, dpr } = this.view;
    const z = this.camZoom;
    // visible region in FIT-space CSS px under the camera
    const vx0 = this.camX - (w / 2) / z, vx1 = this.camX + (w / 2) / z;
    const vy0 = this.camY - (h / 2) / z, vy1 = this.camY + (h / 2) / z;
    const merc = [[vx0, vy0], [vx1, vy0], [vx0, vy1], [vx1, vy1]]
      .map(([x, y]) => apply(inv, x, y));
    const xs = merc.map((c) => c[0]);
    const ys = merc.map((c) => c[1]);
    let tx0 = Math.floor(Math.min(...xs) / TILE);
    let tx1 = Math.floor(Math.max(...xs) / TILE);
    let ty0 = Math.floor(Math.min(...ys) / TILE);
    let ty1 = Math.floor(Math.max(...ys) / TILE);
    if ((tx1 - tx0 + 1) * (ty1 - ty0 + 1) > MAX_TILES) return false;
    tx0--; tx1++; ty0--; ty1++; // prefetch one ring so panning has tiles ready

    const style = this.dark ? "dark_all" : "light_all";
    const L = this.zoom;
    const max = 2 ** L;
    // device = dpr * camera * canvasFromMerc
    const camMat: Mat = [z, 0, 0, z, w / 2 - z * this.camX, h / 2 - z * this.camY];
    const full = compose(camMat, this.canvasFromMerc);
    ctx.save();
    ctx.setTransform(dpr * full[0], dpr * full[1], dpr * full[2], dpr * full[3], dpr * full[4], dpr * full[5]);
    ctx.imageSmoothingEnabled = true;
    let drewAny = false;
    for (let tx = tx0; tx <= tx1; tx++) {
      for (let ty = Math.max(0, ty0); ty <= Math.min(max - 1, ty1); ty++) {
        const wx = ((tx % max) + max) % max;
        const dx = tx * TILE - 0.25, dy = ty * TILE - 0.25, ds = TILE + 0.5;
        const img = this.getTile(style, L, wx, ty); // always request the sharp tile
        if (MapEngine.loaded(img)) {
          ctx.drawImage(img, dx, dy, ds, ds);
          drewAny = true;
          continue;
        }
        // not ready -> draw the matching slice of the nearest cached ancestor
        for (let k = 1; k <= 6 && L - k >= 1; k++) {
          const f = 2 ** k;
          const pmax = 2 ** (L - k);
          const pwx = ((Math.floor(wx / f) % pmax) + pmax) % pmax;
          const pty = Math.floor(ty / f);
          const pimg = this.tiles.get(`${style}/${L - k}/${pwx}/${pty}`);
          if (MapEngine.loaded(pimg)) {
            const sub = TILE / f;
            const sxp = (((wx % f) + f) % f) * sub;
            const syp = (((ty % f) + f) % f) * sub;
            ctx.drawImage(pimg!, sxp, syp, sub, sub, dx, dy, ds, ds);
            drewAny = true;
            break;
          }
        }
      }
    }
    ctx.restore();
    if (drewAny) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = this.dark ? "rgba(8,10,16,0.30)" : "rgba(255,255,255,0.22)";
      ctx.fillRect(0, 0, w, h);
    }
    return drewAny;
  }

  private drawCars(ctx: CanvasRenderingContext2D, selected: string | null,
                   colors: Map<string, string>, onMap: boolean): void {
    this.lastScreen.clear();
    const ms = this.markerScale();
    ctx.textAlign = "center";
    for (const drv of this.buffers.drivers()) {
      const p = this.buffers.at(drv, this.estT);
      if (!p) continue;
      const ax = this.rc * p.x - this.rs * p.y;
      const ay = this.rs * p.x + this.rc * p.y;
      const fx = this.sx(ax);
      const fy = this.sy(ay);
      this.lastScreen.set(drv, { x: fx, y: fy });
      const [x, y] = this.proj(fx, fy);
      const color = colors.get(drv) ?? "#808080";
      const isSel = drv === selected;
      const r = (isSel ? 10 : 8.5) * ms;

      if (isSel) {
        ctx.beginPath();
        ctx.arc(x, y, r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = this.css["--color-accent"];
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = onMap ? "rgba(255,255,255,0.95)" : this.css["--color-bg-surface"];
      ctx.lineWidth = 2.2;
      ctx.stroke();

      ctx.font = `700 ${(10 * ms).toFixed(1)}px ui-monospace, monospace`;
      const ly = y - r - 6;
      if (onMap || this.dark) {
        ctx.lineWidth = 3.5;
        ctx.strokeStyle = "rgba(10,12,18,0.85)";
        ctx.strokeText(drv, x, ly);
        ctx.fillStyle = isSel ? this.css["--color-accent"] : "rgba(255,255,255,0.96)";
      } else {
        ctx.lineWidth = 3.5;
        ctx.strokeStyle = this.css["--color-bg-surface"];
        ctx.strokeText(drv, x, ly);
        ctx.fillStyle = isSel ? this.css["--color-accent"] : this.css["--color-text-secondary"];
      }
      ctx.fillText(drv, x, ly);
    }
    ctx.textAlign = "start";
  }

  private drawStartFinish(ctx: CanvasRenderingContext2D): void {
    const sf = this.asset.start_finish;
    const [x, y] = this.proj(this.sx(sf.x), this.sy(sf.y));
    const tx = sf.dx;
    const ty = -sf.dy;
    const S = 3.4 * this.markerScale();
    for (let i = -3; i < 3; i++) {
      for (let j = 0; j < 2; j++) {
        ctx.fillStyle = (i + j) % 2 === 0 ? "#101117" : "#f5f5f8";
        const cx = x + -ty * (i + 0.5) * S + tx * (j - 0.5) * S;
        const cy = y + tx * (i + 0.5) * S + ty * (j - 0.5) * S;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(Math.atan2(ty, tx));
        ctx.fillRect(-S / 2, -S / 2, S, S);
        ctx.restore();
      }
    }
  }

  /** Sector dividers (perpendicular ticks across the track) + S1/S2/S3 labels.
   *  Stylized even-thirds regions — see computeSectors(). Drawn in screen space. */
  private drawSectors(ctx: CanvasRenderingContext2D, onMap: boolean): void {
    if (!this.sectorTicks.length) return;
    const accent = this.css["--color-accent"] || "#0fae9e";
    const ms = this.markerScale();
    const TICKLEN = 13 * ms;

    ctx.save();
    ctx.lineCap = "round";
    for (const t of this.sectorTicks) {
      const [x, y] = this.proj(t.x, t.y);
      ctx.strokeStyle = onMap ? "rgba(10,12,18,0.55)" : "rgba(255,255,255,0.9)";
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(x - t.nx * TICKLEN, y - t.ny * TICKLEN);
      ctx.lineTo(x + t.nx * TICKLEN, y + t.ny * TICKLEN);
      ctx.stroke();
      ctx.strokeStyle = accent;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(x - t.nx * TICKLEN, y - t.ny * TICKLEN);
      ctx.lineTo(x + t.nx * TICKLEN, y + t.ny * TICKLEN);
      ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `700 ${(10 * ms).toFixed(1)}px ui-monospace, monospace`;
    const h = 15 * ms;
    for (const l of this.sectorLabels) {
      const [x, y] = this.proj(l.x, l.y);
      const w = ctx.measureText(l.label).width + 10 * ms;
      this.roundRect(ctx, x - w / 2, y - h / 2, w, h, 7 * ms);
      ctx.fillStyle = accent;
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.fillText(l.label, x, y + 0.5);
    }
    ctx.restore();
    ctx.textBaseline = "alphabetic";
  }

  private drawCorners(ctx: CanvasRenderingContext2D, onMap: boolean): void {
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const ms = this.markerScale();
    ctx.font = `700 ${(9 * ms).toFixed(1)}px ui-monospace, monospace`;
    const accent = this.css["--color-accent"] || "#0fae9e";
    const surface = this.css["--color-bg-surface"] || "#ffffff";
    for (const c of this.asset.corners) {
      const [ax, ay] = this.proj(this.sx(c.x), this.sy(c.y));
      // apex dot on the racing line
      ctx.beginPath();
      ctx.arc(ax, ay, 2.6 * ms, 0, Math.PI * 2);
      ctx.fillStyle = accent;
      ctx.fill();

      // numbered badge, nudged off the apex
      const bx = ax + 11 * ms;
      const by = ay - 11 * ms;
      ctx.beginPath();
      ctx.arc(bx, by, 8 * ms, 0, Math.PI * 2);
      ctx.fillStyle = onMap ? "rgba(16,17,23,0.82)" : surface;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = accent;
      ctx.stroke();

      ctx.fillStyle = onMap ? "rgba(255,255,255,0.96)" : this.css["--color-text-secondary"];
      ctx.fillText(String(c.n), bx, by + 0.5);
    }
    ctx.restore();
    ctx.textBaseline = "alphabetic";
  }

  private roundRect(ctx: CanvasRenderingContext2D, x: number, y: number,
                    w: number, h: number, r: number): void {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }
}
