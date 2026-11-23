import { fmt } from '../lib/format';
import type { ReplayModel } from '../replay/model';

const REPO = 'https://github.com/atesparilti1/fabtwin';

export default function Method({ model }: { model: ReplayModel | null }) {
  const k = model?.raw.meta.kpis_full_run;
  return (
    <section id="method" className="paper" aria-labelledby="method-title">
      <div className="mx-auto max-w-[1600px] px-4 pb-16 pt-16 md:px-6">
        <div className="grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div>
            <h2 id="method-title" className="display text-4xl text-pink md:text-5xl">Method and assumptions</h2>
            <p className="mt-4 max-w-[52ch] text-sm leading-relaxed text-pink2">
              The engine is a purpose-built discrete-event simulator in Python (no SimPy). Policies are compared with common random numbers: every
              random quantity comes from a stream keyed by seed, source and entity, so two policies on the same seed see the same lots and the same
              failure clocks, and paired differences have far lower variance.
            </p>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <a href={REPO} className="font-medium text-pink underline decoration-pline underline-offset-4 hover:decoration-pink">Source on GitHub</a>
              <a href={`${REPO}#readme`} className="text-pink2 underline decoration-pline underline-offset-4 hover:text-pink hover:decoration-pink">README</a>
              <a href={`${REPO}/blob/main/web/DATA_FORMAT.md`} className="text-pink2 underline decoration-pline underline-offset-4 hover:text-pink hover:decoration-pink">Replay data format</a>
            </div>
          </div>

          <div className="grid gap-x-10 gap-y-8 sm:grid-cols-2">
            <Block title="Model">
              <li>A lot is one FOUP of 25 wafers; wafers are never split.</li>
              <li>Each route step names a tool group, a recipe and a nominal process time; times carry lognormal noise.</li>
              <li>Batch furnaces process up to their capacity of one recipe, with a minimum batch and a maximum wait.</li>
              <li>A recipe change costs a sequence-dependent setup (reticle change on litho, species change on implant).</li>
              <li>Q-time limits the gap from a pre-clean to the furnace start; a violation sends the lot back to re-clean.</li>
            </Block>
            <Block title="Uncertainty">
              <li>Weibull time-to-failure on calendar time with lognormal repairs; a failure pauses the job and it resumes after repair.</li>
              <li>Overlay metrology sends a share of lots back to the litho step (rework).</li>
              <li>Hot lots arrive at random, carry a tighter due date and a higher weight, and go first in every queue.</li>
            </Block>
            <Block title="Transport">
              <li>OHT vehicles run on a directed rail graph: a one-way interbay loop with shortcuts and one intrabay loop per bay.</li>
              <li>Vehicles are assigned to transport requests by nearest-vehicle or by a Hungarian assignment, depending on the policy.</li>
            </Block>
            <Block title="Statistics">
              <li>KPIs are measured after a warm-up period whose length is checked with MSER-5 truncation; intervals are 95% Student-t half-widths over replications.</li>
              <li>Little&rsquo;s law is checked on every run as an invariant.</li>
              {k && (
                <li>
                  Replayed run ({model?.raw.meta.title}): time-average WIP <span className="num text-pink">{fmt(k.avg_wip, 1)}</span> lots vs throughput × cycle
                  time <span className="num text-pink">{fmt(k.little_wip, 1)}</span> lots.
                </li>
              )}
            </Block>
          </div>
        </div>

        <p className="mt-12 max-w-[80ch] border-t border-pline pt-5 text-xs leading-relaxed text-pink3">
          The fab is synthetic: sizes, process times and failure parameters are assumptions chosen to resemble a 300 mm module, documented in the
          repository. The replay files are traces of single runs; the conclusions rest on the replicated benchmarks in the results section.
        </p>
      </div>
      <footer className="border-t border-pline">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-baseline justify-between gap-4 px-4 py-6 text-sm md:px-6">
          <span className="text-pink">
            <span className="font-semibold">Ates Parilti</span> <span className="text-pink3">· Industrial Engineering, TU Eindhoven</span>
          </span>
          <a href={REPO} className="num text-xs text-pink2 underline decoration-pline underline-offset-4 hover:text-pink">github.com/atesparilti1/fabtwin</a>
        </div>
      </footer>
    </section>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="wide border-b border-pink pb-2 text-sm font-semibold text-pink">{title}</h3>
      <ul className="mt-3 space-y-2 text-sm leading-snug text-pink2">{children}</ul>
    </div>
  );
}
