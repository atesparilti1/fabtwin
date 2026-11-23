import { lastLEf } from '../lib/search';
import type { EventRow, OpRow, QTimeRow, ScenarioFile, ToolKind } from './types';

export interface LotInfo {
  id: number;
  idx: number;
  product: number;
  hot: boolean;
  release: number;
  due: number;
  done: number | null;
  scrapped: number | null;
}
export interface VehicleTrack {
  legStart: Float64Array;
  legEnd: Float64Array;
  legLot: Int32Array;
  legOff: Int32Array;
  wpT: Float64Array;
  wpN: Int32Array;
}
export interface Loc {
  kind: number;
  id: number;
}

/**
 * Precomputed, immutable lookup structures for one replay. Everything the
 * scene needs at time t is answered by binary search on these arrays; nothing
 * here allocates per frame.
 */
export class ReplayModel {
  readonly raw: ScenarioFile;
  readonly t0: number;
  readonly t1: number;
  readonly lots: LotInfo[];
  readonly lotIdx = new Map<number, number>();
  private mT: Float64Array[] = [];
  private mS: Uint8Array[] = [];
  private mB: Float64Array[] = []; // cumulative busy+setup hours at each change
  private lT: Float64Array[] = [];
  private lK: Uint8Array[] = [];
  private lI: Int32Array[] = [];
  readonly qByLot: QTimeRow[][];
  readonly opsByLot: OpRow[][];
  readonly opsByMachine: OpRow[][];
  readonly vehicles: VehicleTrack[];
  readonly events: EventRow[];
  readonly kindOfGroup: ToolKind[];
  readonly lithoMachines: number[];

  constructor(raw: ScenarioFile) {
    this.raw = raw;
    this.t0 = raw.meta.t0;
    this.t1 = raw.meta.t1;
    this.kindOfGroup = raw.groups.map((g) => g.kind);
    this.lithoMachines = raw.layout.machines.filter((m) => m.kind === 'litho').map((m) => m.id);

    // machines
    const nM = raw.layout.machines.length;
    const mt: number[][] = Array.from({ length: nM }, () => []);
    const ms: number[][] = Array.from({ length: nM }, () => []);
    for (const [t, m, s] of raw.mstate) {
      mt[m].push(t);
      ms[m].push(s);
    }
    for (let m = 0; m < nM; m++) {
      const T = Float64Array.from(mt[m]);
      const S = Uint8Array.from(ms[m]);
      const B = new Float64Array(T.length);
      for (let i = 1; i < T.length; i++) {
        B[i] = B[i - 1] + (S[i - 1] === 1 || S[i - 1] === 2 ? T[i] - T[i - 1] : 0);
      }
      this.mT.push(T);
      this.mS.push(S);
      this.mB.push(B);
    }

    // lots
    this.lots = raw.lots.map((r, idx) => {
      this.lotIdx.set(r[0], idx);
      return { id: r[0], idx, product: r[1], hot: r[2] === 1, release: r[3], due: r[4], done: r[5], scrapped: r[6] };
    });
    const nL = this.lots.length;
    const lt: number[][] = Array.from({ length: nL }, () => []);
    const lk: number[][] = Array.from({ length: nL }, () => []);
    const li: number[][] = Array.from({ length: nL }, () => []);
    for (const [t, lot, k, id] of raw.lotloc) {
      const i = this.lotIdx.get(lot);
      if (i === undefined) continue;
      lt[i].push(t);
      lk[i].push(k);
      li[i].push(id);
    }
    for (let i = 0; i < nL; i++) {
      this.lT.push(Float64Array.from(lt[i]));
      this.lK.push(Uint8Array.from(lk[i]));
      this.lI.push(Int32Array.from(li[i]));
    }

    this.qByLot = Array.from({ length: nL }, () => []);
    for (const q of raw.qtime) {
      const i = this.lotIdx.get(q[0]);
      if (i !== undefined) this.qByLot[i].push(q);
    }
    this.opsByLot = Array.from({ length: nL }, () => []);
    this.opsByMachine = Array.from({ length: nM }, () => []);
    for (const op of raw.ops) {
      const i = this.lotIdx.get(op[0]);
      if (i !== undefined) this.opsByLot[i].push(op);
      this.opsByMachine[op[2]].push(op);
    }
    for (const a of this.opsByLot) a.sort((x, y) => x[3] - y[3]);
    for (const a of this.opsByMachine) a.sort((x, y) => x[3] - y[3]);

    // vehicles: flatten legs into typed arrays
    this.vehicles = raw.vehicles.map((legs) => {
      const n = legs.length;
      const legStart = new Float64Array(n);
      const legEnd = new Float64Array(n);
      const legLot = new Int32Array(n);
      const legOff = new Int32Array(n + 1);
      let total = 0;
      for (const [, wp] of legs) total += wp.length;
      const wpT = new Float64Array(total);
      const wpN = new Int32Array(total);
      let o = 0;
      legs.forEach(([lot, wp], k) => {
        legOff[k] = o;
        legLot[k] = lot;
        legStart[k] = wp.length ? wp[0][0] : 0;
        legEnd[k] = wp.length ? wp[wp.length - 1][0] : 0;
        for (const [t, node] of wp) {
          wpT[o] = t;
          wpN[o] = node;
          o++;
        }
      });
      legOff[n] = o;
      return { legStart, legEnd, legLot, legOff, wpT, wpN };
    });

    this.events = [...raw.events].sort((a, b) => a[0] - b[0]);
  }

