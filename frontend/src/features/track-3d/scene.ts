// Three.js 3D track scene for the Track Detail overlay (Phase 4).
//  - Elevation-aware track ribbon built from the asset outline + per-point height.
//  - Procedural F1 cars (open-wheel body, wings, halo, 4 rolling wheels).
//  - Georeferenced ground that paints the SAME CARTO map data used by the 2D map,
//    then scatters instanced low-poly trees and translucent water planes derived
//    from those tiles so the 3D surroundings replicate the 2D view.
//  - Camera: OrbitControls by default; optional chase that rides behind a car.
// React-free; the overlay component drives render() each frame.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

export interface GeoRef3D {
  lat0: number; lon0: number;
  asset_cx: number; asset_cy: number;
  geo_cx_m: number; geo_cy_m: number;
  scale_m_per_unit: number; rot_rad: number; flip: number;
  residual_m: number; attribution: string;
}

export interface Asset3D {
  points: [number, number][];
  elevation?: number[];
  bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
  start_finish: { x: number; y: number; dx: number; dy: number };
  corners: { n: number; x: number; y: number }[];
  rotation_rad: number;
  geo?: GeoRef3D | null;
}

export interface CarState3D { drv: string; x: number; y: number; color: string; }

const SPAN = 220;
const VEXAG = 1.8;
const ROAD_W = 3.0;
const WHEEL_R = 0.34;
const TILE = 256;
const EARTH_C = 40075016.686;
const M_PER_DEG_LAT = 110540.0;
const M_PER_DEG_LON_EQ = 111320.0;
const GROUND_G = SPAN * 0.95;
const GROUND_CS = 3072;          // higher-res ground texture (less pixelated)
const GRID = 110;
const CAR_SCALE = 0.62;          // shrink cars relative to the track
const MODEL_TARGET_LEN = 3.2;    // fit an imported .glb to ~this length
const CORRIDOR = ROAD_W * 2.4;   // terrain carve radius around the track centerline
const WGRID = 200;               // water-mask resolution (smooth shorelines)
const WMASK_CS = 1024;           // water alpha-map canvas size
const TUNNEL_MIN_DY = 1.5;       // vertical gap (world units) that counts as over/under
const TUNNEL_SPAN = ROAD_W * 4.5; // length of road covered by each tunnel

interface CarObj {
  group: THREE.Group;
  body: THREE.Mesh;
  wheels: THREE.Group[];
  label: THREE.Sprite;
  heading: number;
  lastX: number;
  lastZ: number;
}

export class Scene3D {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private hemi: THREE.HemisphereLight;
  private dir: THREE.DirectionalLight;
  private ground: THREE.Mesh;
  private groundTex: THREE.CanvasTexture | null = null;
  private groundCanvas: HTMLCanvasElement | null = null;
  private groundTiles = new Map<string, HTMLImageElement>();
  private groundZoom = 14;
  private groundStart = 0;
  private groundBuilt = false;
  private trackMesh!: THREE.Mesh;
  private cars = new Map<string, CarObj>();
  private centerline: THREE.Vector3[] = [];
  private cx: number; private cy: number; private k: number; private ymin: number;
  private rc: number; private rs: number;
  private mode: "orbit" | "chase" | "flyover" = "orbit";
  private carTemplate: THREE.Object3D | null = null;
  private dark: boolean;
  // water (built once tiles are decoded)
  private groundGeo: THREE.BufferGeometry | null = null;
  private waterField: Float32Array | null = null; // WGRID×WGRID blurred 0..1 water amount
  private waterFloor = 0;
  private waterPlane: THREE.Mesh | null = null;
  // free-fly drone camera (flyover mode)
  private lastFrame = performance.now();
  private fly = {
    active: false, locked: false, yaw: 0, pitch: -0.12,
    speed: SPAN * 0.16, keys: new Set<string>(),
  };
  private flyKeyDown = (e: KeyboardEvent) => this.onFlyKey(e, true);
  private flyKeyUp = (e: KeyboardEvent) => this.onFlyKey(e, false);
  private flyMouse = (e: MouseEvent) => this.onFlyMouse(e);
  private flyClick = () => { if (this.fly.active && !this.fly.locked) this.renderer.domElement.requestPointerLock?.(); };
  private flyLockChange = () => { this.fly.locked = document.pointerLockElement === this.renderer.domElement; };

