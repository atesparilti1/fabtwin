import { useMemo, useState } from 'react';
import { fmt } from '../lib/format';
import { useWidth } from '../lib/hooks';
import { IconArrow } from '../lib/icons';
import { KIND_LABEL } from '../lib/palette';
import type { ReplayModel } from '../replay/model';
import type { ScenarioIndex, ToolKind } from '../replay/types';

const ROW_ORDER: ToolKind[] = ['clean', 'furnace', 'dep', 'litho', 'metro', 'etch', 'implant', 'cmp'];

export default function Landing({ model, index }: { model: ReplayModel | null; index: ScenarioIndex | null }) {
  const facts = useMemo(() => {
    if (!model) return null;
    const r = model.raw;
    const q = r.qtime[0];
    const furnace = r.groups.find((g) => g.kind === 'furnace');
    const litho = r.groups.find((g) => g.kind === 'litho');
    const visits = r.products.map((p) => p.steps.filter((s) => r.groups[s[0]].kind === 'litho').length);
    return {
      groups: r.groups.length,
      tools: r.layout.machines.length,
      products: r.products.length,
      vehicles: r.meta.n_vehicles,
      nodes: r.layout.nodes.length,
      edges: r.layout.edges.length,
      steps: r.products.map((p) => p.steps.length),
      visits,
      qtime: q ? q[2] - q[1] : null,
      batch: furnace?.batch_max ?? null,
      setup: litho?.setup_h ?? null,
      dayA: Math.floor(model.t0 / 24) + 1,
      dayB: Math.floor(model.t1 / 24),
    };
  }, [model]);

  return (
    <section className="paper" aria-labelledby="landing-title">
      <div className="mx-auto max-w-[1600px] px-4 pb-16 pt-14 md:px-6 md:pt-20">
        <div className="grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
          <div>
            <h1 id="landing-title" className="display max-w-[14ch] text-[2.6rem] leading-[1.02] text-pink sm:text-6xl xl:text-[4.6rem]">
              Wafers come back to the scanner, layer after layer.
            </h1>
          </div>
          <div className="max-w-[62ch] self-end text-[1.0625rem] leading-relaxed text-pink2">
            <p>
              FabTwin models a semiconductor fab as a <strong className="font-semibold text-pink">re-entrant flexible job shop</strong>. Each lot,
              one FOUP of 25 wafers, returns to the same lithography tools once per mask layer, so a dispatching decision at the
              scanner today shapes the queue in front of it tomorrow.
            </p>
            <p className="mt-4">
              Furnaces <strong className="font-semibold text-pink">batch</strong> lots that share a recipe, scanners lose time on every
              reticle change, an <strong className="font-semibold text-pink">overhead hoist transport</strong> fleet carries every FOUP
              between bays, and tools <strong className="font-semibold text-pink">fail at random</strong>. The question is which
              dispatching, transport and maintenance policies hold cycle time and due dates under that uncertainty.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
              <a href="#twin" className="group inline-flex items-center gap-2 rounded-sm bg-pink px-4 py-2.5 font-medium text-paper transition-colors hover:bg-[#2a3238]">
                Open the twin <IconArrow className="transition-transform group-hover:translate-x-0.5" />
              </a>
              <a href="#analytics" className="text-pink2 underline decoration-pline underline-offset-4 hover:text-pink hover:decoration-pink">
                Benchmark results
              </a>
              <a href="#method" className="text-pink2 underline decoration-pline underline-offset-4 hover:text-pink hover:decoration-pink">
                Method and assumptions
              </a>
            </div>
          </div>
        </div>

        <RouteRibbon model={model} />

        <dl className="mt-10 grid grid-cols-2 gap-x-8 gap-y-6 border-t border-pline pt-6 sm:grid-cols-3 lg:grid-cols-5">
          <Def term="Re-entrant flow">
            {facts ? (
              <>Products run <N>{facts.steps.join(' / ')}</N> steps with <N>{facts.visits.join(' / ')}</N> visits to lithography.</>
            ) : '…'}
          </Def>
          <Def term="Batching">
            {facts?.batch ? <>Furnaces load up to <N>{facts.batch}</N> lots of one recipe; the engine waits for a minimum batch or a timeout.</> : '…'}
          </Def>
          <Def term="Setups">
            {facts?.setup ? <>A reticle change costs <N>{fmt(facts.setup * 60, 0)} min</N> of scanner time, so sequencing by recipe pays.</> : '…'}
          </Def>
          <Def term="Q-time">
            {facts?.qtime ? <>After a pre-clean, a lot must start its furnace step within <N>{fmt(facts.qtime, 0)} h</N> or be re-cleaned.</> : '…'}
          </Def>
          <Def term="Uncertainty">
            Lognormal process times, Weibull failures with lognormal repairs, metrology rework and random hot lots.
          </Def>
        </dl>

        <p className="num mt-8 border-t border-pline pt-4 text-xs leading-relaxed text-pink3">
          {facts && index ? (
            <>
              instance {index.instance} · seed {index.seed} · {facts.groups} tool groups · {facts.tools} tools · {facts.products} products ·{' '}
              {facts.vehicles} OHT vehicles · {facts.nodes} rail nodes, {facts.edges} one-way segments · replay day {facts.dayA}–{facts.dayB}
            </>
          ) : (
            'loading instance…'
          )}
        </p>
      </div>
    </section>
  );
}

