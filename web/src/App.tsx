import { useCallback, useEffect, useState } from 'react';
import { IconWafer } from './lib/icons';
import Analytics from './panels/Analytics';
import Landing from './panels/Landing';
import Method from './panels/Method';
import Twin from './panels/Twin';
import WhatIf from './panels/WhatIf';
import { clock } from './replay/clock';
import { loadAnalytics, loadIndex, useAsync } from './replay/load';
import type { ReplayModel } from './replay/model';

const NAV = [
  { href: '#twin', label: 'Twin' },
  { href: '#analytics', label: 'Results' },
  { href: '#whatif', label: 'What if' },
  { href: '#method', label: 'Method' },
];

function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg">
      <div className="mx-auto flex h-12 max-w-[1600px] items-center gap-6 px-4 md:px-6">
        <a href="#top" className="flex items-center gap-2 text-ink">
          <IconWafer />
          <span className="wide text-[0.95rem] font-bold tracking-tight">FabTwin</span>
        </a>
        <nav aria-label="Sections" className="ml-auto flex items-center gap-4 text-xs text-ink2 sm:gap-6">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="hidden transition-colors hover:text-ink sm:inline">
              {n.label}
            </a>
          ))}
          <a href="https://github.com/atesparilti1/fabtwin" className="rounded-sm border border-line2 px-2.5 py-1 text-ink transition-colors hover:border-amber hover:text-amber">
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}

/** Space toggles play; arrows step 15 sim-minutes (shift: 2 h). Ignored while typing or on form controls. */
function useKeyboard() {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || el?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.code === 'Space') {
        if (tag === 'BUTTON' || tag === 'A') return; // native activation
        e.preventDefault();
        clock.toggle();
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        clock.step((e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 2 : 0.25));
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);
}

export default function App() {
  const index = useAsync(loadIndex);
  const analytics = useAsync(loadAnalytics);
  const [model, setModel] = useState<ReplayModel | null>(null);
  const [firstModel, setFirstModel] = useState<ReplayModel | null>(null);
  useKeyboard();
  const onModel = useCallback((m: ReplayModel | null) => {
    setModel(m);
    if (m) setFirstModel((f) => f ?? m);
  }, []);
  const anyModel = model ?? firstModel;
  return (
    <div id="top" className="min-h-screen overflow-x-clip">
      <a href="#twin" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:bg-amber focus:px-3 focus:py-1 focus:text-bg">
        Skip to the twin
      </a>
      <Header />
      <main>
        <Landing model={anyModel} index={index} />
        <Twin index={index} onModel={onModel} />
        <Analytics data={analytics} index={index} />
        <WhatIf model={anyModel} />
        <Method model={anyModel} />
      </main>
    </div>
  );
}
