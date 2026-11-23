import { scaleLinear } from 'd3-scale';
import { useEffect, useMemo, useRef, useState } from 'react';
import { fmt } from '../lib/format';
import { useWidth } from '../lib/hooks';
import type { ReplayModel } from '../replay/model';
import { RULES, type Rule, type SimInput, type SimResult } from '../worker/sim';
import type { WorkerRequest } from '../worker/sim.worker';

const COLS: { key: keyof SimResult['kpis']; label: string; d: number; better?: 'lower' | 'higher' }[] = [
  { key: 'throughput_per_day', label: 'Throughput /day', d: 1, better: 'higher' },
  { key: 'mean_ct_days', label: 'Cycle time (d)', d: 2, better: 'lower' },
  { key: 'on_time_pct', label: 'On-time %', d: 1, better: 'higher' },
  { key: 'mean_weighted_tardiness_h', label: 'W. tardiness (h)', d: 2, better: 'lower' },
  { key: 'avg_wip', label: 'Avg WIP', d: 1, better: 'lower' },
  { key: 'litho_util', label: 'Litho util %', d: 1 },
  { key: 'qtime_viol_pct', label: 'Q-time viol %', d: 2, better: 'lower' },
];
const LINE = ['#e4e9ec', '#f0a830', '#35d0c0', '#8f9dff', '#ff8f6b'];

interface Run {
  key: string;
  res: SimResult;
  label: string;
}

