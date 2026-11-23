import { scaleLinear } from 'd3-scale';
import { useMemo, useState } from 'react';
import { clockStr, fmt, hours } from '../lib/format';
import { useWidth } from '../lib/hooks';
import { IconClose, IconTarget } from '../lib/icons';
import { KIND_HEX, KIND_LABEL } from '../lib/palette';
import { clock, useClock } from '../replay/clock';
import type { ReplayModel } from '../replay/model';
import { LOC } from '../replay/types';

const loc = { kind: -1, id: -1 };

function status(m: ReplayModel, i: number, t: number): string {
  m.locAt(i, t, loc);
  const L = m.raw.layout;
  switch (loc.kind) {
    case -1: return 'Not yet released';
    case LOC.QUEUE: return `Queued · ${m.raw.groups[loc.id].name}`;
    case LOC.MACHINE: return `On ${L.machines[loc.id].name}`;
    case LOC.VEHICLE: return `On OHT vehicle ${loc.id + 1}`;
    case LOC.DONE: return 'Completed';
    case LOC.SCRAP: return 'Scrapped';
    case LOC.PORT: return 'Awaiting pickup';
    case LOC.TRANSIT: return 'In transit';
    default: return '—';
  }
}

/** Route position at t: index of the step being processed or next in line. */
function stepAt(m: ReplayModel, i: number, t: number): number {
  const op = m.opAt(i, t);
  if (!op) return 0;
  const inOp = op[5] === null || op[5] > t;
  return inOp ? op[1] : op[1] + 1;
}

type Filter = 'all' | 'hot' | 'qtime' | 'late';
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'hot', label: 'Hot' },
  { id: 'qtime', label: 'In Q-time' },
  { id: 'late', label: 'Past due' },
];

