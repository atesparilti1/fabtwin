import type { ToolKind } from '../replay/types';

/** Machine state colours (index = mstate code). Kept in sync with CSS tokens. */
export const STATE_HEX = ['#64707a', '#f0a830', '#35d0c0', '#ff5a4e', '#8f9dff'] as const;
export const STATE_LABEL = ['Idle', 'Setup', 'Processing', 'Down', 'PM'] as const;
/** Emissive intensity per state (values > 1 feed the bloom pass). */
export const STATE_GLOW = [0.55, 2.6, 2.4, 3.2, 2.4] as const;

export const KIND_LABEL: Record<ToolKind, string> = {
  litho: 'Lithography', etch: 'Etch', dep: 'Deposition', furnace: 'Furnace', implant: 'Implant', cmp: 'CMP', clean: 'Wet clean', metro: 'Metrology',
};
/** Muted per-kind tints for route strips (datasheet). Litho owns the amber. */
export const KIND_HEX: Record<ToolKind, string> = {
  litho: '#f0a830', etch: '#5f7f96', dep: '#7b8f74', furnace: '#a0786a', implant: '#8a7aa6', cmp: '#6f8f93', clean: '#9aa4aa', metro: '#4e5a63',
};

export function hexToRgb(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

/** Sequential utilisation ramp (dark slate -> amber -> near white) for the heat map. */
const RAMP: [number, [number, number, number]][] = [
  [0, hexToRgb('#1a2630')], [0.5, hexToRgb('#3a5560')], [0.75, hexToRgb('#c98a2a')], [0.9, hexToRgb('#ff6a3d')], [1, hexToRgb('#ffe2c4')],
];
export function utilColor(u: number, out: [number, number, number] = [0, 0, 0]): [number, number, number] {
  const x = Math.min(1, Math.max(0, u));
  for (let i = 1; i < RAMP.length; i++) {
    if (x <= RAMP[i][0]) {
      const [a, ca] = RAMP[i - 1], [b, cb] = RAMP[i];
      const f = (x - a) / (b - a);
      out[0] = ca[0] + (cb[0] - ca[0]) * f; out[1] = ca[1] + (cb[1] - ca[1]) * f; out[2] = ca[2] + (cb[2] - ca[2]) * f;
      return out;
    }
  }
  return out;
}
export const UTIL_STOPS = RAMP;

/** Recipe colour for Gantt bars: hue by product, lightness by layer. */
const PRODUCT_HUES = [196, 32, 152, 268, 8];
export function recipeColor(recipe: number): string {
  const p = Math.floor(recipe / 1000), layer = recipe % 1000;
  const h = PRODUCT_HUES[p % PRODUCT_HUES.length];
  const l = 34 + ((layer * 7) % 30);
  return `hsl(${h} 38% ${l}%)`;
}
