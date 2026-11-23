/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        raised: 'var(--raised)',
        panel: 'var(--panel)',
        line: 'var(--line)',
        line2: 'var(--line-2)',
        ink: 'var(--ink)',
        ink2: 'var(--ink-2)',
        ink3: 'var(--ink-3)',
        paper: 'var(--paper)',
        paper2: 'var(--paper-2)',
        pink: 'var(--p-ink)',
        pink2: 'var(--p-ink-2)',
        pink3: 'var(--p-ink-3)',
        pline: 'var(--p-line)',
        amber: 'var(--amber)',
        amberd: 'var(--amber-deep)',
        cyan: 'var(--cyan)',
        red: 'var(--red)',
        pm: 'var(--pm)',
        idle: 'var(--idle)',
      },
      fontFamily: {
        sans: ['Archivo', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
    },
  },
  plugins: [],
};
