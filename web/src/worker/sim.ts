/**
 * Simplified TypeScript port of the FabTwin simulator core
 * (fabtwin/sim/engine.py + fabtwin/core/dispatch.py) for in-browser what-if
 * exploration. Same semantics where the scenario file carries the data:
 *   - hot lots first, then the rule score, then queue arrival, then lot id
 *   - batch tools: same-recipe batches, start when >= min batch, a hot lot is
 *     in the batch, the oldest lot waited max_wait, or a Q-time deadline is near
 *   - sequence-dependent setup on recipe change; machine choice avoids setups
 *   - Q-time windows (expiry sends the lot back to re-clean; scrapped after 2)
 *   - overlay metrology rework back to the litho step
 *   - Weibull failures with lognormal repairs, preempt-resume
 *   - fixed transport delay (no OHT)
 * Not ported: OHT vehicles, PM, rolling-horizon planner, machine speed
 * differences and eligibility subsets (not in the replay file), exact RNG
 * streams. Reported results always come from the Python engine.
 */

export type Rule = 'FIFO' | 'SPT' | 'EDD' | 'CR' | 'ATC';
export const RULES: Rule[] = ['FIFO', 'SPT', 'EDD', 'CR', 'ATC'];

export interface SimInput {
  groups: { id: number; kind: string; batch_max: number; setup_h: number; machines: number[] }[];
  products: { id: number; steps: [number, number, number, number, number][] }[];
  nMachines: number;
}
export interface SimParams {
  rule: Rule;
  releasePerDay: number;
  failures: boolean;
  days: number;
  warmupDays: number;
  seed: number;
}
export interface SimResult {
  rule: Rule;
  kpis: {
    throughput_per_day: number;
    mean_ct_days: number;
    on_time_pct: number;
    mean_weighted_tardiness_h: number;
    avg_wip: number;
    litho_util: number;
    qtime_viol_pct: number;
    lots_done: number;
    failures: number;
  };
  wip: [number, number][]; // (day, wip)
  ms: number;
}

// constants mirrored from fabtwin/core/generator.py
const FAILURES: Record<string, [number, number, number, number]> = {
  litho: [200, 2.2, 10, 0.8], etch: [110, 1.8, 4, 0.8], dep: [150, 1.6, 4, 0.8], furnace: [300, 1.5, 8, 0.6],
  implant: [130, 1.6, 5, 0.8], cmp: [120, 1.4, 3, 0.8], clean: [200, 1.3, 2, 0.6], metro: [250, 1.2, 2, 0.6],
};
const PROC_CV: Record<string, number> = { litho: 0.05, etch: 0.1, dep: 0.08, furnace: 0.03, implant: 0.08, cmp: 0.1, clean: 0.1, metro: 0.15 };
const QTIME_H = 4.0;
const REWORK_P = 0.03;
const MIN_BATCH = 3;
const MAX_BATCH_WAIT_H = 2.0;
const QTIME_GUARD_H = 1.0;
const QTIME_MAX_REWORKS = 2;
const FLOW_FACTOR = 2.2;
const HOT_FLOW_FACTOR = 1.6;
const HOT_WEIGHT = 10;
const HOT_SHARE = 0.03;
const TRANSPORT_H = 0.1;
const ATC_K = 2.0;

