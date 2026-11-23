import { Grid, Html, OrbitControls } from '@react-three/drei';
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { STATE_GLOW, STATE_HEX, utilColor } from '../lib/palette';
import { clock } from '../replay/clock';
import type { ReplayModel } from '../replay/model';
import { LOC, type ToolKind } from '../replay/types';
import { DIMS, FOUP, RAIL_Y, toolGeometry } from './geometry';
import { lotAnchor, sceneLayout, towerSlot } from './layout';

export interface SceneProps {
  model: ReplayModel;
  selectedLot: number | null;
  onSelectLot: (idx: number | null) => void;
  heatmap: boolean;
  follow: boolean;
  compact?: boolean;
  reduced: boolean;
}

const dummy = new THREE.Object3D();
const tmpColor = new THREE.Color();
const STATE_COLORS = STATE_HEX.map((h, i) => new THREE.Color(h).multiplyScalar(STATE_GLOW[i]));
const TOOL_BASE = new THREE.Color('#c3cacd');
const rgb: [number, number, number] = [0, 0, 0];

/* ------------------------------------------------------------------ floor */
function Floor({ model, heatmap }: { model: ReplayModel; heatmap: boolean }) {
  const L = model.raw.layout;
  const S = sceneLayout(model);
  const mats = useRef<(THREE.MeshStandardMaterial | null)[]>([]);
  const acc = useRef(0);
  const base = useMemo(
    () => L.bays.map((b) => new THREE.Color(b.kind === 'litho' ? '#2a2316' : '#161c21')),
    [L.bays],
  );
  useFrame((_, dt) => {
    acc.current += dt;
    if (acc.current < 0.15) return;
    acc.current = 0;
    const t = clock.t;
    L.bays.forEach((b, i) => {
      const mat = mats.current[i];
      if (!mat) return;
      if (!heatmap) {
        mat.color.copy(base[i]);
        return;
      }
      const ms = model.raw.groups[b.group].machines;
      let u = 0;
      for (const m of ms) u += model.utilAt(m, t);
      utilColor(u / ms.length, rgb);
      mat.color.setRGB(rgb[0], rgb[1], rgb[2]).multiplyScalar(0.32);
    });
  });
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[0, -0.01, 0]} receiveShadow>
        <planeGeometry args={[L.width + 16, L.depth + 16]} />
        <meshStandardMaterial color="#0f1316" roughness={0.95} />
      </mesh>
      <Grid
        position={[0, 0.002, 0]}
        args={[L.width + 16, L.depth + 16]}
        cellSize={0.6}
        sectionSize={4.8}
        cellThickness={0.5}
        sectionThickness={0.8}
        cellColor="#182026"
        sectionColor="#222c34"
        fadeDistance={160}
        fadeStrength={1}
      />
      {L.bays.map((b, i) => {
        const z0 = b.side * 2.5;
        const z1 = b.side * (2 + b.len + 0.6);
        return (
          <mesh key={b.group} rotation-x={-Math.PI / 2} position={[b.x - S.cx, 0.004, (z0 + z1) / 2]}>
            <planeGeometry args={[b.pitch - 0.5, Math.abs(z1 - z0)]} />
            <meshStandardMaterial
              ref={(m) => (mats.current[i] = m)}
              color={base[i]}
              roughness={0.9}
              transparent
              opacity={0.92}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function BayLabels({ model }: { model: ReplayModel }) {
  const L = model.raw.layout;
  const S = sceneLayout(model);
  return (
    <>
      {L.bays.map((b) => (
        <Html
          key={b.group}
          position={[b.x - S.cx, 0.05, b.side * (2 + b.len + 1.6)]}
          center
          zIndexRange={[10, 0]}
          style={{ pointerEvents: 'none' }}
        >
          <div className={`label whitespace-nowrap ${b.kind === 'litho' ? 'text-amber' : 'text-ink3'}`}>{b.name}</div>
        </Html>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ tools */
function ToolKindMesh({ model, kind, ids, heatmap }: { model: ReplayModel; kind: ToolKind; ids: number[]; heatmap: boolean }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const S = sceneLayout(model);
  const geo = toolGeometry(kind);
  const acc = useRef(1);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    ids.forEach((m, k) => {
      const [x, z, rot] = S.tool[m];
      dummy.position.set(x, 0, z);
      dummy.rotation.set(0, rot, 0);
      dummy.scale.set(1, 1, 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(k, dummy.matrix);
      mesh.setColorAt(k, TOOL_BASE);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
    acc.current = 1;
  }, [ids, S]);
  useFrame((_, dt) => {
    const mesh = ref.current;
    if (!mesh) return;
    acc.current += dt;
    if (acc.current < 0.15) return;
    acc.current = 0;
    const t = clock.t;
    ids.forEach((m, k) => {
      if (heatmap) {
        utilColor(model.utilAt(m, t), rgb);
        tmpColor.setRGB(rgb[0], rgb[1], rgb[2]);
      } else tmpColor.copy(TOOL_BASE);
      mesh.setColorAt(k, tmpColor);
    });
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  return (
    <instancedMesh ref={ref} args={[geo, undefined, ids.length]} castShadow receiveShadow>
      <meshStandardMaterial color="#ffffff" roughness={0.62} metalness={0.05} />
    </instancedMesh>
  );
}

/** Front LED strip + andon light per tool, coloured by machine state. */
function StatusLights({ model }: { model: ReplayModel }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const S = sceneLayout(model);
  const M = model.raw.layout.machines;
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const parent = new THREE.Object3D();
    M.forEach((mc, i) => {
      const { w, d, h } = DIMS[mc.kind];
      const [x, z, rot] = S.tool[mc.id];
      parent.position.set(x, 0, z);
      parent.rotation.set(0, rot, 0);
      parent.updateMatrix();
      // strip on the port-facing front, just under the roofline
      dummy.position.set(-d / 2 - 0.03, Math.min(h - 0.25, 1.45), 0);
      dummy.rotation.set(0, 0, 0);
      dummy.scale.set(0.04, 0.07, w * 0.82);
      dummy.updateMatrix();
      dummy.matrix.premultiply(parent.matrix);
      mesh.setMatrixAt(2 * i, dummy.matrix);
      // andon tower on the roof
      dummy.position.set(-d / 2 + 0.2, h + 0.2, w / 2 - 0.25);
      dummy.scale.set(0.12, 0.4, 0.12);
      dummy.updateMatrix();
      dummy.matrix.premultiply(parent.matrix);
      mesh.setMatrixAt(2 * i + 1, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [M, S]);
  useFrame(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const t = clock.t;
    for (let i = 0; i < M.length; i++) {
      const c = STATE_COLORS[model.stateAt(i, t)];
      mesh.setColorAt(2 * i, c);
      mesh.setColorAt(2 * i + 1, c);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, M.length * 2]}>
      <boxGeometry />
      <meshBasicMaterial color="#ffffff" toneMapped={false} />
    </instancedMesh>
  );
}

function Tools({ model, heatmap }: { model: ReplayModel; heatmap: boolean }) {
  const byKind = useMemo(() => {
    const map = new Map<ToolKind, number[]>();
    for (const m of model.raw.layout.machines) {
      const a = map.get(m.kind) ?? [];
      a.push(m.id);
      map.set(m.kind, a);
    }
    return [...map.entries()];
  }, [model]);
  return (
    <group>
      {byKind.map(([kind, ids]) => (
        <ToolKindMesh key={kind} model={model} kind={kind} ids={ids} heatmap={heatmap} />
      ))}
      <StatusLights model={model} />
    </group>
  );
}

/* ------------------------------------------------------------------ rails */
function Rails({ model }: { model: ReplayModel }) {
  const railRef = useRef<THREE.InstancedMesh>(null);
  const arrowRef = useRef<THREE.InstancedMesh>(null);
  const S = sceneLayout(model);
  const edges = model.raw.layout.edges;
  const arrowEdges = useMemo(
    () =>
      edges.filter(([u, v]) => {
        const a = S.node[u], b = S.node[v];
        return Math.hypot(b[0] - a[0], b[1] - a[1]) > 2.2;
      }),
    [edges, S],
  );
  useLayoutEffect(() => {
    const rails = railRef.current, arrows = arrowRef.current;
    if (!rails || !arrows) return;
    edges.forEach(([u, v], k) => {
      const a = S.node[u], b = S.node[v];
      const dx = b[0] - a[0], dz = b[1] - a[1];
      const len = Math.hypot(dx, dz);
      dummy.position.set((a[0] + b[0]) / 2, RAIL_Y, (a[1] + b[1]) / 2);
      dummy.rotation.set(0, Math.atan2(-dz, dx), 0);
      dummy.scale.set(len + 0.1, 0.09, 0.16);
      dummy.updateMatrix();
      rails.setMatrixAt(k, dummy.matrix);
    });
    rails.instanceMatrix.needsUpdate = true;
    rails.computeBoundingSphere();
    arrowEdges.forEach(([u, v], k) => {
      const a = S.node[u], b = S.node[v];
      const dx = b[0] - a[0], dz = b[1] - a[1];
      dummy.position.set((a[0] + b[0]) / 2, RAIL_Y + 0.09, (a[1] + b[1]) / 2);
      // cone points +y; lay it down along the edge direction
      dummy.rotation.set(0, Math.atan2(-dz, dx), -Math.PI / 2);
      dummy.scale.set(1, 1, 1);
      dummy.updateMatrix();
      arrows.setMatrixAt(k, dummy.matrix);
    });
    arrows.instanceMatrix.needsUpdate = true;
    arrows.computeBoundingSphere();
  }, [edges, arrowEdges, S]);
  return (
    <group>
      <instancedMesh ref={railRef} args={[undefined, undefined, edges.length]}>
        <boxGeometry />
        <meshStandardMaterial color="#8a9aa5" roughness={0.45} metalness={0.15} />
      </instancedMesh>
      <instancedMesh ref={arrowRef} args={[undefined, undefined, arrowEdges.length]}>
        <coneGeometry args={[0.07, 0.24, 3]} />
        <meshBasicMaterial color="#b4c2ca" transparent opacity={0.6} />
      </instancedMesh>
    </group>
  );
}

/* --------------------------------------------------------------- vehicles */
function Vehicles({ model }: { model: ReplayModel }) {
  const bodyRef = useRef<THREE.InstancedMesh>(null);
  const lightRef = useRef<THREE.InstancedMesh>(null);
  const S = sceneLayout(model);
  const n = model.vehicles.length;
  const st = useMemo(() => ({ pos: [0, 0] as [number, number], prev: new Float32Array(n * 2), head: new Float32Array(n) }), [n]);
  const loadedC = useMemo(() => new THREE.Color('#35d0c0').multiplyScalar(2.2), []);
  const emptyC = useMemo(() => new THREE.Color('#9aa6ae').multiplyScalar(0.6), []);
  useFrame(() => {
    const body = bodyRef.current, light = lightRef.current;
    if (!body || !light) return;
    const t = clock.t;
    for (let v = 0; v < n; v++) {
      const lot = model.vehicleAt(v, t, st.pos);
      const x = st.pos[0] - S.cx, z = st.pos[1];
      const dx = x - st.prev[2 * v], dz = z - st.prev[2 * v + 1];
      if (dx * dx + dz * dz > 1e-6) st.head[v] = Math.atan2(-dz, dx);
      st.prev[2 * v] = x;
      st.prev[2 * v + 1] = z;
      dummy.position.set(x, RAIL_Y - 0.28, z);
      dummy.rotation.set(0, st.head[v], 0);
      dummy.scale.set(0.95, 0.42, 0.6);
      dummy.updateMatrix();
      body.setMatrixAt(v, dummy.matrix);
      dummy.position.set(x, RAIL_Y - 0.52, z);
      dummy.scale.set(0.7, 0.04, 0.45);
      dummy.updateMatrix();
      light.setMatrixAt(v, dummy.matrix);
      light.setColorAt(v, lot >= 0 ? loadedC : emptyC);
    }
    body.instanceMatrix.needsUpdate = true;
    light.instanceMatrix.needsUpdate = true;
    if (light.instanceColor) light.instanceColor.needsUpdate = true;
  });
  return (
    <group>
      <instancedMesh ref={bodyRef} args={[undefined, undefined, n]} frustumCulled={false}>
        <boxGeometry />
        <meshStandardMaterial color="#dfe4e6" roughness={0.4} metalness={0.2} />
      </instancedMesh>
      <instancedMesh ref={lightRef} args={[undefined, undefined, n]} frustumCulled={false}>
        <boxGeometry />
        <meshBasicMaterial color="#ffffff" toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

/* ------------------------------------------------------------------ FOUPs */
function foupGeometry(): THREE.BufferGeometry {
  const body = new THREE.BoxGeometry(FOUP.w, FOUP.h * 0.86, FOUP.w * 0.92);
  body.translate(0, -FOUP.h * 0.07, 0);
  const flange = new THREE.BoxGeometry(FOUP.w * 0.5, FOUP.h * 0.14, FOUP.w * 0.5);
  flange.translate(0, FOUP.h * 0.43, 0);
  return mergeGeometries([body.toNonIndexed(), flange.toNonIndexed()], false)!;
}

function Foups({ model, selectedLot, onSelectLot, reduced }: { model: ReplayModel; selectedLot: number | null; onSelectLot: (i: number | null) => void; reduced: boolean }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const S = sceneLayout(model);
  const geo = useMemo(foupGeometry, []);
  const nL = model.lots.length;
  const nG = model.raw.groups.length;
  const nM = model.raw.layout.machines.length;
  const nN = model.raw.layout.nodes.length;
  const scratch = useMemo(
    () => ({
      q: new Int32Array(nG),
      m: new Int32Array(nM),
      p: new Int32Array(nN),
      loc: { kind: -1, id: -1 },
      slot: [0, 0, 0] as [number, number, number],
      v: [0, 0] as [number, number],
      order: new Int32Array(nL),
      since: new Float64Array(nL),
    }),
    [nG, nM, nN, nL],
  );
  const colors = useMemo(
    () => ({
      normal: new THREE.Color('#9aa7b1'),
      hot: new THREE.Color('#ffffff').multiplyScalar(1.7),
      sel: new THREE.Color('#5ff0e6').multiplyScalar(2.6),
      red: new THREE.Color('#ff5a4e'),
    }),
    [],
  );
  useFrame(({ clock: c }) => {
    const mesh = ref.current;
    if (!mesh) return;
    const t = clock.t;
    const { q, m, p, loc, slot, v, order, since } = scratch;
    q.fill(0);
    m.fill(0);
    p.fill(0);
    // queue towers in arrival order: sort lots by time they entered their location
    for (let i = 0; i < nL; i++) {
      order[i] = i;
      since[i] = model.locSince(i, t);
    }
    order.sort((a, b) => since[a] - since[b]);
    for (let k = 0; k < nL; k++) {
      const i = order[k];
      model.locAt(i, t, loc);
      let visible = true;
      switch (loc.kind) {
        case LOC.QUEUE: {
          const [x, z] = S.stocker[loc.id];
          towerSlot(q[loc.id]++, slot);
          dummy.position.set(x + slot[0], slot[1], z + slot[2]);
          break;
        }
        case LOC.MACHINE: {
          const [x, y, z] = S.port[loc.id];
          dummy.position.set(x, y + m[loc.id]++ * (FOUP.h + FOUP.gap), z);
          break;
        }
        case LOC.VEHICLE: {
          model.vehicleAt(loc.id, t, v);
          dummy.position.set(v[0] - S.cx, RAIL_Y - 0.72, v[1]);
          break;
        }
        case LOC.PORT: {
          const [x, z] = S.node[loc.id];
          dummy.position.set(x, 0.95 + p[loc.id]++ * (FOUP.h + FOUP.gap), z);
          break;
        }
        default:
          visible = false;
      }
      dummy.rotation.set(0, 0, 0);
      dummy.scale.setScalar(visible ? 1 : 0);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      if (!visible) continue;
      // colour: selection > Q-time criticality > hot > normal
      if (i === selectedLot) tmpColor.copy(colors.sel);
      else {
        const qp = model.qtimeProgress(i, t);
        if (qp >= 0) {
          const f = Math.min(1.2, qp);
          if (f < 0.5) tmpColor.copy(colors.normal).lerp(colors.red, f * 0.8);
          else {
            const pulse = reduced ? 1 : 0.7 + 0.3 * Math.sin(c.elapsedTime * (4 + 10 * (f - 0.5)));
            tmpColor.copy(colors.red).multiplyScalar((0.9 + 2.6 * (f - 0.5)) * pulse);
          }
        } else if (model.lots[i].hot) tmpColor.copy(colors.hot);
        else tmpColor.copy(colors.normal);
      }
      mesh.setColorAt(i, tmpColor);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.boundingSphere = null; // instances move: recompute lazily for picking
  });
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (e.instanceId !== undefined) onSelectLot(e.instanceId);
  };
  return (
    <instancedMesh
      ref={ref}
      args={[geo, undefined, nL]}
      frustumCulled={false}
      onClick={onClick}
      onPointerOver={() => (document.body.style.cursor = 'pointer')}
      onPointerOut={() => (document.body.style.cursor = '')}
    >
      <meshStandardMaterial color="#ffffff" roughness={0.45} toneMapped={false} />
    </instancedMesh>
  );
}

/* ------------------------------------------------------ selection + camera */
function Beacon({ model, lot }: { model: ReplayModel; lot: number }) {
  const ref = useRef<THREE.Mesh>(null);
  const p = useMemo(() => [0, 0, 0] as [number, number, number], []);
  useFrame(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const ok = lotAnchor(model, lot, clock.t, p);
    mesh.visible = ok;
    mesh.position.set(p[0], 3.2, p[2]);
  });
  return (
    <mesh ref={ref}>
      <cylinderGeometry args={[0.025, 0.025, 6.4, 6]} />
      <meshBasicMaterial color={new THREE.Color('#5ff0e6').multiplyScalar(1.6)} toneMapped={false} transparent opacity={0.7} />
    </mesh>
  );
}

function CameraRig({ model, lot, follow, reduced }: { model: ReplayModel; lot: number | null; follow: boolean; reduced: boolean }) {
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null;
  const camera = useThree((s) => s.camera);
  const p = useMemo(() => [0, 0, 0] as [number, number, number], []);
  const target = useMemo(() => new THREE.Vector3(), []);
  const delta = useMemo(() => new THREE.Vector3(), []);
  useFrame((_, dt) => {
    if (!controls || lot === null || !follow) return;
    if (!lotAnchor(model, lot, clock.t, p)) return;
    target.set(p[0], 0.5, p[2]);
    const k = reduced ? 1 : 1 - Math.exp(-dt * 3.5);
    delta.copy(target).sub(controls.target).multiplyScalar(k);
    controls.target.add(delta);
    camera.position.add(delta);
    controls.update();
  });
  return null;
}

function Lights({ model }: { model: ReplayModel }) {
  const S = sceneLayout(model);
  const litho = model.raw.layout.bays.filter((b) => b.kind === 'litho');
  return (
    <>
      <hemisphereLight args={['#d6e4ef', '#1a1c1e', 0.75]} />
      <directionalLight position={[18, 40, 22]} intensity={1.15} color="#f4f6f8" />
      <directionalLight position={[-30, 22, -18]} intensity={0.3} color="#9fb6c8" />
      {/* yellow-room lighting over the photolithography bays */}
      {litho.map((b) => (
        <pointLight
          key={b.group}
          position={[b.x - S.cx, 6, b.side * (2 + b.len / 2)]}
          color="#ffb347"
          intensity={60}
          distance={18}
          decay={1.6}
        />
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ scene */
function useInView<T extends Element>(): [React.RefObject<T>, boolean] {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { rootMargin: '120px' });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, inView];
}

export default function FabScene({ model, selectedLot, onSelectLot, heatmap, follow, compact = false, reduced }: SceneProps) {
  const [wrap, inView] = useInView<HTMLDivElement>();
  const L = model.raw.layout;
  return (
    <div ref={wrap} className="absolute inset-0">
      <Canvas
        frameloop={inView ? 'always' : 'never'}
        dpr={[1, compact ? 1.25 : 1.75]}
        gl={{ antialias: false, powerPreference: 'high-performance', stencil: false }}
        camera={{ fov: compact ? 40 : 32, position: compact ? [-6, 58, 50] : [-16, 46, 52], near: 0.5, far: 400 }}
        onPointerMissed={() => onSelectLot(null)}
        aria-label="3D view of the fab floor"
      >
        <color attach="background" args={['#0b0e11']} />
        <fog attach="fog" args={['#0b0e11', 80, 170]} />
        <Lights model={model} />
        <Floor model={model} heatmap={heatmap} />
        {!compact && <BayLabels model={model} />}
        <Tools model={model} heatmap={heatmap} />
        <Rails model={model} />
        <Vehicles model={model} />
        <Foups model={model} selectedLot={selectedLot} onSelectLot={onSelectLot} reduced={reduced} />
        {selectedLot !== null && <Beacon model={model} lot={selectedLot} />}
        <OrbitControls
          makeDefault
          enableDamping={!reduced}
          dampingFactor={0.08}
          target={[2, 0, 0]}
          maxPolarAngle={Math.PI * 0.46}
          minDistance={8}
          maxDistance={L.width * 1.6}
        />
        <CameraRig model={model} lot={selectedLot} follow={follow} reduced={reduced} />
        <EffectComposer multisampling={compact ? 0 : 4}>
          <Bloom mipmapBlur luminanceThreshold={1} luminanceSmoothing={0.15} intensity={reduced ? 0.55 : 0.9} radius={0.72} />
          <Vignette eskil={false} offset={0.28} darkness={0.6} />
        </EffectComposer>
      </Canvas>
    </div>
  );
}
