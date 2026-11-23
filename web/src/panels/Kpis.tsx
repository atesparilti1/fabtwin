import { scaleLinear } from 'd3-scale';
import { useMemo, useState } from 'react';
import { fmt } from '../lib/format';
import { useWidth } from '../lib/hooks';
import { clock, useClock } from '../replay/clock';
import type { ReplayModel } from '../replay/model';
import type { Series } from '../replay/types';

type Key = Exclude<keyof Series, 't'>;
interface KpiDef {
  key: Key;
  label: string;
  unit: string;
  digits: number;
  scale: number;
  better: 'lower' | 'higher';
}
export const KPIS: KpiDef[] = [
  { key: 'wip', label: 'WIP', unit: 'lots', digits: 0, scale: 1, better: 'lower' },
  { key: 'thr', label: 'Throughput', unit: 'lots/day', digits: 1, scale: 1, better: 'higher' },
  { key: 'ct', label: 'Cycle time', unit: 'days', digits: 2, scale: 1, better: 'lower' },
  { key: 'ontime', label: 'On-time', unit: '%', digits: 1, scale: 1, better: 'higher' },
  { key: 'litho', label: 'Litho utilisation', unit: '%', digits: 1, scale: 100, better: 'higher' },
];

function val(m: ReplayModel, k: KpiDef, t: number): number | null {
  const v = m.raw.series[k.key][m.seriesIndex(t)];
  return v == null ? null : v * k.scale;
}

function Delta({ a, b, k }: { a: number | null; b: number | null; k: KpiDef }) {
  if (a == null || b == null) return <span className="num text-xs text-ink3">—</span>;
  const d = b - a;
  const eps = Math.pow(10, -k.digits) / 2;
  if (Math.abs(d) < eps) return <span className="num text-xs text-ink3">±0</span>;
  const good = k.better === 'higher' ? d > 0 : d < 0;
  return (
    <span className="num inline-flex items-center gap-1 text-xs" style={{ color: good ? '#5fd39a' : '#ff7a6e' }}>
      <svg width="7" height="6" viewBox="0 0 7 6" aria-hidden style={{ transform: d < 0 ? 'rotate(180deg)' : undefined }}>
        <path d="M3.5 0 7 6H0z" fill="currentColor" />
      </svg>
      {fmt(Math.abs(d), k.digits)}
      <span className="sr-only">{good ? 'better' : 'worse'} than A</span>
    </span>
  );
}

export default function Kpis({ a, b }: { a: ReplayModel; b: ReplayModel | null }) {
  const snap = useClock();
  const [sel, setSel] = useState<Key>('wip');
  const k = KPIS.find((x) => x.key === sel)!;
  return (
    <div className="grid gap-px border-t border-line bg-line lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="grid grid-cols-2 gap-px sm:grid-cols-5">
        {KPIS.map((kp) => {
          const va = val(a, kp, snap.t);
          const vb = b ? val(b, kp, snap.t) : null;
          const on = kp.key === sel;
          return (
            <button
              type="button"
              key={kp.key}
              onClick={() => setSel(kp.key)}
              aria-pressed={on}
              className={`group relative bg-bg px-4 py-3 text-left transition-colors hover:bg-raised ${on ? 'bg-raised' : ''}`}
            >
              {on && <span className="absolute inset-x-0 top-0 h-px bg-amber" />}
              <div className="label text-ink3 group-hover:text-ink2">{kp.label}</div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className="num text-xl text-ink">{fmt(va, kp.digits)}</span>
                <span className="text-2xs text-ink3">{kp.unit}</span>
              </div>
              {b && (
                <div className="mt-0.5 flex items-baseline gap-2">
                  <span className="num text-sm text-cyan">{fmt(vb, kp.digits)}</span>
                  <Delta a={va} b={vb} k={kp} />
                </div>
              )}
            </button>
          );
        })}
      </div>
      <Trace a={a} b={b} k={k} />
    </div>
  );
}

function Trace({ a, b, k }: { a: ReplayModel; b: ReplayModel | null; k: KpiDef }) {
  const [ref, w] = useWidth<HTMLDivElement>(600);
  const snap = useClock();
  const h = 124;
  const pad = { l: 40, r: 12, t: 30, b: 20 };
  const geo = useMemo(() => {
    const s = a.raw.series;
    const pick = (m: ReplayModel) => m.raw.series[k.key].map((v) => (v == null ? null : v * k.scale));
    const ya = pick(a);
    const yb = b ? pick(b) : null;
    const all = [...ya, ...(yb ?? [])].filter((v): v is number => v != null);
    const lo = Math.min(...all), hi = Math.max(...all);
    const x = scaleLinear().domain([a.t0, a.t1]).range([pad.l, w - pad.r]);
    const y = scaleLinear().domain(lo === hi ? [lo - 1, hi + 1] : [lo, hi]).nice(4).range([h - pad.b, pad.t]);
    const path = (ys: (number | null)[]) => {
      let d = '';
      let pen = false;
      ys.forEach((v, i) => {
        if (v == null) { pen = false; return; }
        d += `${pen ? 'L' : 'M'}${x(s.t[i]).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      return d;
    };
    return { x, y, pa: path(ya), pb: yb ? path(yb) : null };
  }, [a, b, k, w, pad.l, pad.r, pad.t, pad.b]);
  const cx = geo.x(snap.t);
  return (
    <div ref={ref} className="relative bg-bg px-0 py-1">
      <div className="absolute left-4 top-2 flex items-center gap-4 text-2xs text-ink3">
        <span className="label">{k.label} · replay window</span>
        <span className="flex items-center gap-1.5"><span className="h-px w-4 bg-ink2" />A</span>
        {b && <span className="flex items-center gap-1.5"><span className="h-px w-4 bg-cyan" />B</span>}
      </div>
      <svg
        width={w}
        height={h}
        className="block cursor-crosshair"
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          clock.seek(geo.x.invert(e.clientX - r.left));
        }}
        role="img"
        aria-label={`${k.label} over the replay window; click to seek`}
      >
        {geo.y.ticks(3).map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={w - pad.r} y1={geo.y(v)} y2={geo.y(v)} stroke="var(--line)" />
            <text x={pad.l - 6} y={geo.y(v) + 3} textAnchor="end" className="num" fontSize={10} fill="var(--ink-3)">
              {fmt(v, k.digits === 0 ? 0 : k.digits - 1)}
            </text>
          </g>
        ))}
        <path d={geo.pa} fill="none" stroke="var(--ink-2)" strokeWidth={1.25} />
        {geo.pb && <path d={geo.pb} fill="none" stroke="var(--cyan)" strokeWidth={1.25} />}
        <line x1={cx} x2={cx} y1={pad.t - 4} y2={h - pad.b} stroke="var(--amber)" />
      </svg>
    </div>
  );
}
