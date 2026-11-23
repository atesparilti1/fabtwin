import { scaleLinear, scaleLog } from 'd3-scale';
import { useMemo, useState } from 'react';
import { clockStr, fmt } from '../lib/format';
import { useWidth } from '../lib/hooks';
import { recipeColor } from '../lib/palette';
import { clock, useClock } from '../replay/clock';
import { useScenario } from '../replay/load';
import type { ReplayModel } from '../replay/model';
import type { ScenarioIndex } from '../replay/types';
import { isCI, type Analytics as AnalyticsData, type CI } from './analyticsTypes';

const CAT = ['#101417', '#9a6100', '#1f7f78', '#5560c4', '#b5482f', '#6b7780', '#7a4d8f'];

export default function Analytics({ data, index }: { data: AnalyticsData | null; index: ScenarioIndex | null }) {
  return (
    <section id="analytics" className="paper border-t border-pline" aria-labelledby="analytics-title">
      <div className="mx-auto max-w-[1600px] px-4 pb-20 pt-16 md:px-6">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <h2 id="analytics-title" className="display text-4xl text-pink md:text-5xl">Results</h2>
          <p className="max-w-[60ch] self-end text-sm leading-relaxed text-pink2">
            The replay shows one run; the claims rest on replications. Benchmarks below come from{' '}
            <code className="num rounded-sm bg-paper2 px-1 text-pink">analytics.json</code>, written by <code className="num rounded-sm bg-paper2 px-1 text-pink">make bench</code>.
            Intervals are 95% confidence half-widths over common-random-number replications. A section that has not been run yet says so
            instead of showing a placeholder.
          </p>
        </div>

        <Headline data={data} />

        <div className="mt-14 grid gap-x-12 gap-y-16 xl:grid-cols-2">
          <Figure title="Dispatching rules under uncertainty" note={data?.dispatch ? `${data.dispatch.replications} replications · instance ${data.dispatch.instance}` : undefined} wide>
            {data === null ? <Pending /> : data.dispatch ? <DispatchCI d={data.dispatch} /> : <Empty section="dispatch" />}
          </Figure>
          <Figure title="Litho bottleneck schedule" note="replay window · bars coloured by reticle (hue = product, shade = layer)" wide>
            <LithoGantt index={index} />
          </Figure>
          {data?.exact && (
            <Figure title="Exact vs heuristic" note="small instances, weighted tardiness">
              <ExactTable d={data.exact} />
            </Figure>
          )}
          {data?.scaling && (
            <Figure title="Solver scaling" note="runtime as instances grow">
              <Scaling d={data.scaling} />
            </Figure>
          )}
          {data?.pareto && (
            <Figure title="Pareto front" note={`${data.pareto.x} vs ${data.pareto.y}`}>
              <Pareto d={data.pareto} />
            </Figure>
          )}
          {data?.convergence && (
            <Figure title="Search convergence" note="best objective by iteration">
              <Convergence d={data.convergence} />
            </Figure>
          )}
          {data?.oht && (
            <Figure title="OHT fleet sizing and assignment">
              <CITable rows={data.oht.rows} />
            </Figure>
          )}
          {data?.maintenance && (
            <Figure title="Maintenance policies">
              <CITable rows={data.maintenance.rows} />
            </Figure>
          )}
          {data && <PendingSections data={data} />}
        </div>
      </div>
    </section>
  );
}

function Figure({ title, note, wide, children }: { title: string; note?: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <figure className={`min-w-0 border-t border-pink pt-4 ${wide ? 'xl:col-span-2' : ''}`}>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="wide text-lg font-semibold text-pink">{title}</h3>
        {note && <figcaption className="text-xs text-pink3">{note}</figcaption>}
      </div>
      {children}
    </figure>
  );
}

function Pending() {
  return <div className="h-24 animate-pulse bg-paper2/60" aria-label="Loading analytics" />;
}

