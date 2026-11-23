import { STATE_HEX } from '../lib/palette';
import { useClock } from '../replay/clock';
import type { ReplayModel } from '../replay/model';
import { LOC } from '../replay/types';
import { DIMS } from './dims';
import { sceneLayout } from './layout';

const loc = { kind: -1, id: -1 };
const v: [number, number] = [0, 0];

/** Top-down 2D fallback for small screens and browsers without WebGL. */
export default function FloorMap2D({ model }: { model: ReplayModel }) {
  const { t } = useClock();
  const L = model.raw.layout;
  const S = sceneLayout(model);
  const q = new Array<number>(model.raw.groups.length).fill(0);
  for (let i = 0; i < model.lots.length; i++) {
    model.locAt(i, t, loc);
    if (loc.kind === LOC.QUEUE) q[loc.id]++;
  }
  const pad = 2;
  const vb = `${-L.width / 2 - pad} ${-L.depth / 2 - pad} ${L.width + 2 * pad} ${L.depth + 2 * pad}`;
  return (
    <svg viewBox={vb} className="absolute inset-0 h-full w-full" role="img" aria-label="Top-down map of the fab, tools coloured by state">
      <rect x={-L.width / 2 - pad} y={-L.depth / 2 - pad} width={L.width + 2 * pad} height={L.depth + 2 * pad} fill="#0f1316" />
      {L.bays.map((b) => {
        const z0 = b.side * 2.5, z1 = b.side * (2 + b.len + 0.6);
        return (
          <g key={b.group}>
            <rect x={b.x - S.cx - b.pitch / 2 + 0.25} y={Math.min(z0, z1)} width={b.pitch - 0.5} height={Math.abs(z1 - z0)} fill={b.kind === 'litho' ? '#2a2316' : '#161c21'} />
            {/* queue length bar at the stocker */}
            <rect x={S.stocker[b.group][0] - 0.4} y={b.side > 0 ? S.stocker[b.group][1] : S.stocker[b.group][1] - Math.min(8, q[b.group] * 0.35)} width={0.8} height={Math.min(8, q[b.group] * 0.35)} fill="#a2adb5" />
          </g>
        );
      })}
      {L.edges.map(([a, b], k) => (
        <line key={k} x1={S.node[a][0]} y1={S.node[a][1]} x2={S.node[b][0]} y2={S.node[b][1]} stroke="#4a5761" strokeWidth={0.15} />
      ))}
      {L.machines.map((mc) => {
        const { w, d } = DIMS[mc.kind];
        const [x, z, rot] = S.tool[mc.id];
        return (
          <rect
            key={mc.id}
            x={-d / 2}
            y={-w / 2}
            width={d}
            height={w}
            transform={`translate(${x} ${z}) rotate(${(-rot * 180) / Math.PI})`}
            fill={STATE_HEX[model.stateAt(mc.id, t)]}
            opacity={0.9}
          />
        );
      })}
      {model.vehicles.map((_, k) => {
        const lot = model.vehicleAt(k, t, v);
        return <rect key={k} x={v[0] - S.cx - 0.5} y={v[1] - 0.3} width={1} height={0.6} fill={lot >= 0 ? '#35d0c0' : '#dfe4e6'} />;
      })}
    </svg>
  );
}