function N({ children }: { children: React.ReactNode }) {
  return <span className="num text-pink">{children}</span>;
}

function Def({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="wide text-sm font-semibold text-pink">{term}</dt>
      <dd className="mt-1 text-sm leading-snug text-pink2">{children}</dd>
    </div>
  );
}

function RouteRibbon({ model }: { model: ReplayModel | null }) {
  const [ref, w] = useWidth<HTMLDivElement>(1200);
  const [p, setP] = useState(0);
  const rowH = 22;
  const padL = 96;
  const padT = 26;
  const h = padT + ROW_ORDER.length * rowH + 10;
  const geo = useMemo(() => {
    if (!model) return null;
    const prod = model.raw.products[p];
    const steps = prod.steps;
    const dx = (w - padL - 8) / Math.max(1, steps.length - 1);
    const pts = steps.map((s, k) => {
      const kind = model.kindOfGroup[s[0]];
      return { x: padL + k * dx, y: padT + ROW_ORDER.indexOf(kind) * rowH + rowH / 2, kind, s, k };
    });
    const layers: { x0: number; x1: number; layer: number }[] = [];
    steps.forEach((s, k) => {
      const last = layers[layers.length - 1];
      if (!last || last.layer !== s[4]) layers.push({ x0: padL + k * dx - dx / 2, x1: padL + k * dx + dx / 2, layer: s[4] });
      else last.x1 = padL + k * dx + dx / 2;
    });
    const d = pts.map((q, i) => `${i ? 'L' : 'M'}${q.x.toFixed(1)},${q.y.toFixed(1)}`).join('');
    return { prod, pts, layers, d, litho: pts.filter((q) => q.kind === 'litho').length };
  }, [model, p, w]);

  return (
    <figure className="mt-14">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <figcaption className="text-sm text-pink2">
          {geo ? (
            <>
              Route of product <span className="font-semibold text-pink">{geo.prod.name}</span>: <span className="num text-pink">{geo.pts.length}</span> steps across{' '}
              <span className="num text-pink">{geo.layers.length}</span> mask layers. Each pass through the amber row is a visit to the scanners.
            </>
          ) : (
            'Loading routes…'
          )}
        </figcaption>
        {model && (
          <div role="radiogroup" aria-label="Product" className="flex gap-1">
            {model.raw.products.map((pr, i) => (
              <button
                key={pr.id}
                type="button"
                role="radio"
                aria-checked={p === i}
                onClick={() => setP(i)}
                className={`rounded-sm px-2.5 py-1 text-xs transition-colors ${p === i ? 'bg-pink text-paper' : 'text-pink2 hover:text-pink'}`}
              >
                {pr.name}
              </button>
            ))}
          </div>
        )}
      </div>
      <div ref={ref} className="relative overflow-hidden">
        <svg width={w} height={h} className="block" role="img" aria-label="Re-entrant route chart: process steps left to right, tool areas top to bottom">
          {ROW_ORDER.map((k, i) => (
            <g key={k}>
              {k === 'litho' && <rect x={padL - 8} y={padT + i * rowH} width={w - padL + 8} height={rowH} fill="var(--amber)" opacity={0.16} />}
              <line x1={padL - 8} x2={w} y1={padT + i * rowH + rowH / 2} y2={padT + i * rowH + rowH / 2} stroke="var(--p-line)" strokeDasharray="1 3" />
              <text x={0} y={padT + i * rowH + rowH / 2 + 4} fontSize={11} fill={k === 'litho' ? 'var(--amber-deep)' : 'var(--p-ink-3)'} fontWeight={k === 'litho' ? 650 : 450}>
                {KIND_LABEL[k]}
              </text>
            </g>
          ))}
          {geo?.layers.map((L, i) => (
            <g key={L.layer}>
              {i % 2 === 1 && <rect x={L.x0} y={padT - 4} width={L.x1 - L.x0} height={h - padT} fill="var(--p-ink)" opacity={0.035} />}
              <text x={(L.x0 + L.x1) / 2} y={14} textAnchor="middle" fontSize={10} className="num" fill="var(--p-ink-3)">
                L{L.layer + 1}
              </text>
            </g>
          ))}
          {geo && <path d={geo.d} fill="none" stroke="var(--p-ink-2)" strokeWidth={1.1} strokeLinejoin="round" />}
          {geo?.pts.map((q) =>
            q.kind === 'litho' ? (
              <rect key={q.k} x={q.x - 4} y={q.y - 4} width={8} height={8} fill="var(--amber)" stroke="var(--p-ink)" strokeWidth={1}>
                <title>{`Step ${q.k + 1}: ${model!.raw.groups[q.s[0]].name}, recipe ${q.s[1]}`}</title>
              </rect>
            ) : (
              <circle key={q.k} cx={q.x} cy={q.y} r={q.s[3] ? 3.2 : 2.2} fill={q.s[3] ? 'var(--bad)' : 'var(--p-ink)'}>
                <title>{`Step ${q.k + 1}: ${model!.raw.groups[q.s[0]].name}${q.s[3] ? ' (opens a Q-time window)' : ''}`}</title>
              </circle>
            ),
          )}
          {!geo && <rect x={padL} y={padT} width={w - padL} height={ROW_ORDER.length * rowH} fill="var(--paper-2)" opacity={0.6} />}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-pink3">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 border border-pink bg-amber" />litho visit</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[var(--bad)]" />step that opens a Q-time window</span>
      </div>
    </figure>
  );
}