/* ------------------------------------------------------------------ RNG */
function hash(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619) >>> 0;
  return h;
}
class Rng {
  private a: number;
  constructor(seed: number, source: string, idx: number) {
    this.a = hash(`fabtwin:${seed}:${source}:${idx}`);
  }
  random(): number {
    let t = (this.a = (this.a + 0x6d2b79f5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  expo(rate: number): number {
    return -Math.log(1 - this.random()) / rate;
  }
  normal(): number {
    const u = 1 - this.random(), v = this.random();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }
  weibull(scale: number, shape: number): number {
    return scale * Math.pow(-Math.log(1 - this.random()), 1 / shape);
  }
  lognormFactor(cv: number): number {
    if (cv <= 0) return 1;
    const s2 = Math.log(1 + cv * cv);
    return Math.exp(-0.5 * s2 + Math.sqrt(s2) * this.normal());
  }
}
function gamma(z: number): number {
  // Lanczos approximation (enough for Weibull scale)
  const g = 7;
  const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (z < 0.5) return Math.PI / (Math.sin(Math.PI * z) * gamma(1 - z));
  z -= 1;
  let x = c[0];
  for (let i = 1; i < g + 2; i++) x += c[i] / (z + i);
  const t = z + g + 0.5;
  return Math.sqrt(2 * Math.PI) * Math.pow(t, z + 0.5) * Math.exp(-t) * x;
}

/* ---------------------------------------------------------------- heap */
type Ev = [t: number, seq: number, kind: number, a: number, b: number];
class Heap {
  private h: Ev[] = [];
  get size() { return this.h.length; }
  push(e: Ev) {
    const h = this.h;
    h.push(e);
    let i = h.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (less(h[i], h[p])) { [h[i], h[p]] = [h[p], h[i]]; i = p; } else break;
    }
  }
  pop(): Ev {
    const h = this.h;
    const top = h[0];
    const last = h.pop()!;
    if (h.length) {
      h[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < h.length && less(h[l], h[m])) m = l;
        if (r < h.length && less(h[r], h[m])) m = r;
        if (m === i) break;
        [h[i], h[m]] = [h[m], h[i]];
        i = m;
      }
    }
    return top;
  }
}
const less = (a: Ev, b: Ev) => a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);

const E = { RELEASE: 0, HOT: 1, ARRIVE: 2, SETUP_END: 3, END: 4, FAIL: 5, REPAIR: 6, WAKE: 7, QEXPIRE: 8, SAMPLE: 9 };
const IDLE = 0, SETUP = 1, BUSY = 2, DOWN = 3;

interface Lot {
  id: number; product: number; step: number; release: number; due: number; weight: number; hot: boolean;
  qArrival: number; qDeadline: number | null; qOrigin: number; qToken: number; inTransit: boolean; expired: boolean;
  done: number | null; rng: Rng; qviol: number; scrapped: number | null;
}
interface Mach {
  id: number; group: number; state: number; since: number; lastRecipe: number | null; batch: Lot[]; token: number;
  phaseEnd: number; pendingProc: number; resume: number | null; remaining: number; busyWin: number; rngFail: Rng; rngBatch: Rng; failToken: number;
}

