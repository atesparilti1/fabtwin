import type { ReplayModel } from '../replay/model';
import { LOC } from '../replay/types';
import { DIMS, FOUP, RAIL_Y } from './dims';

/** World-space helpers derived once per replay (x is centred on the floor). */
export interface SceneLayout {
  cx: number; // subtract from layout x
  bayOfGroup: number[];
  stocker: [number, number][]; // per group: tower base (world x, z)
  port: [number, number, number][]; // per machine: load-port position (x, y, z)
  tool: [number, number, number][]; // per machine: body centre (x, z) and yaw
  node: [number, number][]; // per rail node (world x, z)
}

const cache = new WeakMap<ReplayModel, SceneLayout>();

export function sceneLayout(m: ReplayModel): SceneLayout {
  const hit = cache.get(m);
  if (hit) return hit;
  const L = m.raw.layout;
  const cx = L.width / 2;
  const node = L.nodes.map(([x, z]) => [x - cx, z] as [number, number]);
  const bayOfGroup: number[] = [];
  L.bays.forEach((b, i) => (bayOfGroup[b.group] = i));
  const stocker = m.raw.groups.map((g) => {
    const b = L.bays[bayOfGroup[g.id]];
    const z = node[b.stocker][1];
    // tower stands between the two legs of the bay loop, next to the stocker node
    return [b.x - cx, z + b.side * 1.4] as [number, number];
  });
  // Tools are placed relative to their load-port node (front face 0.3 m from
  // the rail) so back-to-back tools of neighbouring bays never intersect.
  const front = L.machines.map((mc) => [-Math.cos(mc.rot), Math.sin(mc.rot)] as [number, number]);
  const port = L.machines.map((mc, i) => {
    const [px, pz] = node[mc.port];
    return [px - front[i][0] * 0.12, 0.95, pz - front[i][1] * 0.12] as [number, number, number];
  });
  const tool = L.machines.map((mc, i) => {
    const [px, pz] = node[mc.port];
    const off = 0.3 + DIMS[mc.kind].d / 2;
    return [px - front[i][0] * off, pz - front[i][1] * off, mc.rot] as [number, number, number];
  });
  const s: SceneLayout = { cx, bayOfGroup, stocker, port, tool, node };
  cache.set(m, s);
  return s;
}

/** Queue tower slot -> offset (2 x 2 footprint per level). */
export function towerSlot(k: number, out: [number, number, number]) {
  const level = Math.floor(k / 4);
  const c = k % 4;
  const s = FOUP.w + FOUP.gap;
  out[0] = (c % 2) * s - s / 2;
  out[2] = Math.floor(c / 2) * s - s / 2;
  out[1] = FOUP.h / 2 + level * (FOUP.h + FOUP.gap);
  return out;
}

const tmpV: [number, number] = [0, 0];
const tmpLoc = { kind: -1, id: -1 };

/**
 * World position of a lot at t (ignores queue slot stacking; used by the
 * follow camera). Returns false when the lot is not in the fab.
 */
export function lotAnchor(m: ReplayModel, i: number, t: number, out: [number, number, number]): boolean {
  const S = sceneLayout(m);
  const loc = m.locAt(i, t, tmpLoc);
  switch (loc.kind) {
    case LOC.QUEUE: {
      const [x, z] = S.stocker[loc.id];
      out[0] = x; out[1] = 1; out[2] = z;
      return true;
    }
    case LOC.MACHINE: {
      const p = S.port[loc.id];
      out[0] = p[0]; out[1] = p[1]; out[2] = p[2];
      return true;
    }
    case LOC.VEHICLE: {
      m.vehicleAt(loc.id, t, tmpV);
      out[0] = tmpV[0] - S.cx; out[1] = RAIL_Y - 0.6; out[2] = tmpV[1];
      return true;
    }
    case LOC.PORT: {
      const [x, z] = S.node[loc.id];
      out[0] = x; out[1] = 0.9; out[2] = z;
      return true;
    }
    default:
      return false;
  }
}