  stateAt(m: number, t: number): number {
    const i = lastLEf(this.mT[m], t);
    return i < 0 ? (this.mS[m][0] ?? 0) : this.mS[m][i];
  }

  private busyCum(m: number, t: number): number {
    const T = this.mT[m];
    const i = lastLEf(T, t);
    if (i < 0) return 0;
    const s = this.mS[m][i];
    return this.mB[m][i] + (s === 1 || s === 2 ? t - T[i] : 0);
  }

  /** Busy+setup share of machine m over the trailing `win` hours (clipped to t0). */
  utilAt(m: number, t: number, win = 24): number {
    const a = Math.max(this.t0, t - win);
    if (t - a < 1e-3) {
      const s = this.stateAt(m, t);
      return s === 1 || s === 2 ? 1 : 0;
    }
    return (this.busyCum(m, t) - this.busyCum(m, a)) / (t - a);
  }

  /** Time share of each state for machine m over [a, b]. */
  stateShares(m: number, a: number, b: number): number[] {
    const out = [0, 0, 0, 0, 0];
    const T = this.mT[m];
    const S = this.mS[m];
    let i = Math.max(0, lastLEf(T, a));
    for (; i < T.length && T[i] < b; i++) {
      const s0 = Math.max(a, T[i]);
      const s1 = Math.min(b, i + 1 < T.length ? T[i + 1] : b);
      if (s1 > s0) out[S[i]] += s1 - s0;
    }
    const tot = b - a;
    return out.map((x) => x / tot);
  }

  /** Down/PM intervals of machine m (for the litho Gantt). */
  intervals(m: number, state: number): [number, number][] {
    const T = this.mT[m];
    const S = this.mS[m];
    const res: [number, number][] = [];
    for (let i = 0; i < T.length; i++) {
      if (S[i] === state) res.push([T[i], i + 1 < T.length ? T[i + 1] : this.t1]);
    }
    return res;
  }

  /** Lot location at t; kind -1 when the lot is not yet in the fab. */
  locAt(i: number, t: number, out: Loc): Loc {
    const k = lastLEf(this.lT[i], t);
    if (k < 0) {
      out.kind = -1;
      out.id = -1;
    } else {
      out.kind = this.lK[i][k];
      out.id = this.lI[i][k];
    }
    return out;
  }

  /** Time the lot entered its current location (stable queue ordering). */
  locSince(i: number, t: number): number {
    const k = lastLEf(this.lT[i], t);
    return k < 0 ? Infinity : this.lT[i][k];
  }

  /** Progress of the open Q-time window of lot i at t (0 at open, 1 at deadline), or -1. */
  qtimeProgress(i: number, t: number): number {
    const qs = this.qByLot[i];
    for (let k = qs.length - 1; k >= 0; k--) {
      const open = qs[k][1];
      const deadline = qs[k][2];
      const close = qs[k][3];
      if (open <= t && (close === null || t < close)) return (t - open) / Math.max(1e-6, deadline - open);
    }
    return -1;
  }

  /** Vehicle v position at t into out [x, z]; returns the carried lot id (-1 if empty). */
  vehicleAt(v: number, t: number, out: [number, number]): number {
    const V = this.vehicles[v];
    const nodes = this.raw.layout.nodes;
    if (V.legStart.length === 0) return -1;
    const k = lastLEf(V.legStart, t);
    if (k < 0) {
      const p = nodes[V.wpN[0]];
      out[0] = p[0];
      out[1] = p[1];
      return -1;
    }
    const lo = V.legOff[k];
    const hi = V.legOff[k + 1] - 1;
    if (t >= V.legEnd[k]) {
      const p = nodes[V.wpN[hi]];
      out[0] = p[0];
      out[1] = p[1];
      return t === V.legEnd[k] ? V.legLot[k] : -1;
    }
    const j = lastLEf(V.wpT, t, lo, hi);
    const a = nodes[V.wpN[j]];
    const b = nodes[V.wpN[Math.min(hi, j + 1)]];
    const dt = V.wpT[Math.min(hi, j + 1)] - V.wpT[j];
    const f = dt > 0 ? (t - V.wpT[j]) / dt : 1;
    out[0] = a[0] + (b[0] - a[0]) * f;
    out[1] = a[1] + (b[1] - a[1]) * f;
    return V.legLot[k];
  }

  /** Index into the 0.25 h KPI series for time t. */
  seriesIndex(t: number): number {
    const s = this.raw.series.t;
    const i = Math.round((t - s[0]) / 0.25);
    return Math.max(0, Math.min(s.length - 1, i));
  }

  /** The op a lot is in (or last started) at time t. */
  opAt(i: number, t: number): OpRow | null {
    let best: OpRow | null = null;
    for (const op of this.opsByLot[i]) {
      if (op[3] <= t) best = op;
      else break;
    }
    return best;
  }
}
