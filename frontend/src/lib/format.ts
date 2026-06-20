export function fmtClock(totalS: number): string {
  const s = Math.max(0, Math.floor(totalS));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = (s % 60).toString().padStart(2, "0");
  return h > 0 ? `${h}:${m.toString().padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function fmtLap(d: number | null | undefined): string {
  if (d == null) return "—";
  const m = Math.floor(d / 60);
  const s = (d - m * 60).toFixed(3).padStart(6, "0");
  return `${m}:${s}`;
}

export function fmtGap(g: string | null | undefined): string {
  if (g == null) return "—";
  const n = Number(g);
  return Number.isNaN(n) ? g : `+${n.toFixed(3)}`;
}

export function intervalSeconds(g: string | null | undefined): number | null {
  if (g == null) return null;
  const n = Number(g);
  return Number.isNaN(n) ? null : n;
}
