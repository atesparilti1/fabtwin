/** Raw replay file shapes, see web/DATA_FORMAT.md. */
export type ToolKind = 'litho' | 'etch' | 'dep' | 'furnace' | 'implant' | 'cmp' | 'clean' | 'metro';

export interface ScenarioIndexEntry { id: string; title: string; subtitle: string; file: string; bytes: number }
export interface ScenarioIndex { seed: number; instance: string; scenarios: ScenarioIndexEntry[] }

export interface Bay { group: number; name: string; kind: ToolKind; x: number; side: number; stocker: number; len: number; pitch: number }
export interface MachineSpot { id: number; name: string; group: number; kind: ToolKind; x: number; z: number; rot: number; port: number; batch_max: number }
export interface Group { id: number; name: string; kind: ToolKind; batch_max: number; setup_h: number; machines: number[] }
/** [group, recipe, proc_h, has_qtime, layer] */
export type StepRow = [number, number, number, number, number];
export interface Product { id: number; name: string; steps: StepRow[] }

export interface Meta {
  id: string; title: string; subtitle: string; instance: string; seed: number; rule: string;
  transport: string; oht_policy: string | null; n_vehicles: number; pm: unknown;
  t0: number; t1: number; kpis_full_run: Record<string, number>;
}

/** [id, product, hot, release, due, done, scrapped] */
export type LotRow = [number, number, number, number, number, number | null, number | null];
/** [t, machine, state] */
export type MStateRow = [number, number, number];
/** [t, lot, kind, id] */
export type LotLocRow = [number, number, number, number];
/** [lot, open, deadline, close, violated] */
export type QTimeRow = [number, number, number, number | null, number];
/** [lot, step, machine, setup_start, proc_start, end, recipe, batch] */
export type OpRow = [number, number, number, number, number | null, number | null, number, number];
/** [t, type, lot, machine] */
export type EventRow = [number, string, number, number];
export type VehicleLeg = [number, [number, number][]];

export interface Series { t: number[]; wip: number[]; thr: number[]; ct: (number | null)[]; ontime: (number | null)[]; litho: number[] }

export interface ScenarioFile {
  version: number;
  meta: Meta;
  layout: { nodes: [number, number][]; edges: [number, number][]; bays: Bay[]; machines: MachineSpot[]; width: number; depth: number };
  groups: Group[];
  products: Product[];
  lots: LotRow[];
  mstate: MStateRow[];
  lotloc: LotLocRow[];
  qtime: QTimeRow[];
  vehicles: VehicleLeg[][];
  ops: OpRow[];
  events: EventRow[];
  series: Series;
}

export const MSTATE = { IDLE: 0, SETUP: 1, BUSY: 2, DOWN: 3, PM: 4 } as const;
export const LOC = { QUEUE: 0, MACHINE: 1, VEHICLE: 2, DONE: 3, SCRAP: 4, PORT: 5, TRANSIT: 6 } as const;
