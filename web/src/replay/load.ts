import { useEffect, useState } from 'react';
import type { Analytics } from '../panels/analyticsTypes';
import { ReplayModel } from './model';
import type { ScenarioFile, ScenarioIndex } from './types';

const BASE = import.meta.env.BASE_URL + 'data/';

let indexP: Promise<ScenarioIndex> | null = null;
export function loadIndex(): Promise<ScenarioIndex> {
  indexP ??= fetch(BASE + 'index.json').then((r) => {
    if (!r.ok) throw new Error(`index.json: HTTP ${r.status}`);
    return r.json() as Promise<ScenarioIndex>;
  });
  return indexP;
}

let analyticsP: Promise<Analytics> | null = null;
export function loadAnalytics(): Promise<Analytics> {
  analyticsP ??= fetch(BASE + 'analytics.json').then((r) => (r.ok ? (r.json() as Promise<Analytics>) : {}));
  return analyticsP;
}

type Progress = (loaded: number, total: number) => void;
const cache = new Map<string, Promise<ReplayModel>>();
const progressSubs = new Map<string, Set<Progress>>();

/** Streams a scenario file with byte progress, parses it and builds the model once. */
export function loadScenario(id: string, onProgress?: Progress): Promise<ReplayModel> {
  if (onProgress) {
    let s = progressSubs.get(id);
    if (!s) progressSubs.set(id, (s = new Set()));
    s.add(onProgress);
  }
  const hit = cache.get(id);
  if (hit) return hit;
  const p = (async () => {
    const idx = await loadIndex();
    const entry = idx.scenarios.find((s) => s.id === id);
    if (!entry) throw new Error(`unknown scenario ${id}`);
    const res = await fetch(BASE + entry.file);
    if (!res.ok || !res.body) throw new Error(`${entry.file}: HTTP ${res.status}`);
    // content-length may be the compressed size; the index carries the raw size
    const total = entry.bytes;
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let loaded = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      loaded += value.length;
      progressSubs.get(id)?.forEach((f) => f(Math.min(loaded, total), total));
    }
    const buf = new Uint8Array(loaded);
    let o = 0;
    for (const c of chunks) {
      buf.set(c, o);
      o += c.length;
    }
    progressSubs.get(id)?.forEach((f) => f(total, total));
    await new Promise((r) => setTimeout(r, 0)); // let the progress bar paint
    const raw = JSON.parse(new TextDecoder().decode(buf)) as ScenarioFile;
    return new ReplayModel(raw);
  })();
  cache.set(id, p);
  p.catch(() => cache.delete(id));
  return p;
}

export interface ScenarioState {
  model: ReplayModel | null;
  loaded: number;
  total: number;
  error: string | null;
}

export function useScenario(id: string | null): ScenarioState {
  const [st, setSt] = useState<ScenarioState>({ model: null, loaded: 0, total: 0, error: null });
  useEffect(() => {
    if (!id) return;
    let alive = true;
    setSt({ model: null, loaded: 0, total: 0, error: null });
    let lastPaint = 0;
    loadScenario(id, (loaded, total) => {
      const now = performance.now();
      if (!alive || (now - lastPaint < 60 && loaded < total)) return;
      lastPaint = now;
      setSt((s) => (s.model ? s : { ...s, loaded, total }));
    })
      .then((model) => alive && setSt({ model, loaded: 1, total: 1, error: null }))
      .catch((e: unknown) => alive && setSt((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) })));
    return () => {
      alive = false;
    };
  }, [id]);
  return st;
}

export function useAsync<T>(fn: () => Promise<T>): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    fn().then((x) => alive && setV(x)).catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return v;
}