const SECTIONS: { key: keyof AnalyticsData; title: string; what: string }[] = [
  { key: 'exact', title: 'Exact vs heuristic', what: 'CP-SAT and MIP optima and bounds against dispatching rules and ALNS on small instances' },
  { key: 'scaling', title: 'Solver scaling', what: 'runtime and gap as the instance grows' },
  { key: 'pareto', title: 'Pareto front', what: 'trade-off between competing objectives' },
  { key: 'convergence', title: 'Search convergence', what: 'best and current objective by ALNS iteration' },
  { key: 'oht', title: 'OHT fleet', what: 'vehicle count and assignment policy against wait time and Q-time violations' },
  { key: 'maintenance', title: 'Maintenance policies', what: 'run-to-failure against preventive maintenance' },
];

function PendingSections({ data }: { data: AnalyticsData }) {
  const missing = SECTIONS.filter((s) => !data[s.key]);
  if (!missing.length) return null;
  return (
    <div className="min-w-0 border-t border-pink pt-4 xl:col-span-2">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="wide text-lg font-semibold text-pink">Not yet computed</h3>
        <p className="text-xs text-pink3">
          Run <code className="num rounded-sm bg-paper2 px-1 text-pink">make bench</code> to write these sections of analytics.json; each appears here as a figure.
        </p>
      </div>
      <ul className="grid gap-x-10 border-t border-dashed border-pline sm:grid-cols-2 xl:grid-cols-3">
        {missing.map((s) => (
          <li key={s.key} className="border-b border-dashed border-pline py-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium text-pink2">{s.title}</span>
              <code className="num text-2xs text-pink3">{s.key}</code>
            </div>
            <p className="mt-0.5 text-xs leading-snug text-pink3">{s.what}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Empty({ section }: { section: string }) {
  return (
    <div className="flex min-h-[9rem] flex-col justify-center border border-dashed border-pline px-5 py-6">
      <div className="text-sm font-medium text-pink2">Not yet computed</div>
      <p className="mt-1 text-sm text-pink3">
        Run <code className="num rounded-sm bg-paper2 px-1 text-pink">make bench</code> to write the{' '}
        <code className="num text-pink2">{section}</code> section of analytics.json.
      </p>
    </div>
  );
}

/* --------------------------------------------------------------- headline */
function Headline({ data }: { data: AnalyticsData | null }) {
  const h = data?.headline;
  if (!h || !h.deltas?.length) {
    return (
      <div className="mt-10 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-y border-pline py-4 text-sm text-pink3">
        <span className="wide font-semibold text-pink2">Headline deltas</span>
        <span>
          not yet computed. Run <code className="num rounded-sm bg-paper2 px-1 text-pink">make bench</code> to compare the FabTwin policy against the
          FIFO baseline.
        </span>
      </div>
    );
  }
  return (
    <div className="mt-10 grid gap-px border-y border-pline bg-pline sm:grid-cols-2 lg:grid-cols-4">
      {h.deltas.map((d) => (
        <div key={d.label} className="bg-paper px-1 py-5 sm:px-5">
          <div className="num text-3xl text-pink">
            {d.mean > 0 ? '+' : ''}
            {fmt(d.mean, 1)}
            <span className="text-lg text-pink3">{d.unit}</span>
          </div>
          <div className="num mt-0.5 text-xs text-pink3">± {fmt(d.hw, 1)}{d.unit} (95% CI)</div>
          <div className="mt-2 text-sm text-pink2">{d.label}</div>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ dispatch CI */
function DispatchCI({ d }: { d: NonNullable<AnalyticsData['dispatch']> }) {
  const [key, setKey] = useState(d.kpis[0]?.key ?? '');
  const [ref, w] = useWidth<HTMLDivElement>(900);
  const kpi = d.kpis.find((k) => k.key === key) ?? d.kpis[0];
  const pct = kpi.key.includes('util');
  const sc = pct ? 100 : 1;
  const rows = d.rows
    .filter((r) => r.values[kpi.key])
    .map((r) => ({ policy: r.policy, mean: r.values[kpi.key].mean * sc, hw: r.values[kpi.key].hw * sc }))
    .sort((a, b) => (kpi.better === 'lower' ? a.mean - b.mean : b.mean - a.mean));
  const rowH = 34;
  const pad = { l: 72, r: 132, t: 8, b: 28 };
  const h = pad.t + rows.length * rowH + pad.b;
  const lo = Math.min(...rows.map((r) => r.mean - r.hw));
  const hi = Math.max(...rows.map((r) => r.mean + r.hw));
  const span = hi - lo || 1;
  const x = scaleLinear().domain([lo - span * 0.08, hi + span * 0.08]).nice(6).range([pad.l, w - pad.r]);
  const best = rows[0];
  return (
    <div>
      <div role="radiogroup" aria-label="KPI" className="mb-5 flex flex-wrap gap-1">
        {d.kpis.map((k) => (
          <button
            key={k.key}
            type="button"
            role="radio"
            aria-checked={k.key === kpi.key}
            onClick={() => setKey(k.key)}
            className={`rounded-sm px-2.5 py-1 text-xs transition-colors ${k.key === kpi.key ? 'bg-pink text-paper' : 'text-pink2 hover:bg-paper2 hover:text-pink'}`}
          >
            {k.label}
          </button>
        ))}
      </div>
      <div ref={ref}>
        <svg width={w} height={h} className="block" role="img" aria-label={`${kpi.label}: mean and 95% confidence interval per dispatching rule`}>
          {x.ticks(6).map((v) => (
            <g key={v}>
              <line x1={x(v)} x2={x(v)} y1={pad.t} y2={h - pad.b} stroke="var(--p-line)" strokeDasharray={v === 0 ? undefined : '1 3'} />
              <text x={x(v)} y={h - 8} textAnchor="middle" fontSize={10} className="num" fill="var(--p-ink-3)">
                {fmt(v, span * sc < 2 ? 2 : span < 20 ? 1 : 0)}
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y = pad.t + i * rowH + rowH / 2;
            const isBest = r === best;
            const col = isBest ? 'var(--amber-deep)' : 'var(--p-ink)';
            const overlap = !isBest && r.mean - r.hw <= best.mean + best.hw && r.mean + r.hw >= best.mean - best.hw;
            return (
              <g key={r.policy}>
                {i % 2 === 0 && <rect x={0} y={y - rowH / 2} width={w} height={rowH} fill="var(--p-ink)" opacity={0.03} />}
                <text x={0} y={y + 4} fontSize={13} fontWeight={600} fill={col}>{r.policy}</text>
                <line x1={x(r.mean - r.hw)} x2={x(r.mean + r.hw)} y1={y} y2={y} stroke={col} strokeWidth={1.5} />
                <line x1={x(r.mean - r.hw)} x2={x(r.mean - r.hw)} y1={y - 5} y2={y + 5} stroke={col} strokeWidth={1.5} />
                <line x1={x(r.mean + r.hw)} x2={x(r.mean + r.hw)} y1={y - 5} y2={y + 5} stroke={col} strokeWidth={1.5} />
                <rect x={x(r.mean) - 4} y={y - 4} width={8} height={8} fill={isBest ? 'var(--amber)' : 'var(--paper)'} stroke={col} strokeWidth={1.5} />
                <text x={w - pad.r + 14} y={y + 4} fontSize={12} className="num" fill="var(--p-ink)">
                  {fmt(r.mean, 2)}
                  <tspan fill="var(--p-ink-3)"> ± {fmt(r.hw, 2)}</tspan>
                </text>
                {overlap && (
                  <text x={w - 4} y={y + 4} textAnchor="end" fontSize={10} fill="var(--p-ink-3)">
                    ≈ best
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="mt-3 max-w-[75ch] text-xs leading-relaxed text-pink3">
        {kpi.better === 'lower' ? 'Lower is better' : 'Higher is better'}; rows sorted best first, the best mean in amber. &ldquo;≈ best&rdquo; marks intervals that
        overlap the best rule&rsquo;s interval, so the difference is not resolved at this sample size by an unpaired comparison.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------- litho gantt */
function LithoGantt({ index }: { index: ScenarioIndex | null }) {
  const [id, setId] = useState('optimized');
  const st = useScenario(index ? id : null);
  return (
    <div>
      <div role="radiogroup" aria-label="Scenario" className="mb-4 flex flex-wrap gap-1">
        {index?.scenarios.map((s) => (
          <button
            key={s.id}
            type="button"
            role="radio"
            aria-checked={id === s.id}
            onClick={() => setId(s.id)}
            className={`rounded-sm px-2.5 py-1 text-xs transition-colors ${id === s.id ? 'bg-pink text-paper' : 'text-pink2 hover:bg-paper2 hover:text-pink'}`}
          >
            {s.title}
          </button>
        ))}
      </div>
      {st.model ? (
        <GanttChart m={st.model} />
      ) : (
        <div className="flex h-56 items-center justify-center border border-dashed border-pline text-sm text-pink3">
          {st.error ? `Could not load the replay: ${st.error}` : `Loading replay… ${st.total ? Math.round((st.loaded / st.total) * 100) : 0}%`}
        </div>
      )}
    </div>
  );
}

function GanttChart({ m }: { m: ReplayModel }) {
  const [ref, w] = useWidth<HTMLDivElement>(1200);
  const { t } = useClock();
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const machines = m.lithoMachines;
  const rowH = 30;
  const pad = { l: 86, r: 8, t: 22, b: 8 };
  const h = pad.t + machines.length * rowH + pad.b;
  const x = scaleLinear().domain([m.t0, m.t1]).range([pad.l, w - pad.r]).clamp(true);
  const data = useMemo(
    () =>
      machines.map((mc) => ({
        mc,
        name: m.raw.layout.machines[mc].name,
        ops: m.opsByMachine[mc],
        down: m.intervals(mc, 3),
        pm: m.intervals(mc, 4),
        shares: m.stateShares(mc, m.t0, m.t1),
      })),
    [m, machines],
  );
  const days: number[] = [];
  for (let d = Math.ceil(m.t0 / 24) * 24; d <= m.t1; d += 24) days.push(d);
  return (
    <div ref={ref} className="relative">
      <svg
        width={w}
        height={h}
        className="block"
        role="img"
        aria-label="Gantt chart of the lithography tools over the replay window"
        onMouseLeave={() => setHover(null)}
      >
        {days.map((d) => (
          <g key={d}>
            <line x1={x(d)} x2={x(d)} y1={pad.t - 6} y2={h - pad.b} stroke="var(--p-line)" />
            <text x={x(d) + 3} y={pad.t - 9} fontSize={10} className="num" fill="var(--p-ink-3)">D{d / 24 + 1}</text>
          </g>
        ))}
        {data.map((r, i) => {
          const y = pad.t + i * rowH;
          return (
            <g key={r.mc}>
              <text x={0} y={y + rowH / 2 - 1} fontSize={11} fontWeight={600} fill="var(--p-ink)">{r.name}</text>
              <text x={0} y={y + rowH / 2 + 11} fontSize={9.5} className="num" fill="var(--p-ink-3)">
                {fmt((r.shares[1] + r.shares[2]) * 100, 0)}% busy · {fmt(r.shares[1] * 100, 0)}% setup
              </text>
              <rect x={pad.l} y={y + 4} width={w - pad.l - pad.r} height={rowH - 8} fill="var(--paper-2)" />
              {r.ops.map((op, k) => {
                const ps = op[4] ?? m.t1;
                const end = op[5] ?? m.t1;
                if (end < m.t0) return null;
                const tip = `${r.name} · lot ${op[0]} · step ${op[1] + 1} · reticle ${op[6]}\n${clockStr(op[3])} – ${op[5] !== null ? clockStr(op[5]) : 'running'}${ps > op[3] ? ` · setup ${fmt((ps - op[3]) * 60, 0)} min` : ''}`;
                return (
                  <g
                    key={k}
                    onMouseMove={(e) => {
                      const b = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                      setHover({ x: e.clientX - b.left, y: e.clientY - b.top, text: tip });
                    }}
                  >
                    {ps > op[3] && <rect x={x(op[3])} y={y + 4} width={Math.max(0.8, x(ps) - x(op[3]))} height={rowH - 8} fill="url(#g-hatch)" />}
                    <rect x={x(ps)} y={y + 4} width={Math.max(0.8, x(end) - x(ps) - 0.3)} height={rowH - 8} fill={recipeColor(op[6])} />
                  </g>
                );
              })}
              {r.down.map(([a, b], k) => (
                <rect key={`d${k}`} x={x(a)} y={y + 1} width={Math.max(1, x(b) - x(a))} height={3} fill="var(--bad)" />
              ))}
              {r.pm.map(([a, b], k) => (
                <rect key={`p${k}`} x={x(a)} y={y + 1} width={Math.max(1, x(b) - x(a))} height={3} fill="var(--pm)" />
              ))}
            </g>
          );
        })}
        <line x1={x(t)} x2={x(t)} y1={pad.t - 6} y2={h - pad.b} stroke="var(--p-ink)" strokeWidth={1.25} />
        <defs>
          <pattern id="g-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="4" height="4" fill="#f3d79f" />
            <line x1="0" y1="0" x2="0" y2="4" stroke="var(--amber-deep)" strokeWidth="1.4" />
          </pattern>
        </defs>
      </svg>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 whitespace-pre rounded-sm bg-pink px-2 py-1 text-xs leading-snug text-paper shadow-[0_4px_14px_rgba(0,0,0,.18)]"
          style={{ left: Math.min(hover.x + 12, w - 260), top: hover.y + 14 }}
        >
          {hover.text}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-pink3">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-4" style={{ background: 'repeating-linear-gradient(45deg,#f3d79f 0 2px,var(--amber-deep) 2px 3px)' }} />reticle setup</span>
        <span className="flex items-center gap-1.5"><span className="h-1 w-4 bg-[var(--bad)]" />down (failure)</span>
        <span className="flex items-center gap-1.5"><span className="h-1 w-4 bg-pm" />preventive maintenance</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-px bg-pink" />replay clock</span>
        <button type="button" className="ml-auto underline decoration-pline underline-offset-4 hover:text-pink" onClick={() => document.getElementById('twin')?.scrollIntoView()}>
          Scrub the clock in the twin
        </button>
      </div>
      <span className="sr-only">{`Clock at ${clockStr(clock.t)}`}</span>
    </div>
  );
}

/* --------------------------------------------------------------- tables */
function ciText(v: CI, digits = 2) {
  return (
    <>
      {fmt(v.mean, digits)}
      <span className="text-pink3"> ± {fmt(v.hw, digits)}</span>
    </>
  );
}

function prettyKey(k: string) {
  return k.replace(/_pct$/, ' (%)').replace(/_min$/, ' (min)').replace(/_h$/, ' (h)').replace(/_/g, ' ');
}

function CITable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <Empty section="rows" />;
  const keys = Object.keys(rows[0]);
  const idKeys = keys.filter((k) => !isCI(rows[0][k]));
  const ciKeys = keys.filter((k) => isCI(rows[0][k]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-pink text-xs text-pink3">
            {[...idKeys, ...ciKeys].map((k) => (
              <th key={k} scope="col" className={`py-2 pr-4 font-medium ${ciKeys.includes(k) ? 'text-right' : ''}`}>{prettyKey(k)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-pline">
              {idKeys.map((k) => <td key={k} className="py-2 pr-4 text-pink">{String(r[k])}</td>)}
              {ciKeys.map((k) => <td key={k} className="num py-2 pr-4 text-right text-pink">{ciText(r[k] as CI)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExactTable({ d }: { d: NonNullable<AnalyticsData['exact']> }) {
  const heur = Array.from(new Set(d.rows.flatMap((r) => Object.keys(r.heuristics ?? {}))));
  const v = (x: number | null | undefined, dg = 2) => (x == null ? '—' : fmt(x, dg));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-pink text-xs text-pink3">
            <th scope="col" className="py-2 pr-3 font-medium">Instance</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Lots</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">CP-SAT</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Bound</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">MIP</th>
            {heur.map((h) => <th key={h} scope="col" className="py-2 pr-3 text-right font-medium">{h}</th>)}
            <th scope="col" className="py-2 pr-3 text-right font-medium">ALNS</th>
            <th scope="col" className="py-2 text-right font-medium">ALNS gap</th>
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => {
            const bound = Math.max(r.cpsat_bound ?? -Infinity, r.mip_bound ?? -Infinity);
            const gap = r.alns != null && Number.isFinite(bound) && r.alns > 0 ? ((r.alns - bound) / r.alns) * 100 : null;
            return (
              <tr key={r.instance} className="num border-b border-pline text-pink">
                <td className="py-2 pr-3 font-sans">{r.instance}</td>
                <td className="py-2 pr-3 text-right">{r.lots}</td>
                <td className="py-2 pr-3 text-right" title={`${r.cpsat_status}, ${fmt(r.cpsat_s, 1)} s`}>
                  {v(r.cpsat_obj)}
                  <span className="ml-1 text-2xs text-pink3">{r.cpsat_status === 'OPTIMAL' ? 'opt' : r.cpsat_status.toLowerCase()}</span>
                </td>
                <td className="py-2 pr-3 text-right text-pink2">{v(r.cpsat_bound)}</td>
                <td className="py-2 pr-3 text-right">{v(r.mip_obj)}</td>
                {heur.map((h) => <td key={h} className="py-2 pr-3 text-right">{v(r.heuristics?.[h])}</td>)}
                <td className="py-2 pr-3 text-right">{v(r.alns)}</td>
                <td className="py-2 text-right">{gap == null ? '—' : `${fmt(gap, 1)}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-pink3">ALNS gap = (ALNS − best lower bound) / ALNS, using the stronger of the CP-SAT and MIP bounds.</p>
    </div>
  );
}

function Scaling({ d }: { d: NonNullable<AnalyticsData['scaling']> }) {
  const [ref, w] = useWidth<HTMLDivElement>(600);
  const rows = [...d.rows].sort((a, b) => a.lots - b.lots);
  if (rows.length < 2) return <CITable rows={rows as unknown as Record<string, unknown>[]} />;
  const h = 220;
  const pad = { l: 46, r: 16, t: 12, b: 32 };
  const x = scaleLinear().domain([rows[0].lots, rows[rows.length - 1].lots]).range([pad.l, w - pad.r]);
  const all = rows.flatMap((r) => [r.cpsat_s, r.alns_s]).filter((v) => v > 0);
  const y = scaleLog().domain([Math.min(...all) * 0.8, Math.max(...all) * 1.25]).range([h - pad.b, pad.t]);
  const line = (k: 'cpsat_s' | 'alns_s') => rows.filter((r) => r[k] > 0).map((r, i) => `${i ? 'L' : 'M'}${x(r.lots)},${y(r[k])}`).join('');
  return (
    <div ref={ref}>
      <svg width={w} height={h} className="block" role="img" aria-label="Solver runtime against instance size, log scale">
        {y.ticks(4).map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} stroke="var(--p-line)" strokeDasharray="1 3" />
            <text x={pad.l - 6} y={y(v) + 3} textAnchor="end" fontSize={10} className="num" fill="var(--p-ink-3)">{fmt(v, v < 1 ? 1 : 0)}s</text>
          </g>
        ))}
        {rows.map((r) => (
          <text key={r.lots} x={x(r.lots)} y={h - 12} textAnchor="middle" fontSize={10} className="num" fill="var(--p-ink-3)">{r.lots}</text>
        ))}
        <path d={line('cpsat_s')} fill="none" stroke={CAT[0]} strokeWidth={1.5} />
        <path d={line('alns_s')} fill="none" stroke={CAT[1]} strokeWidth={1.5} />
        <text x={w - pad.r} y={pad.t + 10} textAnchor="end" fontSize={11} fill={CAT[0]}>CP-SAT</text>
        <text x={w - pad.r} y={pad.t + 24} textAnchor="end" fontSize={11} fill={CAT[1]}>ALNS</text>
      </svg>
      <p className="mt-1 text-xs text-pink3">x: lots in the instance; ALNS gap to CP-SAT at the largest size: <span className="num text-pink">{fmt(rows[rows.length - 1].gap_pct, 1)}%</span></p>
    </div>
  );
}

function Pareto({ d }: { d: NonNullable<AnalyticsData['pareto']> }) {
  const [ref, w] = useWidth<HTMLDivElement>(600);
  const h = 260;
  const pad = { l: 52, r: 16, t: 12, b: 40 };
  const pts = d.points;
  const methods = Array.from(new Set(pts.map((p) => p.method)));
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const x = scaleLinear().domain([Math.min(...xs), Math.max(...xs)]).nice().range([pad.l, w - pad.r]);
  const y = scaleLinear().domain([Math.min(...ys), Math.max(...ys)]).nice().range([h - pad.b, pad.t]);
  const front = pts.filter((p) => p.front).sort((a, b) => a.x - b.x);
  return (
    <div ref={ref}>
      <svg width={w} height={h} className="block" role="img" aria-label={`Pareto front: ${d.x} against ${d.y}`}>
        {x.ticks(5).map((v) => <text key={v} x={x(v)} y={h - 22} textAnchor="middle" fontSize={10} className="num" fill="var(--p-ink-3)">{fmt(v, 1)}</text>)}
        {y.ticks(5).map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} stroke="var(--p-line)" strokeDasharray="1 3" />
            <text x={pad.l - 6} y={y(v) + 3} textAnchor="end" fontSize={10} className="num" fill="var(--p-ink-3)">{fmt(v, 1)}</text>
          </g>
        ))}
        <text x={(pad.l + w - pad.r) / 2} y={h - 4} textAnchor="middle" fontSize={11} fill="var(--p-ink-2)">{d.x}</text>
        <path d={front.map((p, i) => `${i ? 'L' : 'M'}${x(p.x)},${y(p.y)}`).join('')} fill="none" stroke="var(--p-ink)" strokeWidth={1} strokeDasharray="3 2" />
        {pts.map((p, i) => {
          const c = CAT[methods.indexOf(p.method) % CAT.length];
          return <circle key={i} cx={x(p.x)} cy={y(p.y)} r={p.front ? 4.5 : 3} fill={p.front ? c : 'var(--paper)'} stroke={c} strokeWidth={1.3}><title>{`${p.method}: ${p.x}, ${p.y}`}</title></circle>;
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-pink3">
        <span>y: {d.y}</span>
        {methods.map((mth, i) => (
          <span key={mth} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: CAT[i % CAT.length] }} />{mth}</span>
        ))}
      </div>
    </div>
  );
}

function Convergence({ d }: { d: NonNullable<AnalyticsData['convergence']> }) {
  const [ref, w] = useWidth<HTMLDivElement>(600);
  const h = 240;
  const pad = { l: 52, r: 16, t: 12, b: 30 };
  const all = d.series.flatMap((s) => [...s.best, ...(s.current ?? [])]);
  const maxIt = Math.max(...d.series.flatMap((s) => s.iter));
  const x = scaleLinear().domain([0, maxIt]).range([pad.l, w - pad.r]);
  const y = scaleLinear().domain([Math.min(...all), Math.max(...all)]).nice().range([h - pad.b, pad.t]);
  const path = (it: number[], v: number[]) => it.map((t, i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)},${y(v[i]).toFixed(1)}`).join('');
  return (
    <div ref={ref}>
      <svg width={w} height={h} className="block" role="img" aria-label="Best objective against iteration">
        {y.ticks(4).map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} stroke="var(--p-line)" strokeDasharray="1 3" />
            <text x={pad.l - 6} y={y(v) + 3} textAnchor="end" fontSize={10} className="num" fill="var(--p-ink-3)">{fmt(v, 1)}</text>
          </g>
        ))}
        {x.ticks(5).map((v) => <text key={v} x={x(v)} y={h - 10} textAnchor="middle" fontSize={10} className="num" fill="var(--p-ink-3)">{v}</text>)}
        {d.series.map((s, i) => (
          <g key={s.name}>
            {s.current && <path d={path(s.iter, s.current)} fill="none" stroke={CAT[i % CAT.length]} strokeWidth={0.8} opacity={0.3} />}
            <path d={path(s.iter, s.best)} fill="none" stroke={CAT[i % CAT.length]} strokeWidth={1.6} />
          </g>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-pink3">
        <span>x: iteration · faint line: current solution</span>
        {d.series.map((s, i) => (
          <span key={s.name} className="flex items-center gap-1.5"><span className="h-px w-4" style={{ background: CAT[i % CAT.length] }} />{s.name}</span>
        ))}
      </div>
    </div>
  );
}
