import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { bytes } from '../lib/format';
import { useNarrow, useReducedMotion, useSeen, webglAvailable } from '../lib/hooks';
import { STATE_HEX, STATE_LABEL, UTIL_STOPS } from '../lib/palette';
import { clock } from '../replay/clock';
import { useScenario, type ScenarioState } from '../replay/load';
import type { ReplayModel } from '../replay/model';
import type { ScenarioIndex } from '../replay/types';
import FloorMap2D from '../scene/FloorMap2D';
import Kpis from './Kpis';
import LotJourney from './LotJourney';
import Timeline from './Timeline';

const FabScene = lazy(() => import('../scene/FabScene'));

export function LoadingState({ st, name }: { st: ScenarioState; name: string }) {
  const frac = st.total ? st.loaded / st.total : 0;
  return (
    <div className="absolute inset-0 grid place-items-center bg-bg">
      <div className="w-72">
        {st.error ? (
          <>
            <div className="label text-red">Replay failed to load</div>
            <p className="mt-2 text-sm text-ink2">{st.error}. Reload the page to retry.</p>
          </>
        ) : (
          <>
            <div className="flex items-baseline justify-between">
              <span className="label text-ink3">Loading replay</span>
              <span className="num text-xs text-ink2">{st.total ? `${bytes(st.loaded)} / ${bytes(st.total)}` : 'connecting'}</span>
            </div>
            <div className="relative mt-2 h-px overflow-hidden bg-line2">
              <div className="absolute inset-y-0 left-0 bg-amber transition-[width] duration-150" style={{ width: `${frac * 100}%` }} />
            </div>
            <div className="num mt-2 text-xs text-ink3">
              {name}
              {frac >= 1 ? ' · indexing events' : ''}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Viewport({
  st, name, label, selectedId, onSelect, heatmap, follow, compact, reduced, accent,
}: {
  st: ScenarioState;
  name: string;
  label?: string;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  heatmap: boolean;
  follow: boolean;
  compact: boolean;
  reduced: boolean;
  accent?: string;
}) {
  const narrow = useNarrow();
  const m = st.model;
  const use3D = !narrow && webglAvailable();
  const idx = m && selectedId !== null ? (m.lotIdx.get(selectedId) ?? null) : null;
  return (
    <div className="relative min-h-0 overflow-hidden">
      {!m && <LoadingState st={st} name={name} />}
      {m && use3D && (
        <Suspense fallback={<div className="absolute inset-0 bg-bg" />}>
          <FabScene
            model={m}
            selectedLot={idx}
            onSelectLot={(i) => onSelect(i === null ? null : m.lots[i].id)}
            heatmap={heatmap}
            follow={follow}
            compact={compact}
            reduced={reduced}
          />
        </Suspense>
      )}
      {m && !use3D && <FloorMap2D model={m} />}
      {label && m && (
        <div className="pointer-events-none absolute inset-x-4 top-3 flex min-w-0 items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: accent }} />
          <span className="wide shrink-0 whitespace-nowrap text-sm font-semibold text-ink">{label}</span>
          <span className="hidden min-w-0 truncate text-xs text-ink3 lg:inline">{m.raw.meta.subtitle}</span>
        </div>
      )}
    </div>
  );
}

function Legend({ heatmap }: { heatmap: boolean }) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-4 hidden max-w-[calc(100%-2rem)] flex-wrap items-center gap-x-5 gap-y-1 rounded-sm bg-bg/80 px-3 py-2 text-2xs text-ink2 backdrop-blur-sm md:flex">
      {heatmap ? (
        <span className="flex items-center gap-2">
          <span className="label text-ink3">Utilisation, trailing 24 h</span>
          <span className="num">0%</span>
          <span
            className="h-1.5 w-28"
            style={{
              background: `linear-gradient(90deg, ${UTIL_STOPS.map(([s, c]) => `rgb(${c.map((x) => Math.round(x * 255)).join(',')}) ${s * 100}%`).join(',')})`,
            }}
          />
          <span className="num">100%</span>
        </span>
      ) : (
        <span className="flex items-center gap-3">
          <span className="label text-ink3">Tool state</span>
          {STATE_LABEL.map((l, i) => (
            <span key={l} className="flex items-center gap-1.5">
              <span className="h-1.5 w-3" style={{ background: STATE_HEX[i] }} />
              {l}
            </span>
          ))}
        </span>
      )}
      <span className="flex items-center gap-3">
        <span className="label text-ink3">FOUP</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 bg-[#9aa7b1]" />lot</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 bg-white" />hot lot</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 bg-red" />Q-time deadline near</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 bg-cyan" />selected</span>
      </span>
    </div>
  );
}

function Toggle({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      className={`flex items-center gap-2 rounded-sm border px-2.5 py-1 text-xs transition-colors ${
        on ? 'border-amber text-amber' : 'border-line2 bg-bg/70 text-ink2 hover:text-ink'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${on ? 'bg-amber' : 'bg-ink3'}`} />
      {children}
    </button>
  );
}

export default function Twin({ index, onModel }: { index: ScenarioIndex | null; onModel: (m: ReplayModel | null) => void }) {
  const reduced = useReducedMotion();
  const ids = index?.scenarios.map((s) => s.id) ?? [];
  const [compare, setCompare] = useState(false);
  const [single, setSingle] = useState('optimized');
  const [aId, setAId] = useState('baseline');
  const [bId, setBId] = useState('optimized');
  const [heatmap, setHeatmap] = useState(false);
  const [follow, setFollow] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const primaryId = index ? (compare ? aId : single) : null;
  const A = useScenario(primaryId);
  const B = useScenario(index && compare ? bId : null);
  const [sectionRef, seen] = useSeen<HTMLElement>();
  const autoplayed = useRef(false);
  const title = (id: string) => index?.scenarios.find((s) => s.id === id)?.title ?? id;
  const file = (id: string) => index?.scenarios.find((s) => s.id === id)?.file ?? '';

  useEffect(() => {
    onModel(A.model);
    if (A.model) clock.setRange(A.model.t0, A.model.t1);
  }, [A.model, onModel]);
  useEffect(() => {
    if (A.model && seen && !reduced && !autoplayed.current) {
      autoplayed.current = true;
      clock.play();
    }
  }, [A.model, seen, reduced]);

  const selIdx = A.model && selectedId !== null ? (A.model.lotIdx.get(selectedId) ?? null) : null;

  return (
    <section id="twin" ref={sectionRef} className="border-y border-line bg-bg" aria-label="Digital twin replay">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-end justify-between gap-x-10 gap-y-4 px-4 pb-5 pt-14 md:px-6">
        <div className="max-w-2xl">
          <h2 className="display text-3xl text-ink md:text-4xl">The twin</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink2">
            Seven days of one simulation run, replayed from the event log. Every tool state, FOUP move and OHT trip is
            reconstructed from the Python engine&rsquo;s trace; nothing is animated for effect. All scenarios share instance{' '}
            <span className="num text-ink">{index?.instance ?? '…'}</span> and seed <span className="num text-ink">{index?.seed ?? '…'}</span>, so
            the same lots meet the same failures.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="hidden md:block">
            <Toggle on={heatmap} onChange={setHeatmap}>Bottleneck heat map</Toggle>
          </div>
          <div role="radiogroup" aria-label="View mode" className="flex rounded-sm border border-line2 p-0.5">
            {(['Single', 'Compare'] as const).map((v) => {
              const on = (v === 'Compare') === compare;
              return (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setCompare(v === 'Compare')}
                  className={`px-3 py-1 text-xs transition-colors ${on ? 'bg-ink text-bg' : 'text-ink2 hover:text-ink'}`}
                >
                  {v === 'Single' ? 'Single run' : 'Compare A / B'}
                </button>
              );
            })}
          </div>
          {!compare ? (
            <div role="radiogroup" aria-label="Scenario" className="flex flex-wrap gap-1">
              {ids.map((id) => (
                <button
                  key={id}
                  type="button"
                  role="radio"
                  aria-checked={single === id}
                  onClick={() => setSingle(id)}
                  title={index?.scenarios.find((s) => s.id === id)?.subtitle}
                  className={`rounded-sm px-2.5 py-1 text-xs transition-colors ${single === id ? 'text-amber shadow-[inset_0_-1px_0_var(--amber)]' : 'text-ink2 hover:text-ink'}`}
                >
                  {title(id)}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs">
              <ScenarioSelect label="A" value={aId} ids={ids} title={title} onChange={setAId} />
              <span className="text-ink3">vs</span>
              <ScenarioSelect label="B" value={bId} ids={ids} title={title} onChange={setBId} />
            </div>
          )}
        </div>
      </div>

      <div className="relative">
        <div className={`grid h-[46vh] min-h-[300px] md:h-[68vh] md:min-h-[420px] max-h-[860px] ${compare ? 'grid-rows-2 gap-px bg-line md:grid-cols-2 md:grid-rows-1' : ''}`}>
          <Viewport
            st={A}
            name={file(primaryId ?? '')}
            label={compare ? `A · ${title(aId)}` : undefined}
            accent="var(--ink-2)"
            selectedId={selectedId}
            onSelect={setSelectedId}
            heatmap={heatmap}
            follow={follow}
            compact={compare}
            reduced={reduced}
          />
          {compare && (
            <Viewport
              st={B}
              name={file(bId)}
              label={`B · ${title(bId)}`}
              accent="var(--cyan)"
              selectedId={selectedId}
              onSelect={setSelectedId}
              heatmap={heatmap}
              follow={follow}
              compact
              reduced={reduced}
            />
          )}
        </div>
        {A.model && (
          <>
            <Legend heatmap={heatmap} />
          </>
        )}
      </div>

      {A.model && (
        <>
          <Timeline model={A.model} />
          <Kpis a={A.model} b={compare ? B.model : null} />
          <LotJourney
            model={A.model}
            selected={selIdx}
            onSelect={(i) => setSelectedId(i === null ? null : A.model!.lots[i].id)}
            follow={follow}
            setFollow={setFollow}
          />
        </>
      )}
    </section>
  );
}

function ScenarioSelect({ label, value, ids, title, onChange }: { label: string; value: string; ids: string[]; title: (id: string) => string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="label text-ink3">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm border border-line2 bg-bg px-2 py-1 text-xs text-ink focus:border-amber focus:outline-none"
      >
        {ids.map((id) => (
          <option key={id} value={id}>
            {title(id)}
          </option>
        ))}
      </select>
    </label>
  );
}