  constructor(private container: HTMLElement, private asset: Asset3D, dark: boolean) {
    this.dark = dark;
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    container.appendChild(this.renderer.domElement);
    this.scene.fog = new THREE.Fog(0x0c0e14, SPAN * 1.4, SPAN * 3.2);
    this.camera = new THREE.PerspectiveCamera(52, w / h, 0.5, 6000);
    this.camera.position.set(SPAN * 0.55, SPAN * 0.55, SPAN * 0.7);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.minDistance = 12;
    this.controls.maxDistance = SPAN * 2.4;
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x404040, 1.0);
    this.scene.add(this.hemi);
    this.dir = new THREE.DirectionalLight(0xffffff, 1.4);
    this.dir.position.set(SPAN * 0.6, SPAN, SPAN * 0.3);
    this.scene.add(this.dir);
    const b = asset.bounds;
    this.cx = (b.min_x + b.max_x) / 2;
    this.cy = (b.min_y + b.max_y) / 2;
    const dx = b.max_x - b.min_x || 1;
    const dy = b.max_y - b.min_y || 1;
    this.k = SPAN / Math.max(dx, dy);
    const elev = asset.elevation ?? [];
    this.ymin = elev.length ? Math.min(...elev) : 0;
    const th = -(asset.rotation_rad ?? 0);
    this.rc = Math.cos(th);
    this.rs = Math.sin(th);
    this.buildCenterline();
    this.ground = this.buildGround();
    this.scene.add(this.ground);
    this.buildTrack();
    this.buildTunnels();
    this.buildStartFinish();
    this.buildCorners();
    this.applyTheme();
    this.loadCarModel();
  }

  /** Optional: load a web-optimized F1 model from /models/f1.glb if the user
   *  dropped one in. Falls back silently to the procedural car when absent. */
  private loadCarModel(): void {
    new GLTFLoader().load(
      "/models/f1.glb",
      (gltf) => {
        const root = gltf.scene;
        const box = new THREE.Box3().setFromObject(root);
        const size = new THREE.Vector3(); box.getSize(size);
        const len = Math.max(size.x, size.z) || 1;
        root.scale.setScalar(MODEL_TARGET_LEN / len);
        const box2 = new THREE.Box3().setFromObject(root);
        root.position.y -= box2.min.y; // sit wheels on the ground
        this.carTemplate = root;
        for (const obj of this.cars.values()) this.scene.remove(obj.group);
        this.cars.clear(); // rebuilt as model clones on the next frame
      },
      undefined,
      () => { /* no /models/f1.glb — keep the procedural car */ },
    );
  }

  private worldXZ(ax: number, ay: number): [number, number] {
    return [(ax - this.cx) * this.k, (ay - this.cy) * this.k];
  }
  private worldToAsset(X: number, Z: number): [number, number] {
    return [this.cx + X / this.k, this.cy + Z / this.k];
  }
  private elevAt(wx: number, wz: number): number {
    let best = 0, bestD = Infinity;
    for (const p of this.centerline) {
      const d = (p.x - wx) ** 2 + (p.z - wz) ** 2;
      if (d < bestD) { bestD = d; best = p.y; }
    }
    return best;
  }
  private distToTrack(wx: number, wz: number): number {
    let bestD = Infinity;
    for (const p of this.centerline) {
      const d = (p.x - wx) ** 2 + (p.z - wz) ** 2;
      if (d < bestD) bestD = d;
    }
    return Math.sqrt(bestD);
  }

  /** Terrain height at a world point: hugs the track elevation nearby (so the
   *  track never "flies"), smoothly blending to an inverse-distance average of
   *  the whole lap farther out. A carve term keeps the ground a touch BELOW the
   *  asphalt (no land poking through the ribbon) and, at over/under crossings,
   *  follows the LOWER deck so the road underneath stays exposed. Finally, any
   *  point flagged as water is dropped into a flat basin. */
  private heightField(X: number, Z: number): number {
    const cl = this.centerline;
    if (!cl.length) return 0;
    const corr2 = CORRIDOR * CORRIDOR;
    let wsum = 0, hsum = 0, nearest = 0, nd = Infinity, minNear = Infinity;
    for (let i = 0; i < cl.length; i += 2) {
      const p = cl[i];
      const d2 = (p.x - X) ** 2 + (p.z - Z) ** 2;
      if (d2 < nd) { nd = d2; nearest = p.y; }
      if (d2 < corr2 && p.y < minNear) minNear = p.y;
      const w = 1 / (d2 + 25);
      wsum += w; hsum += w * p.y;
    }
    const idw = hsum / (wsum || 1);
    const t = Math.min(1, nd / (SPAN * 0.16) ** 2); // 0 near track -> hug; 1 far -> average
    let h = nearest * (1 - t) + idw * t;
    if (nd < corr2) {
      const dd = Math.sqrt(nd);
      const kk = 1 - dd / CORRIDOR;               // 1 at centerline -> 0 at corridor edge
      const blend = kk * kk * (3 - 2 * kk);       // smoothstep
      const base = minNear === Infinity ? nearest : minNear;
      const target = base - 0.55 * kk;            // sit just under the asphalt / lower deck
      h = h * (1 - blend) + target * blend;
    }
    if (this.waterField) {
      const wv = this.waterSample(X, Z);
      if (wv > 0) h = h * (1 - wv) + Math.min(h, this.waterFloor) * wv;
    }
    return h;
  }

  /** Bilinear-ish lookup into the blurred water field (0 = land, 1 = open water). */
  private waterSample(X: number, Z: number): number {
    const f = this.waterField;
    if (!f) return 0;
    const G = GROUND_G;
    const gi = Math.round(((X + G) / (2 * G)) * (WGRID - 1));
    const gj = Math.round(((Z + G) / (2 * G)) * (WGRID - 1));
    if (gi < 0 || gj < 0 || gi >= WGRID || gj >= WGRID) return 0;
    return f[gj * WGRID + gi];
  }

  private buildCenterline(): void {
    const pts = this.asset.points;
    const elev = this.asset.elevation ?? [];
    const c: THREE.Vector3[] = [];
    for (let i = 0; i < pts.length; i++) {
      const [wx, wz] = this.worldXZ(pts[i][0], pts[i][1]);
      const wy = ((elev[i] ?? 0) - this.ymin) * this.k * VEXAG;
      c.push(new THREE.Vector3(wx, wy, wz));
    }
    this.centerline = c;
  }

  private assetToMerc(x: number, y: number): [number, number] {
    const g = this.asset.geo!;
    const ax = x - g.asset_cx;
    const ay = (y - g.asset_cy) * g.flip;
    const c = Math.cos(g.rot_rad), s = Math.sin(g.rot_rad);
    const qx = g.scale_m_per_unit * (c * ax - s * ay) + g.geo_cx_m;
    const qy = g.scale_m_per_unit * (s * ax + c * ay) + g.geo_cy_m;
    const lon = g.lon0 + qx / (M_PER_DEG_LON_EQ * Math.cos((g.lat0 * Math.PI) / 180));
    const lat = g.lat0 + qy / M_PER_DEG_LAT;
    const n = TILE * 2 ** this.groundZoom;
    const phi = (lat * Math.PI) / 180;
    return [((lon + 180) / 360) * n, ((1 - Math.asinh(Math.tan(phi)) / Math.PI) / 2) * n];
  }

  private buildGround(): THREE.Mesh {
    const G = GROUND_G;
    const N = 96; // terrain grid resolution
    const geo = new THREE.BufferGeometry();
    const pos: number[] = [];
    const uv: number[] = [];
    const idx: number[] = [];
    for (let j = 0; j <= N; j++) {
      for (let i = 0; i <= N; i++) {
        const X = -G + (i / N) * 2 * G;
        const Z = -G + (j / N) * 2 * G;
        pos.push(X, this.heightField(X, Z), Z); // ground follows the track relief
        uv.push(i / N, j / N);
      }
    }
    for (let j = 0; j < N; j++) {
      for (let i = 0; i < N; i++) {
        const a = j * (N + 1) + i, b = a + 1, c = a + (N + 1), d = c + 1;
        idx.push(a, c, b, b, c, d);
      }
    }
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    this.groundGeo = geo;
    const mat = new THREE.MeshStandardMaterial({
      color: 0x0c0e14, roughness: 1, metalness: 0, side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.y = 0;
    if (this.asset.geo) {
      this.groundCanvas = document.createElement("canvas");
      this.groundCanvas.width = GROUND_CS;
      this.groundCanvas.height = GROUND_CS;
      this.groundTex = new THREE.CanvasTexture(this.groundCanvas);
      this.groundTex.flipY = false;
      this.groundTex.colorSpace = THREE.SRGBColorSpace;
      this.groundTex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      this.groundTex.minFilter = THREE.LinearMipmapLinearFilter;
      this.groundTex.generateMipmaps = true;
      mat.map = this.groundTex;
      mat.color.set(0xffffff);
      this.pickGroundZoom();
      this.requestGroundTiles();
      this.groundStart = performance.now();
    }
    return mesh;
  }

  private pickGroundZoom(): void {
    const g = this.asset.geo!;
    const worldPerMeter = this.k / g.scale_m_per_unit;
    const pxPerMeter = (GROUND_CS / (2 * GROUND_G)) * worldPerMeter;
    const ideal = Math.log2((pxPerMeter * EARTH_C * Math.cos((g.lat0 * Math.PI) / 180)) / TILE);
    this.groundZoom = Math.max(3, Math.min(18, Math.round(ideal)));
  }

  private requestGroundTiles(): void {
    const range = this.groundTileRange();
    if (!range) return;
    const style = "rastertiles/voyager";
    const max = 2 ** this.groundZoom;
    for (let tx = range.tx0; tx <= range.tx1; tx++) {
      for (let ty = Math.max(0, range.ty0); ty <= Math.min(max - 1, range.ty1); ty++) {
        const wx = ((tx % max) + max) % max;
        const key = `${this.groundZoom}/${wx}/${ty}`;
        if (this.groundTiles.has(key)) continue;
        const img = new Image();
        img.crossOrigin = "anonymous";
        const sub = "abcd"[(wx + ty) % 4];
        img.src = `https://${sub}.basemaps.cartocdn.com/${style}/${this.groundZoom}/${wx}/${ty}.png`;
        this.groundTiles.set(key, img);
      }
    }
  }

  private groundTileRange() {
    const G = GROUND_G;
    const mercs = [[-G, -G], [G, -G], [-G, G], [G, G]].map(([X, Z]) => {
      const [ax, ay] = this.worldToAsset(X, Z);
      return this.assetToMerc(ax, ay);
    });
    const xs = mercs.map((m) => m[0]), ys = mercs.map((m) => m[1]);
    return {
      tx0: Math.floor(Math.min(...xs) / TILE), tx1: Math.floor(Math.max(...xs) / TILE),
      ty0: Math.floor(Math.min(...ys) / TILE), ty1: Math.floor(Math.max(...ys) / TILE),
    };
  }

  private mercToPixel(): { a: number; b: number; c: number; d: number; e: number; f: number } | null {
    const G = GROUND_G, CS = GROUND_CS;
    const m = (X: number, Z: number) => {
      const [ax, ay] = this.worldToAsset(X, Z);
      return this.assetToMerc(ax, ay);
    };
    const mA = m(-G, -G);
    const mB = m(G, -G);
    const mC = m(-G, G);
    const exx = (mB[0] - mA[0]) / CS, exy = (mB[1] - mA[1]) / CS;
    const eyx = (mC[0] - mA[0]) / CS, eyy = (mC[1] - mA[1]) / CS;
    const det = exx * eyy - exy * eyx;
    if (Math.abs(det) < 1e-12) return null;
    const ia = eyy / det, ic = -eyx / det, ib = -exy / det, id = exx / det;
    return {
      a: ia, b: ib, c: ic, d: id,
      e: -(ia * mA[0] + ic * mA[1]),
      f: -(ib * mA[0] + id * mA[1]),
    };
  }

  private drawGroundCanvas(): boolean {
    if (!this.groundCanvas) return false;
    const ctx = this.groundCanvas.getContext("2d");
    const tf = this.mercToPixel();
    if (!ctx || !tf) return false;
    ctx.fillStyle = this.dark ? "#10141c" : "#e7ebef";
    ctx.fillRect(0, 0, GROUND_CS, GROUND_CS);
    const range = this.groundTileRange();
    if (!range) return false;
    const max = 2 ** this.groundZoom;
    ctx.save();
    ctx.setTransform(tf.a, tf.b, tf.c, tf.d, tf.e, tf.f);
    let drew = false;
    for (let tx = range.tx0; tx <= range.tx1; tx++) {
      for (let ty = Math.max(0, range.ty0); ty <= Math.min(max - 1, range.ty1); ty++) {
        const wx = ((tx % max) + max) % max;
        const img = this.groundTiles.get(`${this.groundZoom}/${wx}/${ty}`);
        if (img && img.complete && img.naturalWidth > 0) {
          ctx.drawImage(img, tx * TILE - 0.5, ty * TILE - 0.5, TILE + 1, TILE + 1);
          drew = true;
        }
      }
    }
    ctx.restore();
    return drew;
  }

  private tickGround(): void {
    if (this.groundBuilt || !this.groundCanvas) return;
    let loaded = 0;
    for (const img of this.groundTiles.values()) if (img.complete && img.naturalWidth > 0) loaded++;
    const total = this.groundTiles.size;
    const elapsed = performance.now() - this.groundStart;
    const ready = total > 0 && (loaded >= total || (elapsed > 4000 && loaded > 0));
    if (loaded > 0) {
      if (this.drawGroundCanvas() && this.groundTex) this.groundTex.needsUpdate = true;
    }
    if (ready) {
      this.groundBuilt = true;
      this.buildEnvironment();
    }
  }

  private buildEnvironment(): void {
    if (!this.groundCanvas) return;
    const ctx = this.groundCanvas.getContext("2d");
    if (!ctx) return;
    let data: ImageData;
    try { data = ctx.getImageData(0, 0, GROUND_CS, GROUND_CS); }
    catch { return; }
    const px = data.data;
    const G = GROUND_G;
    const cell = (2 * G) / GRID;
    const treeM: THREE.Matrix4[] = [];
    const bldgM: THREE.Matrix4[] = [];
    const tmp = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const sca = new THREE.Vector3();
    const pos = new THREE.Vector3();
    const yAxis = new THREE.Vector3(0, 1, 0);
    const sample = (u: number, v: number) => {
      const i = (Math.min(GROUND_CS - 1, v) * GROUND_CS + Math.min(GROUND_CS - 1, u)) * 4;
      return [px[i], px[i + 1], px[i + 2]];
    };

    // ---- smooth water: classify on a fine grid, dilate (connect thin rivers),
    //      box-blur (soft shorelines), then drop the basin + lay one flat sheet.
    this.buildWater(sample);

    for (let gj = 0; gj < GRID; gj++) {
      for (let gi = 0; gi < GRID; gi++) {
        const X = -G + (gi + 0.5) * cell;
        const Z = -G + (gj + 0.5) * cell;
        const u = Math.floor(((X + G) / (2 * G)) * GROUND_CS);
        const v = Math.floor(((Z + G) / (2 * G)) * GROUND_CS);
        const [r, gC, bC] = sample(u, v);
        const bright = (r + gC + bC) / 3;
        const isVeg = gC > 110 && gC >= r + 6 && gC >= bC + 6;
        // buildings: greyish/beige mid-tone in the CARTO Voyager palette (heuristic)
        const isBldg = !isVeg && bright > 150 && bright < 232
          && Math.abs(r - gC) < 16 && r - bC > -6 && r - bC < 34;
        if (this.waterSample(X, Z) > 0.3) continue;        // no props on water
        if (this.distToTrack(X, Z) < ROAD_W * 1.8) continue; // keep the track clear
        const Y = this.heightField(X, Z); // sit on the terrain
        if (isBldg && bldgM.length < 2500) {
          const fp = cell * (0.4 + Math.random() * 0.3);
          const ht = 2 + Math.random() * 7;
          pos.set(X + (Math.random() - 0.5) * cell * 0.3, Y, Z + (Math.random() - 0.5) * cell * 0.3);
          q.setFromAxisAngle(yAxis, Math.random() * Math.PI * 0.5);
          sca.set(fp, ht, fp);
          tmp.compose(pos, q, sca);
          bldgM.push(tmp.clone());
          q.identity();
        } else if (isVeg && treeM.length < 5000) {
          const jx = (Math.random() - 0.5) * cell * 0.6;
          const jz = (Math.random() - 0.5) * cell * 0.6;
          pos.set(X + jx, Y, Z + jz);
          q.setFromAxisAngle(yAxis, Math.random() * Math.PI * 2);
          const sc = 0.7 + Math.random() * 0.9;
          sca.set(sc, sc, sc);
          tmp.compose(pos, q, sca);
          treeM.push(tmp.clone());
          q.identity();
        }
      }
    }
    if (bldgM.length) {
      const bgeo = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
      const bmat = new THREE.MeshStandardMaterial({ roughness: 0.8, metalness: 0.05 });
      const bim = new THREE.InstancedMesh(bgeo, bmat, bldgM.length);
      const bc = new THREE.Color();
      bldgM.forEach((mx, i) => {
        bim.setMatrixAt(i, mx);
        const g = 0.6 + Math.random() * 0.2;
        bc.setRGB(g, g * 0.98, g * 0.94);
        bim.setColorAt(i, bc);
      });
      bim.instanceMatrix.needsUpdate = true;
      if (bim.instanceColor) bim.instanceColor.needsUpdate = true;
      this.scene.add(bim);
    }
    if (treeM.length) {
      const trunkGeo = new THREE.CylinderGeometry(0.1, 0.16, 1.1, 6).translate(0, 0.55, 0);
      const trunkMat = new THREE.MeshStandardMaterial({ color: 0x5b4632, roughness: 0.9 });
      // rounded (icosphere) foliage with per-tree colour variation = natural, not blocky
      const folGeo = new THREE.IcosahedronGeometry(0.95, 1).translate(0, 1.7, 0);
      const folMat = new THREE.MeshStandardMaterial({ roughness: 0.85 });
      const trunkIM = new THREE.InstancedMesh(trunkGeo, trunkMat, treeM.length);
      const folIM = new THREE.InstancedMesh(folGeo, folMat, treeM.length);
      const tint = new THREE.Color();
      treeM.forEach((mx, i) => {
        trunkIM.setMatrixAt(i, mx); folIM.setMatrixAt(i, mx);
        tint.setHSL(0.27 + Math.random() * 0.07, 0.45 + Math.random() * 0.2, 0.3 + Math.random() * 0.13);
        folIM.setColorAt(i, tint);
      });
      trunkIM.instanceMatrix.needsUpdate = true;
      folIM.instanceMatrix.needsUpdate = true;
      if (folIM.instanceColor) folIM.instanceColor.needsUpdate = true;
      this.scene.add(trunkIM); this.scene.add(folIM);
    }
  }

  /** Classify water on a fine grid, dilate (bridge thin rivers), box-blur for
   *  soft shorelines, carve the basin, then lay one flat alpha-masked sheet. */
  private buildWater(sample: (u: number, v: number) => number[]): void {
    const G = GROUND_G;
    const raw = new Uint8Array(WGRID * WGRID);
    for (let gj = 0; gj < WGRID; gj++) {
      for (let gi = 0; gi < WGRID; gi++) {
        const X = -G + ((gi + 0.5) / WGRID) * 2 * G;
        const Z = -G + ((gj + 0.5) / WGRID) * 2 * G;
        const u = Math.floor(((X + G) / (2 * G)) * GROUND_CS);
        const v = Math.floor(((Z + G) / (2 * G)) * GROUND_CS);
        const [r, gC, bC] = sample(u, v);
        if (bC > 105 && bC >= r + 8 && bC >= gC - 4) raw[gj * WGRID + gi] = 1;
      }
    }
    // dilate 3×3 so thin rivers become continuous ribbons (not isolated dots)
    const dil = new Uint8Array(WGRID * WGRID);
    for (let gj = 0; gj < WGRID; gj++) {
      for (let gi = 0; gi < WGRID; gi++) {
        let on = 0;
        for (let dj = -1; dj <= 1 && !on; dj++) {
          for (let di = -1; di <= 1; di++) {
            const ni = gi + di, nj = gj + dj;
            if (ni >= 0 && nj >= 0 && ni < WGRID && nj < WGRID && raw[nj * WGRID + ni]) { on = 1; break; }
          }
        }
        dil[gj * WGRID + gi] = on;
      }
    }
    const f = new Float32Array(WGRID * WGRID);
    for (let i = 0; i < dil.length; i++) f[i] = dil[i];
    this.boxBlur(f, 3); this.boxBlur(f, 3); // soft, smooth shoreline
    // never let water sit on top of the track itself (e.g. Monaco harbour front
    // + tunnel): zero the field inside the track corridor so neither the basin
    // carve nor the water sheet covers the road. Done after the blur so the
    // exclusion stays crisp.
    for (let gj = 0; gj < WGRID; gj++) {
      for (let gi = 0; gi < WGRID; gi++) {
        const X = -G + ((gi + 0.5) / WGRID) * 2 * G;
        const Z = -G + ((gj + 0.5) / WGRID) * 2 * G;
        if (this.distToTrack(X, Z) < ROAD_W * 2.2) f[gj * WGRID + gi] = 0;
      }
    }
    // floor = natural terrain under the wettest cells (field still null here)
    const heights: number[] = [];
    for (let gj = 0; gj < WGRID; gj += 3) {
      for (let gi = 0; gi < WGRID; gi += 3) {
        if (f[gj * WGRID + gi] > 0.6) {
          const X = -G + ((gi + 0.5) / WGRID) * 2 * G;
          const Z = -G + ((gj + 0.5) / WGRID) * 2 * G;
          heights.push(this.heightField(X, Z));
        }
      }
    }
    if (!heights.length) return; // circuit has no water
    heights.sort((a, b) => a - b);
    this.waterFloor = heights[Math.floor(heights.length / 2)] - 1.3;
    this.waterField = f;
    this.recomputeGroundHeights();
    this.buildWaterPlane(f);
  }

  private boxBlur(f: Float32Array, R: number): void {
    const N = WGRID, tmp = new Float32Array(f.length);
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      let s = 0, c = 0;
      for (let d = -R; d <= R; d++) { const ni = i + d; if (ni >= 0 && ni < N) { s += f[j * N + ni]; c++; } }
      tmp[j * N + i] = s / c;
    }
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      let s = 0, c = 0;
      for (let d = -R; d <= R; d++) { const nj = j + d; if (nj >= 0 && nj < N) { s += tmp[nj * N + i]; c++; } }
      f[j * N + i] = s / c;
    }
  }

  private buildWaterPlane(f: Float32Array): void {
    const G = GROUND_G;
    const cv = document.createElement("canvas");
    cv.width = WGRID; cv.height = WGRID;
    const c = cv.getContext("2d")!;
    const img = c.createImageData(WGRID, WGRID);
    for (let i = 0; i < f.length; i++) {
      const g = Math.round(Math.max(0, Math.min(1, f[i])) * 255);
      img.data[i * 4] = g; img.data[i * 4 + 1] = g; img.data[i * 4 + 2] = g; img.data[i * 4 + 3] = 255;
    }
    c.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(cv);
    tex.flipY = false; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
    void WMASK_CS; // (field resolution upsamples smoothly via linear filtering)
    const y = this.waterFloor + 0.45;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(
      [-G, y, -G, G, y, -G, G, y, G, -G, y, G], 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
    geo.setAttribute("normal", new THREE.Float32BufferAttribute([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], 3));
    geo.setIndex([0, 2, 1, 0, 3, 2]);
    const mat = new THREE.MeshStandardMaterial({
      color: this.dark ? 0x123a5c : 0x2f86c4, roughness: 0.07, metalness: 0.5,
      transparent: true, alphaMap: tex, depthWrite: false, side: THREE.DoubleSide,
    });
    this.waterPlane = new THREE.Mesh(geo, mat);
    this.waterPlane.renderOrder = 1;
    this.scene.add(this.waterPlane);
  }

  private recomputeGroundHeights(): void {
    const geo = this.groundGeo;
    if (!geo) return;
    const posAttr = geo.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < posAttr.count; i++) {
      posAttr.setY(i, this.heightField(posAttr.getX(i), posAttr.getZ(i)));
    }
    posAttr.needsUpdate = true;
    geo.computeVertexNormals();
  }

  /** Find places where the lap crosses over/under itself (XZ intersection with a
   *  real vertical gap) and build an arched tunnel over the LOWER road so cars
   *  pass through it instead of disappearing into a hill. */
  private buildTunnels(): void {
    const cl = this.centerline, n = cl.length;
    if (n < 8) return;
    const done: THREE.Vector3[] = [];
    for (let i = 0; i < n; i++) {
      const a1 = cl[i], a2 = cl[(i + 1) % n];
      for (let j = i + 2; j < n; j++) {
        if (i === 0 && j === n - 1) continue; // wrap-adjacent
        const b1 = cl[j], b2 = cl[(j + 1) % n];
        const p = segInt(a1.x, a1.z, a2.x, a2.z, b1.x, b1.z, b2.x, b2.z);
        if (!p) continue;
        const ya = (a1.y + a2.y) * 0.5, yb = (b1.y + b2.y) * 0.5;
        if (Math.abs(ya - yb) < TUNNEL_MIN_DY) continue;
        const cw = new THREE.Vector3(p[0], 0, p[1]);
        if (done.some((d) => (d.x - cw.x) ** 2 + (d.z - cw.z) ** 2 < (ROAD_W * 3) ** 2)) continue;
        done.push(cw);
        this.buildTunnelAt(ya < yb ? i : j, Math.max(ya, yb));
      }
    }
  }

  private buildTunnelAt(idx: number, upperY: number): void {
    const cl = this.centerline, n = cl.length;
    const back: THREE.Vector3[] = [];
    let acc = 0;
    for (let s = 1; s < n; s++) {
      const a = cl[(idx - s + 1 + n) % n], b = cl[(idx - s + n) % n];
      acc += Math.hypot(a.x - b.x, a.z - b.z); back.push(b);
      if (acc > TUNNEL_SPAN) break;
    }
    back.reverse();
    const fwd: THREE.Vector3[] = [];
    acc = 0;
    for (let s = 1; s < n; s++) {
      const a = cl[(idx + s - 1) % n], b = cl[(idx + s) % n];
      acc += Math.hypot(a.x - b.x, a.z - b.z); fwd.push(b);
      if (acc > TUNNEL_SPAN) break;
    }
    const path = [...back, cl[idx], ...fwd];
    if (path.length < 2) return;
    const R = ROAD_W * 0.95;
    const lowerY = cl[idx].y;
    const roofTop = Math.min(upperY - 0.3, lowerY + R + 0.4);
    const archScale = Math.max(0.6, (roofTop - lowerY) / R);
    const K = 7;
    const verts: number[] = [], idxA: number[] = [], rings: number[] = [];
    for (let pi = 0; pi < path.length; pi++) {
      const c = path[pi];
      const a = path[Math.max(0, pi - 1)], b = path[Math.min(path.length - 1, pi + 1)];
      let tx = b.x - a.x, tz = b.z - a.z; const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
      const nx = -tz, nz = tx;
      rings.push(verts.length / 3);
      for (let kk = 0; kk <= K; kk++) {
        const ang = Math.PI * (kk / K);
        const off = Math.cos(ang) * R, up = Math.sin(ang) * R * archScale;
        verts.push(c.x + nx * off, c.y + up, c.z + nz * off);
      }
    }
    for (let pi = 0; pi < path.length - 1; pi++) {
      const r0 = rings[pi], r1 = rings[pi + 1];
      for (let kk = 0; kk < K; kk++) {
        idxA.push(r0 + kk, r1 + kk, r0 + kk + 1, r0 + kk + 1, r1 + kk, r1 + kk + 1);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    geo.setIndex(idxA);
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({ color: 0x1a1c22, roughness: 0.9, metalness: 0.05, side: THREE.DoubleSide });
    this.scene.add(new THREE.Mesh(geo, mat));
    const rim = new THREE.MeshStandardMaterial({ color: 0x2b2e38, roughness: 0.7, emissive: 0x111319 });
    for (const end of [0, path.length - 1]) {
      const c = path[end];
      const a = path[Math.max(0, end - 1)], b = path[Math.min(path.length - 1, end + 1)];
      let tx = b.x - a.x, tz = b.z - a.z; const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
      const nx = -tz, nz = tx;
      const torus = new THREE.Mesh(new THREE.TorusGeometry(R, R * 0.12, 6, 18, Math.PI), rim);
      torus.position.set(c.x, c.y, c.z);
      torus.rotation.y = Math.atan2(-nz, nx);
      torus.scale.y = archScale;
      this.scene.add(torus);
    }
  }

  private buildTrack(): void {
    const pts = this.asset.points;
    const elev = this.asset.elevation ?? [];
    const n = pts.length;
    const center: THREE.Vector3[] = [];
    for (let i = 0; i < n; i++) {
      const [wx, wz] = this.worldXZ(pts[i][0], pts[i][1]);
      const wy = ((elev[i] ?? 0) - this.ymin) * this.k * VEXAG;
      center.push(new THREE.Vector3(wx, wy, wz));
    }
    this.centerline = center;
    const pos: number[] = [];
    const idx: number[] = [];
    const hw = ROAD_W / 2;
    for (let i = 0; i < n; i++) {
      const a = center[(i - 1 + n) % n];
      const b = center[(i + 1) % n];
      let tx = b.x - a.x, tz = b.z - a.z;
      const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
      const nx = -tz, nz = tx;
      const c = center[i];
      pos.push(c.x + nx * hw, c.y + 0.05, c.z + nz * hw);
      pos.push(c.x - nx * hw, c.y + 0.05, c.z - nz * hw);
    }
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      const l0 = 2 * i, r0 = 2 * i + 1, l1 = 2 * j, r1 = 2 * j + 1;
      idx.push(l0, r0, r1, l0, r1, l1);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({
      color: 0x2a2d36, roughness: 0.85, metalness: 0.0, side: THREE.DoubleSide,
    });
    this.trackMesh = new THREE.Mesh(geo, mat);
    this.scene.add(this.trackMesh);
    const edgePts = (off: number) => {
      const v: THREE.Vector3[] = [];
      for (let i = 0; i <= n; i++) {
        const ii = i % n;
        v.push(new THREE.Vector3(pos[6 * ii + off], pos[6 * ii + 1 + off] + 0.04, pos[6 * ii + 2 + off]));
      }
      return v;
    };
    for (const off of [0, 3]) {
      const lg = new THREE.BufferGeometry().setFromPoints(edgePts(off));
      const seg = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: 0xffffff }));
      this.scene.add(seg);
    }
  }

  private buildStartFinish(): void {
    const sf = this.asset.start_finish;
    const [wx, wz] = this.worldXZ(sf.x, sf.y);
    const wy = this.elevAt(wx, wz);
    const geo = new THREE.BoxGeometry(ROAD_W * 1.1, 0.4, 1.0);
    const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0x222222 });
    const m = new THREE.Mesh(geo, mat);
    m.position.set(wx, wy + 0.35, wz);
    m.rotation.y = Math.atan2(-sf.dy, sf.dx);
    this.scene.add(m);
  }

  private buildCorners(): void {
    for (const c of this.asset.corners) {
      const [wx, wz] = this.worldXZ(c.x, c.y);
      const wy = this.elevAt(wx, wz);
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(0.55, 10, 8),
        new THREE.MeshStandardMaterial({ color: 0x0fae9e, emissive: 0x0b6b62 }),
      );
      m.position.set(wx, wy + 0.7, wz);
      this.scene.add(m);
      const lbl = new THREE.Sprite(new THREE.SpriteMaterial({
        map: labelTexture(String(c.n)), transparent: true, depthWrite: false, depthTest: false,
      }));
      lbl.scale.set(2.6, 1.3, 1);
      lbl.position.set(wx, wy + 2.1, wz);
      this.scene.add(lbl);
    }
  }

  private buildF1Car(color: string): CarObj {
    const group = new THREE.Group();
    const col = new THREE.Color(color);
    // imported model (if /models/f1.glb was provided): clone + team-tint
    if (this.carTemplate) {
      const model = this.carTemplate.clone(true);
      model.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (mesh.isMesh && mesh.material) {
          const mat = (mesh.material as THREE.MeshStandardMaterial).clone();
          if (mat.emissive) mat.emissive = col.clone().multiplyScalar(0.35);
          mesh.material = mat;
        }
      });
      group.add(model);
      const label = makeLabel();
      label.position.y = 2.2;
      group.add(label);
      this.scene.add(group);
      return { group, body: new THREE.Mesh(), wheels: [], label, heading: 0, lastX: 0, lastZ: 0 };
    }
    const team = new THREE.MeshStandardMaterial({ color: col, roughness: 0.45, metalness: 0.25 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x141417, roughness: 0.6 });
    const tyre = new THREE.MeshStandardMaterial({ color: 0x0e0e11, roughness: 0.85 });
    const add = (geo: THREE.BufferGeometry, mat: THREE.Material, x: number, y: number, z: number) => {
      const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); group.add(m); return m;
    };
    add(new THREE.BoxGeometry(2.4, 0.16, 0.86), team, 0, 0.30, 0);
    const body = add(new THREE.BoxGeometry(1.5, 0.26, 0.5), team, 0.15, 0.42, 0) as THREE.Mesh;
    add(new THREE.BoxGeometry(1.2, 0.18, 0.32), team, 1.25, 0.30, 0);
    add(new THREE.ConeGeometry(0.14, 0.5, 10).rotateZ(-Math.PI / 2), team, 1.95, 0.28, 0);
    add(new THREE.BoxGeometry(0.5, 0.05, 1.55), dark, 1.95, 0.16, 0);
    add(new THREE.BoxGeometry(0.5, 0.22, 0.05), dark, 1.95, 0.24, 0.78);
    add(new THREE.BoxGeometry(0.5, 0.22, 0.05), dark, 1.95, 0.24, -0.78);
    add(new THREE.BoxGeometry(1.15, 0.3, 0.34), team, -0.05, 0.32, 0.42);
    add(new THREE.BoxGeometry(1.15, 0.3, 0.34), team, -0.05, 0.32, -0.42);
    add(new THREE.BoxGeometry(1.2, 0.34, 0.34), team, -0.5, 0.5, 0);
    add(new THREE.BoxGeometry(0.28, 0.24, 0.3), dark, 0.5, 0.62, 0);
    add(new THREE.BoxGeometry(0.5, 0.2, 0.42), dark, 0.5, 0.5, 0);
    const halo = add(new THREE.TorusGeometry(0.28, 0.035, 8, 18, Math.PI), dark, 0.55, 0.58, 0);
    halo.rotation.x = Math.PI / 2; halo.rotation.z = Math.PI / 2;
    add(new THREE.BoxGeometry(0.04, 0.04, 0.5), dark, 0.85, 0.6, 0);
    add(new THREE.BoxGeometry(0.45, 0.05, 1.25), dark, -1.45, 0.82, 0);
    add(new THREE.BoxGeometry(0.06, 0.45, 0.06), dark, -1.45, 0.6, 0.25);
    add(new THREE.BoxGeometry(0.06, 0.45, 0.06), dark, -1.45, 0.6, -0.25);
    const wheels: THREE.Group[] = [];
    const mkWheel = (x: number, z: number) => {
      const wg = new THREE.Group();
      wg.position.set(x, WHEEL_R, z);
      const tyreMesh = new THREE.Mesh(
        new THREE.CylinderGeometry(WHEEL_R, WHEEL_R, 0.32, 18).rotateX(Math.PI / 2), tyre);
      const hub = new THREE.Mesh(
        new THREE.CylinderGeometry(0.16, 0.16, 0.34, 12).rotateX(Math.PI / 2),
        new THREE.MeshStandardMaterial({ color: 0x999999, metalness: 0.6, roughness: 0.4 }));
      wg.add(tyreMesh); wg.add(hub);
      group.add(wg); wheels.push(wg);
    };
    mkWheel(1.05, 0.66); mkWheel(1.05, -0.66);
    mkWheel(-1.05, 0.66); mkWheel(-1.05, -0.66);
    const label = makeLabel();
    label.position.y = 2.2;
    group.add(label);
    this.scene.add(group);
    return { group, body, wheels, label, heading: 0, lastX: 0, lastZ: 0 };
  }

  private ensureCar(drv: string, color: string): CarObj {
    let car = this.cars.get(drv);
    if (!car) {
      car = this.buildF1Car(color);
      car.label.material.map = labelTexture(drv);
      car.label.material.needsUpdate = true;
      this.cars.set(drv, car);
    }
    return car;
  }

  setMode(mode: "orbit" | "chase" | "flyover"): void {
    this.mode = mode;
    this.disableFly();
    if (mode === "flyover") this.enableFly();      // free-fly drone (WASD + mouse)
    else this.controls.enabled = mode !== "chase"; // orbit user-driven, chase camera-driven
  }

  // ---- Free-fly drone (flyover): WASD translate, mouse turns + changes altitude ----
  private enableFly(): void {
    this.controls.enabled = false;
    const dir = new THREE.Vector3();
    this.camera.getWorldDirection(dir);
    this.fly.yaw = Math.atan2(dir.z, dir.x);
    this.fly.active = true;
    this.fly.keys.clear();
    window.addEventListener("keydown", this.flyKeyDown);
    window.addEventListener("keyup", this.flyKeyUp);
    document.addEventListener("mousemove", this.flyMouse);
    document.addEventListener("pointerlockchange", this.flyLockChange);
    this.renderer.domElement.addEventListener("click", this.flyClick);
  }

  private disableFly(): void {
    if (!this.fly.active) return;
    this.fly.active = false;
    this.fly.keys.clear();
    window.removeEventListener("keydown", this.flyKeyDown);
    window.removeEventListener("keyup", this.flyKeyUp);
    document.removeEventListener("mousemove", this.flyMouse);
    document.removeEventListener("pointerlockchange", this.flyLockChange);
    this.renderer.domElement.removeEventListener("click", this.flyClick);
    if (document.pointerLockElement === this.renderer.domElement) document.exitPointerLock?.();
    this.fly.locked = false;
  }

  isPointerLocked(): boolean { return this.fly.locked; }

  private onFlyKey(e: KeyboardEvent, down: boolean): void {
    if (!this.fly.active) return;
    const k = e.key.toLowerCase();
    if (k === "w" || k === "a" || k === "s" || k === "d") {
      if (down) this.fly.keys.add(k); else this.fly.keys.delete(k);
      e.preventDefault();
    }
  }

  private onFlyMouse(e: MouseEvent): void {
    if (!this.fly.active || !this.fly.locked) return;
    this.fly.yaw += e.movementX * 0.0026;            // mouse right => turn right (yaw)
    this.camera.position.y += -e.movementY * 0.14;   // forward(up)/back(down) => altitude
    const minY = this.waterFloor + 3;
    if (this.camera.position.y < minY) this.camera.position.y = minY;
  }

  private updateFly(dt: number): void {
    const f = this.fly;
    const cosY = Math.cos(f.yaw), sinY = Math.sin(f.yaw);
    const fwd = new THREE.Vector3(cosY, 0, sinY);
    const right = new THREE.Vector3(-sinY, 0, cosY);
    const mv = new THREE.Vector3();
    if (f.keys.has("w")) mv.add(fwd);
    if (f.keys.has("s")) mv.sub(fwd);
    if (f.keys.has("d")) mv.add(right);
    if (f.keys.has("a")) mv.sub(right);
    if (mv.lengthSq() > 0) { mv.normalize().multiplyScalar(f.speed * dt); this.camera.position.add(mv); }
    const p = this.camera.position, cp = Math.cos(f.pitch);
    this.camera.lookAt(p.x + cosY * cp, p.y + Math.sin(f.pitch), p.z + sinY * cp);
  }

  setTheme(dark: boolean): void {
    this.dark = dark;
    this.applyTheme();
    if (this.groundBuilt && this.drawGroundCanvas() && this.groundTex) this.groundTex.needsUpdate = true;
  }

  private applyTheme(): void {
    const sky = this.dark ? 0x0c0e14 : 0xdfe6ee;
    (this.scene.fog as THREE.Fog).color.set(sky);
    const groundMat = this.ground.material as THREE.MeshStandardMaterial;
    if (!groundMat.map) groundMat.color.set(this.dark ? 0x0c0e14 : 0xdfe3ea);
    this.hemi.intensity = this.dark ? 0.85 : 1.15;
    this.dir.intensity = this.dark ? 1.25 : 1.5;
    (this.trackMesh?.material as THREE.MeshStandardMaterial)?.color.set(this.dark ? 0x23262f : 0x33363f);
  }

  resize(): void {
    const w = this.container.clientWidth || 1;
    const h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  render(cars: CarState3D[], selected: string | null): void {
    const now = performance.now();
    const dt = Math.min((now - this.lastFrame) / 1000, 0.05);
    this.lastFrame = now;
    this.tickGround();
    const seen = new Set<string>();
    for (const c of cars) {
      seen.add(c.drv);
      const obj = this.ensureCar(c.drv, c.color);
      const ax = this.rc * c.x - this.rs * c.y;
      const ay = this.rs * c.x + this.rc * c.y;
      const [wx, wz] = this.worldXZ(ax, ay);
      const wy = this.elevAt(wx, wz);
      const dx = wx - obj.lastX, dz = wz - obj.lastZ;
      const moved = Math.hypot(dx, dz);
      if (moved > 0.01) obj.heading = lerpAngle(obj.heading, Math.atan2(dz, dx), 0.3);
      obj.lastX = wx; obj.lastZ = wz;
      obj.group.position.set(wx, wy + 0.02, wz);
      obj.group.rotation.y = -obj.heading;
      const roll = moved / WHEEL_R;
      for (const wgp of obj.wheels) wgp.rotation.z -= roll;
      const isSel = c.drv === selected;
      obj.group.scale.setScalar(isSel ? CAR_SCALE * 1.35 : CAR_SCALE);
      const bm = obj.body.material as THREE.MeshStandardMaterial;
      if (bm.emissive) bm.emissive.set(isSel ? 0x333333 : 0x000000);
    }
    for (const [drv, obj] of this.cars) obj.group.visible = seen.has(drv);

    if (this.mode === "chase" && selected && this.cars.get(selected)?.group.visible) {
      const obj = this.cars.get(selected)!;
      const p = obj.group.position;
      const hx = Math.cos(obj.heading), hz = Math.sin(obj.heading);
      this.camera.position.lerp(new THREE.Vector3(p.x - hx * 13, p.y + 6.5, p.z - hz * 13), 0.1);
      this.camera.lookAt(p.x + hx * 5, p.y + 1, p.z + hz * 5);
    } else if (this.mode === "flyover") {
      this.updateFly(dt); // free-fly drone — WASD + mouse, no auto motion
    } else {
      this.controls.update();
    }
    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.disableFly();
    this.controls.dispose();
    this.scene.traverse((o) => {
      const any = o as unknown as { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
      any.geometry?.dispose?.();
      const m = any.material;
      if (Array.isArray(m)) m.forEach((x) => x.dispose()); else m?.dispose?.();
    });
    this.groundTex?.dispose();
    this.renderer.dispose();
    if (this.renderer.domElement.parentElement === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }
}

const _labelCache = new Map<string, THREE.CanvasTexture>();
function labelTexture(text: string): THREE.CanvasTexture {
  let t = _labelCache.get(text);
  if (t) return t;
  const cv = document.createElement("canvas");
  cv.width = 128; cv.height = 64;
  const ctx = cv.getContext("2d")!;
  ctx.fillStyle = "rgba(12,14,20,0.82)";
  roundRect(ctx, 4, 14, 120, 36, 8); ctx.fill();
  ctx.fillStyle = "#ffffff";
  ctx.font = "700 28px ui-monospace, monospace";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, 64, 33);
  t = new THREE.CanvasTexture(cv);
  t.minFilter = THREE.LinearFilter;
  _labelCache.set(text, t);
  return t;
}

function makeLabel(): THREE.Sprite {
  const mat = new THREE.SpriteMaterial({ transparent: true, depthWrite: false });
  const sp = new THREE.Sprite(mat);
  sp.scale.set(5.5, 2.75, 1);
  return sp;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function lerpAngle(a: number, b: number, t: number): number {
  let d = b - a;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return a + d * t;
}

/** Proper 2D segment intersection (exclusive of endpoints). Returns the
 *  intersection point [x, y] or null. Used to find track over/under crossings. */
function segInt(
  ax: number, ay: number, bx: number, by: number,
  cx: number, cy: number, dx: number, dy: number,
): [number, number] | null {
  const r1x = bx - ax, r1y = by - ay, r2x = dx - cx, r2y = dy - cy;
  const den = r1x * r2y - r1y * r2x;
  if (Math.abs(den) < 1e-9) return null;
  const t = ((cx - ax) * r2y - (cy - ay) * r2x) / den;
  const u = ((cx - ax) * r1y - (cy - ay) * r1x) / den;
  if (t <= 0 || t >= 1 || u <= 0 || u >= 1) return null;
  return [ax + t * r1x, ay + t * r1y];
}
