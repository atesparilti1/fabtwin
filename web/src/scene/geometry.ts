import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import type { ToolKind } from '../replay/types';
import { DIMS, FOUP, RAIL_Y } from './dims';

export { DIMS, FOUP, RAIL_Y };

/**
 * Low-poly tool bodies, one merged geometry per tool kind. Local frame:
 * -x faces the load port / rail, z runs along the bay, y up. Footprints are
 * stylised but sized like 300 mm tools (metres).
 */
function box(w: number, h: number, d: number, x: number, y: number, z: number): THREE.BufferGeometry {
  // BoxGeometry(width=x, height=y, depth=z)
  const g = new THREE.BoxGeometry(d, h, w);
  g.translate(x, y + h / 2, z);
  return g;
}
function cyl(r: number, h: number, x: number, y: number, z: number, seg = 10): THREE.BufferGeometry {
  const g = new THREE.CylinderGeometry(r, r, h, seg);
  g.translate(x, y + h / 2, z);
  return g;
}

function build(kind: ToolKind): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  switch (kind) {
    case 'litho': {
      // scanner body + coater/developer track at the front + illuminator housing
      parts.push(box(5.8, 2.0, 1.3, 0.3, 0, 0));
      parts.push(box(5.8, 1.25, 0.6, -0.65, 0, 0));
      parts.push(box(1.4, 0.45, 1.0, 0.35, 2.0, -1.4));
      parts.push(box(5.2, 0.12, 1.1, 0.3, 2.0, 0.3));
      break;
    }
    case 'furnace': {
      parts.push(box(1.4, 3.6, 1.35, 0.27, 0, 0));
      parts.push(box(1.4, 1.0, 0.55, -0.68, 0, 0));
      parts.push(cyl(0.16, 0.5, 0.45, 3.6, 0.35, 8));
      break;
    }
    case 'etch': {
      parts.push(box(2.4, 1.6, 0.5, -0.7, 0, 0)); // EFEM
      const hub = new THREE.CylinderGeometry(0.55, 0.55, 1.15, 6);
      hub.translate(0.15, 0.575, 0);
      parts.push(hub);
      for (const [x, z] of [[0.2, -1.25], [0.55, 0], [0.2, 1.25]]) parts.push(box(0.9, 1.45, 0.8, x, 0, z));
      break;
    }
    case 'dep': {
      parts.push(box(2.4, 1.7, 0.5, -0.7, 0, 0));
      const hub = new THREE.CylinderGeometry(0.5, 0.5, 1.05, 8);
      hub.translate(0.15, 0.525, 0);
      parts.push(hub);
      for (const [x, z] of [[0.15, -1.3], [0.55, -0.5], [0.55, 0.5], [0.15, 1.3]]) parts.push(cyl(0.38, 1.65, x, 0, z, 12));
      break;
    }
    case 'implant': {
      parts.push(box(5.0, 1.5, 1.8, 0.05, 0, 0));
      parts.push(box(1.4, 2.25, 1.8, 0.05, 0, -1.8)); // ion source terminal
      const beam = new THREE.CylinderGeometry(0.2, 0.2, 3.2, 10);
      beam.rotateX(Math.PI / 2);
      beam.translate(0.25, 1.7, 0.6);
      parts.push(beam);
      break;
    }
    case 'cmp': {
      parts.push(box(3.8, 1.45, 1.8, 0.05, 0, 0));
      for (const z of [-1.15, 0, 1.15]) parts.push(cyl(0.32, 0.22, 0.25, 1.45, z, 14));
      break;
    }
    case 'clean': {
      parts.push(box(5.4, 1.7, 1.6, 0.05, 0, 0));
      for (const z of [-1.8, 0, 1.8]) parts.push(box(0.5, 0.35, 0.45, 0.4, 1.7, z));
      break;
    }
    case 'metro': {
      parts.push(box(1.8, 1.35, 1.4, 0.05, 0, 0));
      const dome = new THREE.SphereGeometry(0.4, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2);
      dome.translate(0.15, 1.35, 0);
      parts.push(dome);
      break;
    }
  }
  // normalise attribute sets (some primitives are non-indexed after transforms)
  const norm = parts.map((g) => (g.index ? g.toNonIndexed() : g));
  const merged = mergeGeometries(norm, false);
  if (!merged) throw new Error(`geometry merge failed for ${kind}`);
  merged.computeBoundingSphere();
  return merged;
}

const cache = new Map<ToolKind, THREE.BufferGeometry>();
export function toolGeometry(kind: ToolKind): THREE.BufferGeometry {
  let g = cache.get(kind);
  if (!g) cache.set(kind, (g = build(kind)));
  return g;
}

