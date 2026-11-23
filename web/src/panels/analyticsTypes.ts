/** analytics.json; every section is optional until `make bench` has produced it. */
export interface CI {
  mean: number;
  hw: number;
}
export interface KpiDef {
  key: string;
  label: string;
  better: 'lower' | 'higher';
}
export interface PolicyRow {
  policy: string;
  values: Record<string, CI>;
}
export interface Analytics {
  dispatch?: { replications: number; instance: string; kpis: KpiDef[]; rows: PolicyRow[] };
  exact?: {
    rows: {
      instance: string;
      lots: number;
      cpsat_obj: number | null;
      cpsat_bound: number | null;
      cpsat_status: string;
      cpsat_s: number;
      mip_obj: number | null;
      mip_bound: number | null;
      mip_s: number | null;
      heuristics: Record<string, number>;
      alns: number | null;
    }[];
  };
  scaling?: { rows: { lots: number; ops: number; best_rule: number; alns: number; cpsat_obj: number | null; cpsat_bound: number; cpsat_s: number; alns_s: number }[] };
  pareto?: { x: string; y: string; points: { method: string; x: number; y: number; front: boolean }[] };
  convergence?: { series: { name: string; iter: number[]; best: number[]; current?: number[] }[] };
  oht?: { rows: ({ vehicles: number; policy: string } & Record<string, unknown>)[] };
  maintenance?: { rows: ({ policy: string } & Record<string, unknown>)[] };
  headline?: { rows: PolicyRow[]; deltas: { label: string; mean: number; hw: number; unit: string }[] };
}

export function isCI(v: unknown): v is CI {
  return typeof v === 'object' && v !== null && 'mean' in v && 'hw' in v;
}
