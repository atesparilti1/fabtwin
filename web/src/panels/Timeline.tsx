import { useMemo } from 'react';
import { clock as fmtClock } from '../lib/format';
import { IconNext, IconPause, IconPlay, IconPrev } from '../lib/icons';
import { clock, SPEEDS, useClock } from '../replay/clock';
import type { ReplayModel } from '../replay/model';

export const EVENT_TYPES = [
  { type: 'fail', label: 'Failure', color: 'var(--red)' },
  { type: 'qviol', label: 'Q-time violation', color: '#ff8f6b' },
  { type: 'hot', label: 'Hot-lot release', color: '#ffffff' },
  { type: 'pm', label: 'Preventive maint.', color: 'var(--pm)' },
] as const;

function jump(model: ReplayModel, type: string, dir: 1 | -1) {
  const ev = model.events;
  const t = clock.t;
  if (dir > 0) {
    const e = ev.find((x) => x[1] === type && x[0] > t + 1e-4);
    if (e) clock.seek(e[0]);
  } else {
    for (let i = ev.length - 1; i >= 0; i--) {
      if (ev[i][1] === type && ev[i][0] < t - 1e-3) {
        clock.seek(ev[i][0]);
        return;
      }
    }
  }
}

export default function Timeline({ model }: { model: ReplayModel }) {
  const snap = useClock();
  const { t0, t1 } = model;
  const span = t1 - t0;
  const c = fmtClock(snap.t);
  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const e of model.events) m[e[1]] = (m[e[1]] ?? 0) + 1;
    return m;
  }, [model]);
  const days = useMemo(() => {
    const a: number[] = [];
    for (let d = Math.ceil(t0 / 24) * 24; d <= t1; d += 24) a.push(d);
    return a;
  }, [t0, t1]);
  const ticks = useMemo(
    () => model.events.filter((e) => EVENT_TYPES.some((x) => x.type === e[1])),
    [model],
  );

  return (
    <div className="border-t border-line bg-raised/95 px-4 pb-3 pt-2 md:px-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <button
          type="button"
          onClick={() => clock.toggle()}
          className="grid h-10 w-10 place-items-center rounded-full border border-line2 text-ink transition-colors hover:border-amber hover:text-amber"
          aria-label={snap.playing ? 'Pause replay (space)' : 'Play replay (space)'}
        >
          {snap.playing ? <IconPause /> : <IconPlay />}
        </button>
        <div className="min-w-[9.5rem]" aria-live="off">
          <div className="label text-ink3">Sim clock</div>
          <div className="num text-xl leading-6 text-ink">
            Day {c.day} <span className="text-amber">{c.hhmm}</span>
          </div>
        </div>
        <div role="radiogroup" aria-label="Replay speed" className="flex items-center gap-1">
          <span className="label mr-2 text-ink3">Speed</span>
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={snap.speed === s}
              onClick={() => clock.setSpeed(s)}
              className={`num rounded-sm px-2 py-1 text-xs transition-colors ${
                snap.speed === s ? 'bg-ink text-bg' : 'text-ink2 hover:text-ink'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="label text-ink3">Jump to</span>
          {EVENT_TYPES.map((e) => {
            const n = counts[e.type] ?? 0;
            return (
              <div key={e.type} className={`flex items-center gap-1 ${n ? '' : 'opacity-40'}`}>
                <button
                  type="button"
                  disabled={!n}
                  onClick={() => jump(model, e.type, -1)}
                  className="grid h-6 w-5 place-items-center text-ink2 hover:text-ink disabled:cursor-not-allowed"
                  aria-label={`Previous ${e.label}`}
                >
                  <IconPrev />
                </button>
                <span className="flex items-center gap-1.5 text-xs text-ink2">
                  <span className="h-2 w-2 rounded-full" style={{ background: e.color }} />
                  {e.label}
                  <span className="num text-ink3">{n}</span>
                </span>
                <button
                  type="button"
                  disabled={!n}
                  onClick={() => jump(model, e.type, 1)}
                  className="grid h-6 w-5 place-items-center text-ink2 hover:text-ink disabled:cursor-not-allowed"
                  aria-label={`Next ${e.label}`}
                >
                  <IconNext />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      <div className="relative mt-1">
        <svg className="pointer-events-none absolute inset-x-0 top-0 h-7 w-full" preserveAspectRatio="none" viewBox={`0 0 1000 28`} aria-hidden>
          {days.map((d) => (
            <line key={d} x1={((d - t0) / span) * 1000} x2={((d - t0) / span) * 1000} y1={4} y2={24} stroke="var(--line-2)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          ))}
          {ticks.map((e, i) => {
            const col = EVENT_TYPES.find((x) => x.type === e[1])?.color ?? '#fff';
            const x = ((e[0] - t0) / span) * 1000;
            return <line key={i} x1={x} x2={x} y1={e[1] === 'fail' ? 2 : 6} y2={e[1] === 'fail' ? 9 : 11} stroke={col} strokeWidth={1.5} vectorEffect="non-scaling-stroke" opacity={0.85} />;
          })}
        </svg>
        <input
          type="range"
          className="track relative"
          min={t0}
          max={t1}
          step={0.05}
          value={snap.t}
          onChange={(e) => clock.seek(parseFloat(e.target.value))}
          aria-label="Replay time"
          aria-valuetext={`Day ${c.day} ${c.hhmm}`}
        />
        <div className="relative h-4">
          {days.map((d) => (
            <span
              key={d}
              className="num absolute text-2xs text-ink3"
              style={{ left: `${((d - t0) / span) * 100}%`, transform: `translateX(${d - t0 < 1 ? 0 : t1 - d < 1 ? -100 : -50}%)` }}
            >
              D{d / 24 + 1}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