export default function WhatIf({ model }: { model: ReplayModel | null }) {
  const [rule, setRule] = useState<Rule>('ATC');
  const [rate, setRate] = useState(20);
  const [failures, setFailures] = useState(true);
  const [days, setDays] = useState(20);
  const [seed, setSeed] = useState(1);
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const worker = useRef<Worker | null>(null);
  const reqId = useRef(0);
  const warm = Math.round(days * 0.3);

  useEffect(() => () => worker.current?.terminate(), []);

  const input = useMemo<SimInput | null>(
    () =>
      model && {
        groups: model.raw.groups.map((g) => ({ id: g.id, kind: g.kind, batch_max: g.batch_max, setup_h: g.setup_h, machines: g.machines })),
        products: model.raw.products.map((p) => ({ id: p.id, steps: p.steps })),
        nMachines: model.raw.layout.machines.length,
      },
    [model],
  );

  const run = (rules: Rule[]) => {
    if (!input) return;
    worker.current ??= new Worker(new URL('../worker/sim.worker.ts', import.meta.url), { type: 'module' });
    const id = ++reqId.current;
    const params = { releasePerDay: rate, failures, days, warmupDays: warm, seed };
    const tag = `${fmt(rate, 1)}/d · ${failures ? 'failures' : 'no failures'} · ${days} d · seed ${seed}`;
    setBusy(true);
    setErr(null);
    if (rules.length > 1) setRuns([]);
    worker.current.onmessage = (e: MessageEvent<{ id: number; type: string; res?: SimResult; message?: string }>) => {
      if (e.data.id !== reqId.current) return;
      if (e.data.type === 'result' && e.data.res) {
        const res = e.data.res;
        setRuns((r) => [...r.filter((x) => x.key !== `${res.rule}|${tag}`), { key: `${res.rule}|${tag}`, res, label: tag }].slice(-5));
      } else if (e.data.type === 'done') setBusy(false);
      else if (e.data.type === 'error') {
        setErr(e.data.message ?? 'simulation failed');
        setBusy(false);
      }
    };
    const msg: WorkerRequest = { id, input, params, rules };
    worker.current.postMessage(msg);
  };

  const best = useMemo(() => {
    const b: Partial<Record<string, number>> = {};
    for (const c of COLS) {
      if (!c.better || runs.length < 2) continue;
      const vals = runs.map((r) => r.res.kpis[c.key]).filter(Number.isFinite);
      b[c.key] = c.better === 'lower' ? Math.min(...vals) : Math.max(...vals);
    }
    return b;
  }, [runs]);

  return (
    <section id="whatif" className="border-y border-line bg-bg" aria-labelledby="whatif-title">
      <div className="mx-auto max-w-[1600px] px-4 pb-16 pt-14 md:px-6">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <h2 id="whatif-title" className="display text-3xl text-ink md:text-4xl">What if</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink2">
              Change the release rate or the dispatching rule and simulate the same fab in your browser. Runs share random streams per lot and per
              tool, so rules are compared on the same arrivals and failures.
            </p>
          </div>
          <p className="max-w-sm border-l border-amber pl-3 text-xs leading-relaxed text-ink2">
            <span className="font-semibold text-amber">Simplified TypeScript port, for exploration.</span> Reported results come from the Python
            engine. Not ported: OHT vehicles, preventive maintenance, tool speed differences.
          </p>
        </div>

        <div className="mt-10 grid gap-10 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <form
            className="space-y-6"
            onSubmit={(e) => {
              e.preventDefault();
              run([rule]);
            }}
          >
            <fieldset>
              <legend className="label mb-2 text-ink3">Dispatching rule</legend>
              <div className="grid grid-cols-5 gap-px border border-line2 bg-line2" role="radiogroup">
                {RULES.map((r) => (
                  <button
                    key={r}
                    type="button"
                    role="radio"
                    aria-checked={rule === r}
                    onClick={() => setRule(r)}
                    className={`py-1.5 text-xs font-semibold transition-colors ${rule === r ? 'bg-ink text-bg' : 'bg-bg text-ink2 hover:text-ink'}`}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </fieldset>
            <div>
              <label htmlFor="rate" className="flex items-baseline justify-between">
                <span className="label text-ink3">Release rate</span>
                <span className="num text-sm text-ink">{fmt(rate, 1)} lots/day</span>
              </label>
              <input id="rate" type="range" className="track" min={14} max={24} step={0.5} value={rate} onChange={(e) => setRate(parseFloat(e.target.value))} />
              <div className="num flex justify-between text-2xs text-ink3"><span>14</span><span>24</span></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <label className="block">
                <span className="label text-ink3">Horizon</span>
                <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="num mt-1 w-full rounded-sm border border-line2 bg-bg px-2 py-1.5 text-sm text-ink focus:border-amber focus:outline-none">
                  {[10, 20, 40].map((d) => <option key={d} value={d}>{d} days</option>)}
                </select>
              </label>
              <label className="block">
                <span className="label text-ink3">Seed</span>
                <input type="number" min={0} max={9999} value={seed} onChange={(e) => setSeed(Math.max(0, Math.min(9999, Number(e.target.value) || 0)))} className="num mt-1 w-full rounded-sm border border-line2 bg-bg px-2 py-1.5 text-sm text-ink focus:border-amber focus:outline-none" />
              </label>
            </div>
            <label className="flex cursor-pointer items-center gap-3 text-sm text-ink2">
              <input type="checkbox" checked={failures} onChange={(e) => setFailures(e.target.checked)} className="h-4 w-4 accent-[var(--amber)]" />
              Random tool failures
            </label>
            <p className="text-xs text-ink3">The fab starts empty; the first <span className="num text-ink2">{warm}</span> days are discarded as warm-up.</p>
            <div className="flex flex-wrap gap-2">
              <button type="submit" disabled={!input || busy} className="rounded-sm bg-amber px-4 py-2 text-sm font-semibold text-[#141006] transition-opacity hover:opacity-90 disabled:opacity-40">
                {busy ? 'Simulating…' : `Run ${rule}`}
              </button>
              <button type="button" disabled={!input || busy} onClick={() => run(RULES)} className="rounded-sm border border-line2 px-4 py-2 text-sm text-ink2 transition-colors hover:border-ink3 hover:text-ink disabled:opacity-40">
                Run all five
              </button>
            </div>
            {!input && <p className="text-xs text-ink3">Waiting for the replay file, which carries the instance.</p>}
            {err && <p className="text-xs text-red">Simulation failed: {err}</p>}
          </form>

          <div className="min-w-0">
            {runs.length === 0 ? (
              <div className="flex h-full min-h-[14rem] items-center border border-dashed border-line2 px-6">
                <p className="max-w-md text-sm text-ink3">No runs yet. Pick a rule and press Run; results stack here so you can compare up to five runs.</p>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-line2 text-2xs text-ink3">
                        <th scope="col" className="py-2 pr-3 font-medium">Run</th>
                        {COLS.map((c) => <th key={c.key} scope="col" className="py-2 pr-3 text-right font-medium">{c.label}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((r, i) => (
                        <tr key={r.key} className="border-b border-line">
                          <td className="py-2 pr-3">
                            <span className="flex items-center gap-2">
                              <span className="h-px w-4" style={{ background: LINE[i % LINE.length] }} />
                              <span className="font-semibold text-ink">{r.res.rule}</span>
                              <span className="hidden text-2xs text-ink3 xl:inline">{r.label}</span>
                            </span>
                          </td>
                          {COLS.map((c) => {
                            const v = c.key === 'litho_util' ? r.res.kpis[c.key] * 100 : r.res.kpis[c.key];
                            const isBest = best[c.key] !== undefined && r.res.kpis[c.key] === best[c.key];
                            return (
                              <td key={c.key} className={`num py-2 pr-3 text-right ${isBest ? 'text-amber' : 'text-ink'}`}>{fmt(v, c.d)}</td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-2xs text-ink3">
                  Single replication each: differences smaller than run-to-run noise are not meaningful. Amber marks the best value among the runs shown.
                  {` Last run took ${fmt(runs[runs.length - 1].res.ms, 0)} ms.`}
                </p>
                <WipChart runs={runs} warm={warm} />
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function WipChart({ runs, warm }: { runs: Run[]; warm: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(800);
  const h = 200;
  const pad = { l: 40, r: 12, t: 16, b: 26 };
  const maxD = Math.max(...runs.map((r) => r.res.wip[r.res.wip.length - 1]?.[0] ?? 1));
  const maxW = Math.max(...runs.flatMap((r) => r.res.wip.map((p) => p[1])), 1);
  const x = scaleLinear().domain([0, maxD]).range([pad.l, w - pad.r]);
  const y = scaleLinear().domain([0, maxW]).nice(4).range([h - pad.b, pad.t]);
  return (
    <div ref={ref} className="mt-8">
      <div className="label mb-1 text-ink3">WIP (lots) over simulated days</div>
      <svg width={w} height={h} className="block" role="img" aria-label="Work in process over time for each run">
        <rect x={pad.l} y={pad.t} width={x(warm) - pad.l} height={h - pad.b - pad.t} fill="var(--ink)" opacity={0.04} />
        <text x={pad.l + 6} y={pad.t + 12} fontSize={10} fill="var(--ink-3)">warm-up</text>
        {y.ticks(4).map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={pad.l - 6} y={y(v) + 3} textAnchor="end" fontSize={10} className="num" fill="var(--ink-3)">{v}</text>
          </g>
        ))}
        {x.ticks(8).map((v) => <text key={v} x={x(v)} y={h - 8} textAnchor="middle" fontSize={10} className="num" fill="var(--ink-3)">{v}</text>)}
        {runs.map((r, i) => (
          <path key={r.key} d={r.res.wip.map(([d, v], k) => `${k ? 'L' : 'M'}${x(d).toFixed(1)},${y(v).toFixed(1)}`).join('')} fill="none" stroke={LINE[i % LINE.length]} strokeWidth={1.25} />
        ))}
      </svg>
    </div>
  );
}