export function simulate(inp: SimInput, p: SimParams): SimResult {
  const start = performance.now();
  const T = p.days * 24;
  const W = Math.min(p.warmupDays * 24, T * 0.9);
  const groups = inp.groups;
  const prods = inp.products.map((pr) => {
    const steps = pr.steps.map((s, i) => {
      const kind = groups[s[0]].kind;
      const prevLitho = i > 0 && groups[pr.steps[i - 1][0]].kind === 'litho';
      return {
        group: s[0], recipe: s[1], proc: s[2], qtime: s[3] === 1 ? QTIME_H : null, kind,
        cv: PROC_CV[kind] ?? 0.1,
        reworkTo: kind === 'metro' && prevLitho ? i - 1 : -1,
      };
    });
    const rem = new Array<number>(steps.length + 1).fill(0);
    for (let i = steps.length - 1; i >= 0; i--) rem[i] = rem[i + 1] + steps[i].proc;
    return { steps, rem, raw: rem[0] };
  });
  const groupOf = new Array<number>(inp.nMachines).fill(0);
  groups.forEach((g) => g.machines.forEach((m) => (groupOf[m] = g.id)));
  const machines: Mach[] = Array.from({ length: inp.nMachines }, (_, id) => ({
    id, group: groupOf[id], state: IDLE, since: 0, lastRecipe: null, batch: [], token: 0, phaseEnd: 0, pendingProc: 0,
    resume: null, remaining: 0, busyWin: 0, rngFail: new Rng(p.seed, 'fail', id), rngBatch: new Rng(p.seed, 'batch', id), failToken: 0,
  }));
  const queues: Lot[][] = groups.map(() => []);
  const nextWake: (number | null)[] = groups.map(() => null);
  const lots: Lot[] = [];
  const heap = new Heap();
  let seq = 0;
  let now = 0;
  const push = (t: number, k: number, a = 0, b = 0) => heap.push([t, ++seq, k, a, b]);
  const rngRel = new Rng(p.seed, 'release', 0);
  const rngHot = new Rng(p.seed, 'hot', 0);
  const relRate = p.releasePerDay / 24;
  const hotRate = relRate * HOT_SHARE;
  const wrr = prods.map(() => 0);
  let wip = 0, wipLast = 0, wipArea = 0;
  let qOpened = 0, qViol = 0, failures = 0;
  const wipSeries: [number, number][] = [];
  const inWin = (t: number) => t >= W && t <= T;
  const overlap = (a: number, b: number) => Math.max(0, Math.min(b, T) - Math.max(a, W));

  const setState = (m: Mach, s: number) => {
    if (m.state === SETUP || m.state === BUSY) m.busyWin += overlap(m.since, now);
    m.since = now;
    m.state = s;
  };
  const wipChange = (d: number) => {
    wipArea += wip * overlap(wipLast, now);
    wipLast = now;
    wip += d;
  };

  const newLot = (product: number, hot: boolean) => {
    const ff = hot ? HOT_FLOW_FACTOR : FLOW_FACTOR;
    const id = lots.length;
    const lot: Lot = {
      id, product, step: 0, release: now, due: now + ff * prods[product].raw, weight: hot ? HOT_WEIGHT : 1, hot,
      qArrival: now, qDeadline: null, qOrigin: -1, qToken: 0, inTransit: false, expired: false, done: null,
      rng: new Rng(p.seed, 'lot', id), qviol: 0, scrapped: null,
    };
    lots.push(lot);
    wipChange(1);
    push(now, E.ARRIVE, id);
  };

  const send = (lot: Lot, step: number) => {
    lot.step = step;
    lot.inTransit = true;
    push(now + TRANSPORT_H, E.ARRIVE, lot.id);
  };

  const score = (lot: Lot, pbar: number): number => {
    const pr = prods[lot.product];
    const st = pr.steps[lot.step];
    switch (p.rule) {
      case 'FIFO': return lot.qArrival;
      case 'SPT': return st.proc;
      case 'EDD': return lot.due;
      case 'CR': return (lot.due - now) / Math.max(pr.rem[lot.step], 1e-9);
      case 'ATC': {
        const slack = Math.max(0, lot.due - pr.rem[lot.step] - now);
        return -(lot.weight / st.proc) * Math.exp(-slack / (ATC_K * Math.max(pbar, 1e-9)));
      }
    }
  };
  const cmp = (pbar: number) => {
    const memo = new Map<Lot, number>();
    const sc = (l: Lot) => {
      let v = memo.get(l);
      if (v === undefined) memo.set(l, (v = score(l, pbar)));
      return v;
    };
    return (a: Lot, b: Lot) => (Number(!a.hot) - Number(!b.hot)) || sc(a) - sc(b) || a.qArrival - b.qArrival || a.id - b.id;
  };

  const startJob = (m: Mach, batch: Lot[], recipe: number) => {
    const g = groups[m.group];
    for (const lot of batch) {
      if (lot.qDeadline !== null) { lot.qDeadline = null; lot.qToken++; }
    }
    const setup = m.lastRecipe !== null && m.lastRecipe !== recipe ? g.setup_h : 0;
    m.lastRecipe = recipe;
    const steps = batch.map((l) => prods[l.product].steps[l.step]);
    let base: number, noise: number;
    if (g.batch_max > 1) {
      base = Math.max(...steps.map((s) => s.proc));
      noise = m.rngBatch.lognormFactor(steps[0].cv);
    } else {
      base = steps[0].proc;
      noise = batch[0].rng.lognormFactor(steps[0].cv);
    }
    m.pendingProc = base * noise;
    m.batch = batch;
    m.token++;
    if (setup > 0) {
      setState(m, SETUP);
      m.phaseEnd = now + setup;
      push(m.phaseEnd, E.SETUP_END, m.id, m.token);
    } else beginProc(m);
  };
  const beginProc = (m: Mach) => {
    setState(m, BUSY);
    m.phaseEnd = now + m.pendingProc;
    push(m.phaseEnd, E.END, m.id, m.token);
  };

  const scheduleWake = (g: number, t: number) => {
    const nw = nextWake[g];
    if (nw === null || t < nw - 1e-9) {
      nextWake[g] = t;
      push(t, E.WAKE, g);
    }
  };

  const dispatch = (gi: number) => {
    const q = queues[gi];
    if (!q.length) return;
    const g = groups[gi];
    const idle = g.machines.map((id) => machines[id]).filter((m) => m.state === IDLE);
    if (!idle.length) return;
    const pbar = q.reduce((a, l) => a + prods[l.product].steps[l.step].proc, 0) / q.length;
    const order = cmp(pbar);
    if (g.batch_max > 1) {
      for (const m of idle) {
        if (!q.length) break;
        const byRecipe = new Map<number, Lot[]>();
        for (const l of q) {
          const r = prods[l.product].steps[l.step].recipe;
          const a = byRecipe.get(r);
          if (a) a.push(l); else byRecipe.set(r, [l]);
        }
        let best: { lead: Lot; size: number; recipe: number; batch: Lot[] } | null = null;
        let wake = Infinity;
        for (const [r, cs] of byRecipe) {
          cs.sort(order);
          const batch = cs.slice(0, g.batch_max);
          const oldest = Math.min(...cs.map((c) => c.qArrival));
          const qdl = Math.min(...cs.map((c) => c.qDeadline ?? Infinity));
          const ready = batch.length >= MIN_BATCH || batch.some((c) => c.hot) || now - oldest >= MAX_BATCH_WAIT_H - 1e-9 || qdl - now <= QTIME_GUARD_H + 1e-9;
          if (ready) {
            if (!best || order(batch[0], best.lead) < 0 || (batch[0] === best.lead && batch.length > best.size)) best = { lead: batch[0], size: batch.length, recipe: r, batch };
          } else wake = Math.min(wake, oldest + MAX_BATCH_WAIT_H, qdl - QTIME_GUARD_H);
        }
        if (!best) {
          if (wake < Infinity) scheduleWake(gi, Math.max(wake, now));
          continue;
        }
        for (const l of best.batch) q.splice(q.indexOf(l), 1);
        startJob(m, best.batch, best.recipe);
      }
      return;
    }
    idle.sort((a, b) => a.id - b.id);
    const cands = [...q].sort(order);
    for (const lot of cands) {
      if (!idle.length) break;
      const st = prods[lot.product].steps[lot.step];
      let mi = idle.findIndex((m) => m.lastRecipe === st.recipe);
      if (mi < 0) mi = 0;
      const m = idle.splice(mi, 1)[0];
      q.splice(q.indexOf(lot), 1);
      startJob(m, [lot], st.recipe);
    }
  };

  const complete = (lot: Lot) => {
    const pr = prods[lot.product];
    const k = lot.step;
    const s = pr.steps[k];
    let nxt = k + 1;
    if (s.reworkTo >= 0) {
      const u = lot.rng.random();
      if (u < REWORK_P) nxt = s.reworkTo;
    }
    if (nxt === pr.steps.length) {
      lot.done = now;
      wipChange(-1);
      return;
    }
    if (s.qtime !== null && nxt === k + 1) {
      lot.qDeadline = now + s.qtime;
      lot.qOrigin = k;
      lot.qToken++;
      if (inWin(now)) qOpened++;
      push(lot.qDeadline, E.QEXPIRE, lot.id, lot.qToken);
    }
    send(lot, nxt);
  };

  const failModel = (m: Mach) => FAILURES[groups[m.group].kind];
  const armFailure = (m: Mach) => {
    if (!p.failures) return;
    const f = failModel(m);
    if (!f) return;
    const [mtbf, shape] = f;
    m.failToken++;
    push(now + m.rngFail.weibull(mtbf / gamma(1 + 1 / shape), shape), E.FAIL, m.id, m.failToken);
  };

  // ------------------------------------------------------------- run
  push(0, E.RELEASE);
  if (hotRate > 0) push(rngHot.expo(hotRate), E.HOT);
  machines.forEach(armFailure);
  push(0, E.SAMPLE);

  while (heap.size) {
    const [t, , kind, a, b] = heap.pop();
    if (t > T) break;
    now = t;
    switch (kind) {
      case E.RELEASE: {
        for (let i = 0; i < wrr.length; i++) wrr[i] += 1 / wrr.length;
        let pi = 0;
        for (let i = 1; i < wrr.length; i++) if (wrr[i] > wrr[pi]) pi = i;
        wrr[pi] -= 1;
        newLot(pi, false);
        push(now + rngRel.expo(relRate), E.RELEASE);
        break;
      }
      case E.HOT: {
        newLot(Math.min(prods.length - 1, Math.floor(rngHot.random() * prods.length)), true);
        push(now + rngHot.expo(hotRate), E.HOT);
        break;
      }
      case E.ARRIVE: {
        const lot = lots[a];
        if (lot.scrapped !== null) break;
        lot.inTransit = false;
        if (lot.expired) {
          lot.expired = false;
          send(lot, lot.qOrigin);
          break;
        }
        lot.qArrival = now;
        const g = prods[lot.product].steps[lot.step].group;
        queues[g].push(lot);
        dispatch(g);
        break;
      }
      case E.SETUP_END: {
        const m = machines[a];
        if (b === m.token && m.state === SETUP) beginProc(m);
        break;
      }
      case E.END: {
        const m = machines[a];
        if (b !== m.token || m.state !== BUSY) break;
        const batch = m.batch;
        m.batch = [];
        setState(m, IDLE);
        for (const lot of batch) complete(lot);
        dispatch(m.group);
        break;
      }
      case E.FAIL: {
        const m = machines[a];
        if (b !== m.failToken || m.state === DOWN) break;
        if (m.state === SETUP || m.state === BUSY) {
          m.resume = m.state;
          m.remaining = m.phaseEnd - now;
          m.token++;
        } else m.resume = null;
        setState(m, DOWN);
        if (inWin(now)) failures++;
        const [, , mttr, rcv] = failModel(m);
        push(now + mttr * m.rngFail.lognormFactor(rcv), E.REPAIR, m.id);
        break;
      }
      case E.REPAIR: {
        const m = machines[a];
        if (m.resume !== null) {
          const ph = m.resume;
          m.resume = null;
          m.token++;
          setState(m, ph);
          m.phaseEnd = now + m.remaining;
          push(m.phaseEnd, ph === SETUP ? E.SETUP_END : E.END, m.id, m.token);
        } else {
          setState(m, IDLE);
          dispatch(m.group);
        }
        armFailure(m);
        break;
      }
      case E.WAKE: {
        const nw = nextWake[a];
        if (nw !== null && Math.abs(nw - now) < 1e-9) {
          nextWake[a] = null;
          dispatch(a);
        }
        break;
      }
      case E.QEXPIRE: {
        const lot = lots[a];
        if (b !== lot.qToken || lot.qDeadline === null) break;
        lot.qDeadline = null;
        lot.qviol++;
        if (inWin(now)) qViol++;
        const g = prods[lot.product].steps[lot.step].group;
        if (lot.qviol > QTIME_MAX_REWORKS) {
          lot.scrapped = now;
          lot.qToken++;
          if (!lot.inTransit) queues[g].splice(queues[g].indexOf(lot), 1);
          wipChange(-1);
          break;
        }
        if (lot.inTransit) {
          lot.expired = true;
          break;
        }
        queues[g].splice(queues[g].indexOf(lot), 1);
        send(lot, lot.qOrigin);
        break;
      }
      case E.SAMPLE: {
        wipSeries.push([now / 24, wip]);
        push(now + 1, E.SAMPLE);
        break;
      }
    }
  }
  now = T;
  wipChange(0);
  for (const m of machines) setState(m, m.state);

  const done = lots.filter((l) => l.done !== null && l.done >= W && l.done <= T);
  const n = done.length;
  const span = T - W;
  const ct = done.map((l) => l.done! - l.release);
  const tard = done.map((l) => Math.max(0, l.done! - l.due));
  const lithoIds = groups.filter((g) => g.kind === 'litho').flatMap((g) => g.machines);
  return {
    rule: p.rule,
    kpis: {
      throughput_per_day: (n / span) * 24,
      mean_ct_days: n ? ct.reduce((a, b) => a + b, 0) / n / 24 : NaN,
      on_time_pct: n ? (100 * tard.filter((x) => x <= 0).length) / n : NaN,
      mean_weighted_tardiness_h: n ? done.reduce((a, l, i) => a + l.weight * tard[i], 0) / n : NaN,
      avg_wip: wipArea / span,
      litho_util: lithoIds.reduce((a, id) => a + machines[id].busyWin, 0) / (lithoIds.length * span),
      qtime_viol_pct: qOpened ? (100 * qViol) / qOpened : 0,
      lots_done: n,
      failures,
    },
    wip: wipSeries,
    ms: performance.now() - start,
  };
}
