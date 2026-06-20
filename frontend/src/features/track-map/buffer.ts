// Per-driver position ring buffers + interpolation for the render clock.
// Input arrives at ~4 Hz (session time); we render at 60 fps slightly behind
// the newest sample so there is always a bracket to interpolate inside.

export interface Sample { t: number; x: number; y: number; }

export const RENDER_LAG_S = 1.0;   // how far behind newest data we render
export const HARD_JUMP_S = 5;      // bigger time jump => seek: flush buffers
export const STALE_S = 15;         // no data for this long => car retired/hidden
const KEEP_S = 8;                  // history kept per driver

export class PositionBuffers {
  private buf = new Map<string, Sample[]>();
  newestT = 0;

  push(t: number, cars: { drv: string; x: number; y: number }[]): boolean {
    const jumped = Math.abs(t - this.newestT) > HARD_JUMP_S && this.newestT !== 0;
    if (jumped) this.buf.clear();
    this.newestT = t;
    for (const c of cars) {
      let arr = this.buf.get(c.drv);
      if (!arr) this.buf.set(c.drv, (arr = []));
      if (arr.length && arr[arr.length - 1].t >= t) continue; // dedupe
      arr.push({ t, x: c.x, y: c.y });
      const cutoff = t - KEEP_S;
      while (arr.length > 2 && arr[0].t < cutoff) arr.shift();
    }
    return jumped;
  }

  clear(): void {
    this.buf.clear();
    this.newestT = 0;
  }

  drivers(): string[] {
    return [...this.buf.keys()];
  }

  /** Interpolated position at session time t, or null if no data yet. */
  at(drv: string, t: number): { x: number; y: number } | null {
    const arr = this.buf.get(drv);
    if (!arr || arr.length === 0) return null;
    if (t <= arr[0].t) return arr[0];
    const last = arr[arr.length - 1];
    if (t >= last.t) {
      // hold briefly (sampling gaps), but hide retired cars
      return t - last.t > STALE_S ? null : last;
    }
    // search backwards: render time is near the end almost always
    let i = arr.length - 2;
    while (i > 0 && arr[i].t > t) i--;
    const a = arr[i];
    const b = arr[i + 1];
    const f = (t - a.t) / (b.t - a.t || 1);
    return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f };
  }
}
