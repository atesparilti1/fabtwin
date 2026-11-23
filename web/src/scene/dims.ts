import type { ToolKind } from '../replay/types';

/** Tool footprints (metres), kept free of three.js so 2D views stay light. */
export interface KindDims {
  w: number; // extent along z
  d: number; // extent along x
  h: number; // height of the status strip
}

export const DIMS: Record<ToolKind, KindDims> = {
  litho: { w: 5.8, d: 1.9, h: 2.15 },
  furnace: { w: 1.5, d: 1.9, h: 3.7 },
  etch: { w: 3.6, d: 1.9, h: 1.6 },
  dep: { w: 3.6, d: 1.9, h: 1.75 },
  implant: { w: 5.0, d: 1.9, h: 2.3 },
  cmp: { w: 3.8, d: 1.9, h: 1.6 },
  clean: { w: 5.4, d: 1.7, h: 1.85 },
  metro: { w: 1.9, d: 1.5, h: 1.55 },
};

export const RAIL_Y = 4.2;
export const FOUP = { w: 0.42, h: 0.36, gap: 0.04 };