export default function LotJourney({
  model, selected, onSelect, follow, setFollow,
}: {
  model: ReplayModel;
  selected: number | null;
  onSelect: (i: number | null) => void;
  follow: boolean;
  setFollow: (f: boolean) => void;
}) {
  const snap = useClock();
  const tq = Math.floor(snap.t * 4) / 4; // list refreshes every 15 sim-minutes
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const rows = useMemo(() => {
    return model.lots
      .map((l) => {
        model.locAt(l.idx, tq, loc);
        const inFab = loc.kind !== -1 && loc.kind !== LOC.DONE && loc.kind !== LOC.SCRAP;
        return { l, inFab, q: model.qtimeProgress(l.idx, tq), late: inFab && l.due < tq };
      })
      .filter((r) => r.inFab || r.l.idx === selected)
      .filter((r) => (filter === 'hot' ? r.l.hot : filter === 'qtime' ? r.q >= 0 : filter === 'late' ? r.late : true))
      .filter((r) => !query || String(r.l.id).includes(query.trim()))
      .sort((a, b) => Number(b.l.hot) - Number(a.l.hot) || b.q - a.q || a.l.due - b.l.due);
  }, [model, tq, filter, query, selected]);

  return (
    <div className="grid border-t border-line md:grid-cols-[19rem_minmax(0,1fr)]">
      <div className="border-b border-line md:border-b-0 md:border-r">
        <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-4">
          <h3 className="wide text-sm font-semibold text-ink">Lots in the fab</h3>
          <span className="num text-xs text-ink3">{rows.length}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1 px-4 pb-2" role="radiogroup" aria-label="Filter lots">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              role="radio"
              aria-checked={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-sm px-2 py-0.5 text-xs transition-colors ${filter === f.id ? 'bg-ink text-bg' : 'text-ink2 hover:text-ink'}`}
            >
              {f.label}
            </button>
          ))}
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value.replace(/\D/g, ''))}
            placeholder="Lot #"
            inputMode="numeric"
            aria-label="Search lot number"
            className="num ml-auto w-16 rounded-sm border border-line2 bg-transparent px-1.5 py-0.5 text-xs text-ink placeholder:text-ink3 focus:border-amber focus:outline-none"
          />
        </div>
        <ul className="h-64 overflow-y-auto pb-2 md:h-72" aria-label="Lots">
          {rows.length === 0 && <li className="px-4 py-6 text-xs text-ink3">No lot matches this filter at the current time.</li>}
          {rows.map(({ l, q, late }) => {
            const on = l.idx === selected;
            return (
              <li key={l.id}>
                <button
                  type="button"
                  onClick={() => onSelect(on ? null : l.idx)}
                  aria-pressed={on}
                  className={`flex w-full items-center gap-3 px-4 py-1.5 text-left transition-colors hover:bg-raised ${on ? 'bg-panel' : ''}`}
                >
                  <span className={`num w-12 text-xs ${on ? 'text-cyan' : 'text-ink'}`}>{l.id}</span>
                  <span className="text-2xs text-ink3">{model.raw.products[l.product].name}</span>
                  <span className="min-w-0 flex-1 truncate text-2xs text-ink2">{status(model, l.idx, tq)}</span>
                  {l.hot && <span className="label rounded-sm bg-ink px-1 text-[0.6rem] text-bg">Hot</span>}
                  {q >= 0 && (
                    <span className="num text-2xs" style={{ color: q > 0.5 ? 'var(--red)' : '#ff9f8a' }} title="Q-time window elapsed">
                      Q{Math.round(q * 100)}%
                    </span>
                  )}
                  {late && <span className="label text-[0.6rem] text-red">Late</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      {selected === null ? (
        <div className="flex items-center px-6 py-8">
          <p className="max-w-md text-sm leading-relaxed text-ink2">
            Click a FOUP in the fab or pick a lot from the list to follow it: its re-entrant route, every operation in the
            replay window, its due date and its Q-time windows.
          </p>
        </div>
      ) : (
        <LotDetail model={model} i={selected} t={snap.t} follow={follow} setFollow={setFollow} onClose={() => onSelect(null)} />
      )}
    </div>
  );
}

function LotDetail({
  model, i, t, follow, setFollow, onClose,
}: { model: ReplayModel; i: number; t: number; follow: boolean; setFollow: (f: boolean) => void; onClose: () => void }) {
  const lot = model.lots[i];
  const prod = model.raw.products[lot.product];
  const steps = prod.steps;
  const cur = Math.min(steps.length, stepAt(model, i, t));
  const lithoIdx = useMemo(() => steps.map((s, k) => (model.kindOfGroup[s[0]] === 'litho' ? k : -1)).filter((k) => k >= 0), [steps, model]);
  const lithoDone = lithoIdx.filter((k) => k < cur).length;
  const remaining = steps.slice(cur).reduce((a, s) => a + s[2], 0);
  const finished = lot.done !== null && lot.done <= t;
  const slack = lot.due - t - remaining;
  const qs = model.qByLot[i];
  const viol = qs.filter((q) => q[4] === 1).length;

  return (
    <div className="min-w-0 px-4 pb-5 pt-4 md:px-6">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="display text-2xl text-ink">Lot {lot.id}</h3>
            {lot.hot && <span className="label rounded-sm bg-ink px-1.5 py-0.5 text-bg">Hot lot</span>}
          </div>
          <p className="mt-0.5 text-xs text-ink2">
            {prod.name} · {steps.length} steps · {lithoIdx.length} litho visits · {status(model, i, t)}
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
          <Fact k="Released" v={clockStr(lot.release)} />
          <Fact k="Due" v={clockStr(lot.due)} />
          <Fact k={finished ? 'Completed' : 'Slack now'} v={finished ? clockStr(lot.done!) : hours(slack)} tone={!finished && slack < 0 ? 'bad' : undefined} />
          <Fact k="Q-time windows" v={`${qs.length}${viol ? ` · ${viol} violated` : ''}`} tone={viol ? 'bad' : undefined} />
        </dl>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setFollow(!follow)}
            aria-pressed={follow}
            className={`flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-xs transition-colors ${
              follow ? 'border-cyan text-cyan' : 'border-line2 text-ink2 hover:text-ink'
            }`}
          >
            <IconTarget /> {follow ? 'Following in 3D' : 'Follow in 3D'}
          </button>
          <button type="button" onClick={onClose} className="grid h-7 w-7 place-items-center text-ink3 hover:text-ink" aria-label="Close lot details">
            <IconClose />
          </button>
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-1.5 flex items-baseline justify-between text-2xs text-ink3">
          <span className="label">Route</span>
          <span>
            step <span className="num text-ink">{Math.min(cur + 1, steps.length)}</span> of {steps.length} · litho visit{' '}
            <span className="num text-amber">{Math.min(lithoDone + (cur < steps.length && lithoIdx.includes(cur) ? 1 : 0), lithoIdx.length)}</span> of{' '}
            {lithoIdx.length}
          </span>
        </div>
        <RouteStrip model={model} product={lot.product} cur={cur} />
      </div>

      <div className="mt-5">
        <div className="mb-1.5 flex items-center gap-4 text-2xs text-ink3">
          <span className="label">Operations in the replay window</span>
          <span className="flex items-center gap-1.5"><span className="hatch h-2 w-3 text-amber" />setup</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-3 bg-ink2" />processing</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-3 bg-red/40" />Q-time window</span>
        </div>
        <LotGantt model={model} i={i} t={t} />
      </div>
    </div>
  );
}

function Fact({ k, v, tone }: { k: string; v: string; tone?: 'bad' }) {
  return (
    <div>
      <dt className="label text-ink3">{k}</dt>
      <dd className={`num ${tone === 'bad' ? 'text-red' : 'text-ink'}`}>{v}</dd>
    </div>
  );
}

function RouteStrip({ model, product, cur }: { model: ReplayModel; product: number; cur: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(700);
  const steps = model.raw.products[product].steps;
  const cw = w / steps.length;
  return (
    <div ref={ref}>
      <svg width={w} height={34} className="block" role="img" aria-label="Route of the lot; litho steps are highlighted">
        {steps.map((s, k) => {
          const kind = model.kindOfGroup[s[0]];
          const litho = kind === 'litho';
          const h = litho ? 26 : 14;
          const done = k < cur;
          return (
            <g key={k}>
              <rect
                x={k * cw + 0.5}
                y={30 - h}
                width={Math.max(1, cw - 1.5)}
                height={h}
                fill={KIND_HEX[kind]}
                opacity={done ? 0.95 : k === cur ? 1 : 0.28}
              >
                <title>{`Step ${k + 1}: ${model.raw.groups[s[0]].name} (${KIND_LABEL[kind]}), ${fmt(s[2], 2)} h${s[3] ? ', opens Q-time window' : ''}`}</title>
              </rect>
              {s[3] === 1 && <rect x={k * cw + cw / 2 - 1} y={0} width={2} height={2} fill="var(--red)" />}
            </g>
          );
        })}
        {cur < steps.length && <rect x={cur * cw - 0.5} y={2} width={cw + 0.5} height={31} fill="none" stroke="var(--cyan)" strokeWidth={1.25} />}
      </svg>
    </div>
  );
}

function LotGantt({ model, i, t }: { model: ReplayModel; i: number; t: number }) {
  const [ref, w] = useWidth<HTMLDivElement>(700);
  const x = scaleLinear().domain([model.t0, model.t1]).range([0, w]).clamp(true);
  const ops = model.opsByLot[i];
  const qs = model.qByLot[i];
  const lot = model.lots[i];
  const days: number[] = [];
  for (let d = Math.ceil(model.t0 / 24) * 24; d <= model.t1; d += 24) days.push(d);
  return (
    <div ref={ref}>
      <svg
        width={w}
        height={46}
        className="block cursor-crosshair"
        onClick={(e) => clock.seek(x.invert(e.clientX - e.currentTarget.getBoundingClientRect().left))}
        role="img"
        aria-label="Operations of the lot over the replay window; click to seek"
      >
        {days.map((d) => <line key={d} x1={x(d)} x2={x(d)} y1={0} y2={46} stroke="var(--line)" />)}
        {qs.map((q, k) => (
          <g key={`q${k}`}>
            <rect x={x(q[1])} y={26} width={Math.max(1, x(q[3] ?? model.t1) - x(q[1]))} height={10} fill="var(--red)" opacity={q[4] ? 0.75 : 0.3} />
            <line x1={x(q[2])} x2={x(q[2])} y1={24} y2={38} stroke="var(--red)" strokeWidth={1.5} />
          </g>
        ))}
        {ops.map((op, k) => {
          const kind = model.kindOfGroup[model.raw.layout.machines[op[2]].group];
          const ps = op[4] ?? model.t1;
          const end = op[5] ?? model.t1;
          return (
            <g key={k}>
              {ps > op[3] && <rect x={x(op[3])} y={6} width={Math.max(1, x(ps) - x(op[3]))} height={14} fill="url(#hatch-amber)" />}
              <rect x={x(ps)} y={6} width={Math.max(1.5, x(end) - x(ps))} height={14} fill={KIND_HEX[kind]}>
                <title>{`Step ${op[1] + 1} on ${model.raw.layout.machines[op[2]].name}: ${clockStr(op[3])} – ${op[5] !== null ? clockStr(op[5]) : 'running'}`}</title>
              </rect>
            </g>
          );
        })}
        {lot.due >= model.t0 && lot.due <= model.t1 && (
          <g>
            <line x1={x(lot.due)} x2={x(lot.due)} y1={0} y2={46} stroke="var(--ink)" strokeDasharray="2 2" />
            <text x={x(lot.due) + 3} y={44} fontSize={9} fill="var(--ink-2)">due</text>
          </g>
        )}
        <line x1={x(t)} x2={x(t)} y1={0} y2={46} stroke="var(--amber)" />
        <defs>
          <pattern id="hatch-amber" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="4" height="4" fill="rgba(240,168,48,.25)" />
            <line x1="0" y1="0" x2="0" y2="4" stroke="var(--amber)" strokeWidth="1.5" />
          </pattern>
        </defs>
      </svg>
    </div>
  );
}
