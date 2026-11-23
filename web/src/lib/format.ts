/** Sim clock: hours since start -> "Day 41 · 07:12". */
export function clock(t: number): { day: number; hhmm: string } {
  const day = Math.floor(t / 24);
  const mins = Math.floor((t - day * 24) * 60 + 1e-6);
  const hh = Math.floor(mins / 60), mm = mins % 60;
  return { day: day + 1, hhmm: `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}` };
}
export function clockStr(t: number): string { const c = clock(t); return `D${c.day} ${c.hhmm}`; }
export function fmt(v: number | null | undefined, d = 1): string {
  if (v == null || !Number.isFinite(v)) return '—';
  return v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
export function hours(h: number): string {
  if (!Number.isFinite(h)) return '—';
  const a = Math.abs(h);
  if (a < 1) return `${Math.round(h * 60)} min`;
  if (a < 48) return `${fmt(h, 1)} h`;
  return `${fmt(h / 24, 1)} d`;
}
export function bytes(n: number): string { return `${(n / 1e6).toFixed(1)} MB`; }
