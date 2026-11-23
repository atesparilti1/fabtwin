/** Small authored icon set: 16px grid, 1.5px strokes, square caps. */
type P = { className?: string };
const base = { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none', 'aria-hidden': true } as const;

export const IconPlay = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M4.5 3v10l8-5z" fill="currentColor" />
  </svg>
);
export const IconPause = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M5 3.5v9M11 3.5v9" stroke="currentColor" strokeWidth="2" />
  </svg>
);
export const IconPrev = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M10.5 3.5 6 8l4.5 4.5" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
export const IconNext = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M5.5 3.5 10 8l-4.5 4.5" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
export const IconTarget = ({ className }: P) => (
  <svg {...base} className={className}>
    <circle cx="8" cy="8" r="4.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8 1v3M8 12v3M1 8h3M12 8h3" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
export const IconClose = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
export const IconArrow = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
export const IconWafer = ({ className }: P) => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden className={className}>
    <circle cx="10" cy="10" r="8.25" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5 7.5h10M4 10h12M5 12.5h10" stroke="var(--amber)" strokeWidth="1.2" />
    <path d="M8 18.2h4" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);
