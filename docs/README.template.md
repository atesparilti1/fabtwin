# FabTwin

**Stochastic scheduling and transport optimisation for a semiconductor fab, with a 3D digital twin.**

[Live demo](https://atesparilti1.github.io/fabtwin/) · [Technical write-up (PDF, 2 pages)](docs/fabtwin_writeup.pdf) · [Formulation](docs/formulation.md) · [Replay data format](web/DATA_FORMAT.md)

![FabTwin landing page](docs/figures/site_landing.png)

FabTwin optimises three coupled problems of a wafer fab under uncertainty and checks every policy in a discrete-event digital twin:

1. **Scheduling.** A re-entrant flexible job shop with batching: lots revisit lithography once per mask layer, furnaces batch up to 6 lots of one recipe, scanners pay a setup on every reticle change, Q-time windows limit the wait between clean and furnace, and hot lots jump the queue.
2. **Transport.** Overhead hoist vehicles (OHT) on a directed rail network with loops and one-way shortcuts, with congestion, deadlock avoidance, and coupling to Q-time feasibility.
3. **Maintenance and uncertainty.** Weibull failures, lognormal repairs and processing times, metrology rework, random hot lots, and preventive-maintenance (PM) intervals as decision variables.

Every number in this README and in the web app is produced by a script in this repository with a fixed seed (`make bench`). Assumptions are labelled; simplifications compared with real fabs are listed at the end.

---

## Headline results

{{HEADLINE}}

{{CV}}

---

## Repository layout

```
fabtwin/core/      instance model, generator, layout + rail graph, dispatch rules,
                   static snapshot problem + decoders, CP-SAT, time-indexed MIP (HiGHS),
                   bottleneck-first decomposition, ALNS, rolling-horizon planner, maintenance
fabtwin/sim/       own discrete-event engine (failures, PM, rework, Q-time, OHT), CRN streams,
                   replication runner, output analysis (t-CIs, paired CIs, MSER-5), replay export
scripts/           bench_*.py (every table and figure), export_scenarios.py, make_figures.py,
                   build_analytics.py, build_writeup.py, build_readme.py
web/               React + TypeScript + Vite + Tailwind + react-three-fiber twin, Web Worker what-if
tests/             schedule feasibility, simulator invariants, Little's Law, CP-SAT = MIP, OHT headway
results/           JSON + Markdown outputs of the benchmarks (committed)
```

```bash
pip install -e ".[dev]"
make test          # pytest with coverage (core + sim), mypy via `make typecheck`
make bench         # regenerates every table, figure and web dataset (~45 min on 16 cores)
make web           # replay data + production build of the web twin
```

---

## The problem

### Fab model (synthetic, SMT2020-inspired)

The public SMT2020 testbed (Kopp et al., 2020) has about 1,000 tools and routes of 300–600 steps. That is too large for exact methods and for 200-replication studies in Python, so `fabtwin/core/generator.py` builds smaller fabs with the same **structure**. Each layer runs pre-clean → oxidation furnace or deposition → litho → overlay metrology (3% rework back to litho) → etch → strip, with implant + anneal and CMP on some layers, plus a 4 h clean → furnace Q-time. Each product has its own reticle per layer, furnace recipes are shared across products (batchable), and implant species cause setups. The release rate is set so the litho groups run at the target utilisation counting a setup on every visit, which makes litho the designed bottleneck. Litho dedication (each step qualified on all but one scanner) is load-balanced.

{{INSTANCE}}

All parameter values (processing-time ranges, CVs, MTBF/MTTR/shape, PM durations, flow factors) are in `generator.py` and are stored inside every instance (`Instance.params`). They are order-of-magnitude assumptions, not fab data.

### Formulation

The full CP-SAT and time-indexed MIP formulations, the stochastic model and the maintenance model are in **[docs/formulation.md](docs/formulation.md)**. In short, the CP-SAT model is:

$$\min \sum_j w_j T_j \quad \text{s.t.}\quad \sum_{m\in M_o} x_{om}=1,\ \ S_{o_{k+1}}\ge E_{o_k}+\tau,\ \ S_{o_{k+1}}-E_{o_k}\le Q_{o_k},\ \ \textsc{Circuit} \text{ with setups},\ \ \text{batch synchronisation},\ \ T_j\ge E_{o_{n_j}}-d_j.$$

---

## Methods

| Layer | Method | Code |
|---|---|---|
| Ground truth | CP-SAT (optional intervals, AddCircuit for sequence-dependent setups, pairwise batch synchronisation + cumulative, hard Q-time) | `core/cpsat.py` |
| Ground truth | Time-indexed MIP solved with HiGHS (same grid, same problem) | `core/mip.py` |
| Baselines | FIFO, SPT, EDD, ODD, critical ratio, ATC; setup-aware ATCS (machine-first, reticle-aware) | `core/dispatch.py` |
| Decomposition | Bottleneck-first: litho subproblem (parallel machines, setups, operation due dates from heads/tails) by CP-SAT, rest dispatched around it; 2 passes | `core/decomposition.py` |
| Metaheuristic | ALNS on priority vectors, decoded by active (Giffler–Thompson) and non-delay schedule generation (best of both); destroy: random, worst-job, Shaw, setup-cluster; repair: greedy, due-order, **batch merge**, **setup-aware litho resequencing**, **Q-time repair**; simulated-annealing acceptance, adaptive weights | `core/alns.py` |
| Rolling horizon | Every 8 h, CP-SAT sequences the litho queue plus lots about to arrive (live machine state, loaded reticle); other tools keep their rule | `core/rolling.py` |
| Transport | Hungarian assignment per decision epoch (priority credits for hot lots, open Q-time windows and waiting time), congestion-aware A*, headway time-window reservations (collision- and deadlock-free by construction) | `sim/oht.py` |
| Maintenance | Age-based PM; nominal plan by renewal-reward (availability-optimal); robust plan by simulation optimisation with CRN, two-stage screen-and-select, validation on fresh seeds | `core/maintenance.py` |
| Digital twin | Own event engine; per-entity random streams for common random numbers; trace export for the browser | `sim/engine.py` |

### Simulation methodology

* **Horizon and warm-up.** 120 simulated days per replication. The 30-day warm-up was checked with MSER-5 on the across-replication mean daily WIP (figure below).
* **Replications.** 200 per policy for dispatching, maintenance validation and the headline comparison; 60 for the OHT fleet study; 20 for the (expensive) rolling-horizon CP-SAT policy. Intervals are two-sided 95% Student-t.
* **Common random numbers.** Every random quantity comes from its own stream keyed by (seed, source, entity): one per lot (processing noise, rework draws), per machine (failures, repairs, PM durations, batch noise), plus releases and hot lots. Policies compared on the same seeds therefore face the same lots and failure clocks, and differences are reported as **paired** CIs.
* **Sanity checks.** Little's Law ($L=\lambda W$, including scrapped lots) holds within about 1% in every policy; the sample-path identity area(WIP) = Σ time-in-system is tested exactly; stability is checked as output rate = input rate (tests).

![Warm-up](docs/figures/warmup.png)

---

## Results

### Step 1: dispatching rules in the stochastic fab

{{DISPATCH}}

![Dispatching](docs/figures/dispatch_ci.png)

### Steps 2–3: exact models, decomposition and ALNS

{{EXACT}}

![Gaps](docs/figures/exact_gaps.png)

<p float="left"><img src="docs/figures/scaling.png" width="49%"> <img src="docs/figures/pareto.png" width="49%"></p>

![Convergence](docs/figures/convergence.png)

**Reading.** CP-SAT proves optimality within a second on every small instance. The time-indexed MIP reaches the same optimum where it terminates, but needs 10–90 s and stops at the time limit from about 80 operations. Its bounds stay consistent with the CP-SAT optimum. The bottleneck-first decomposition and ALNS close part of the gap left by dispatching rules. ALNS is never worse than the best rule (it is seeded with it). The remaining gap comes from its schedule-generation scheme: some optimal schedules idle a scanner on purpose or wait to fill a furnace batch in ways the decoders cannot express. At 240 operations, time-limited CP-SAT still wins. At 480 and more, it no longer finds good solutions in 60 s while ALNS keeps improving on the rules, which is the crossover that motivates decomposition at fab scale.

### Step 4: OHT transport and Q-time coupling

{{OHT}}

![OHT](docs/figures/oht.png)

### Step 5: maintenance under uncertainty, robust vs nominal

{{MAINT}}

![Maintenance](docs/figures/maintenance.png)

### Coupled fab: full policies

{{HEADTABLE}}

![Headline](docs/figures/headline.png)

---

## The 3D twin (web/)

React + TypeScript + Vite + Tailwind + react-three-fiber/drei with bloom. It replays precomputed event logs: three policies on the same seed, 7 days each, exported by `scripts/export_scenarios.py` and regenerated in the Pages build.

* Fab floor with bays of stylised tools: scanners, furnace towers, etch clusters, implanters, CMP, wet benches and metrology. All are instanced, glow by state (idle, setup, processing, down, PM), and the floor can show a bottleneck heat map.
* OHT rails on the ceiling, vehicles moving along booked waypoints and carrying FOUPs, queues stacked as FOUP towers at each stocker. Q-time-critical lots pulse red as their deadline approaches.
* Timeline scrubber at 1×–1000×, with jumps to failures, Q-time violations, hot-lot arrivals and PMs.
* Compare mode: split screen with policy A vs policy B on the same seed and live KPIs.
* Lot journey: click a FOUP and the camera follows it, with a Gantt strip of its re-entrant route.
* Analytics: litho Gantt, CI bars, Pareto front, convergence, exact-vs-heuristic table, OHT and maintenance studies, all read from `analytics.json`.
* **What-if mode:** a simplified TypeScript port of the simulator and dispatching rules running in a Web Worker. It is labelled as exploratory; reported numbers come from the Python engine.
* A 2D floor map on phones or without WebGL; `prefers-reduced-motion` turns off autoplay, pulsing and camera moves.

---

## Assumptions and limitations

* **Synthetic fab.** It has the SMT2020 structure, not the SMT2020 data, and is smaller (16 tool groups, 55 tools, 58–69-step routes in the benchmark fab). The `large` preset (38 groups, up to 153 steps) is generated and tested but not benchmarked with 200 replications.
* **Not modelled:** operators, reticle availability and pod logistics, engineering holds, send-ahead wafers, tool chambers as separate resources, or yield beyond rework and Q-time scrap.
* **Failures** run on calendar time and renew at repair and PM (as good as new); a failure pauses the current job (preempt-resume).
* **Transport.** Point vehicles at constant speed (3 m/s) without acceleration; idle vehicles park on stocker spurs off the running rail; delivery is to the bay stocker, and the stocker-to-tool hand-off is instantaneous.
* **Releases** follow a renewal process with CV 1 (no CONWIP or start-rate control). The operating point is chosen so the fab is stable over 300 days on several instance seeds; the x-factor (about 1.9–2.2) is lower than in many real fabs because there are fewer sources of variability.
* **Static instances** for exact methods are WIP snapshots with 0.1 h time resolution and deterministic durations; the MIP horizon is 1.25× the best heuristic makespan.
* **ALNS** is limited by its schedule-generation scheme (see the gap table). It is reported as measured.
* **Optional RL / genetic-programming dispatching** was not run, so nothing is reported for it.

---

## Author

Ates Parilti, Industrial Engineering, TU Eindhoven. Related work: Monte Carlo study of the ASML EUV supply chain, XGBoost demand forecaster, full-stack apps.

{{FOOTER}}
