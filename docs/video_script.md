# FabTwin: 90-second walkthrough (script)

Screen recording of https://atesparilti1.github.io/fabtwin/ at 1440×900, voice-over. Times are cumulative.
Numbers spoken in the voice-over must be read off the screen (the KPI panel, results section or README tables);
do not quote figures that are not visible in the recording.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:08 | Landing hero, slow scroll to the route chart (litho row highlighted). | "This is FabTwin, a digital twin of a semiconductor fab. Every wafer lot comes back to the lithography scanners once per mask layer, which makes a fab one of the hardest scheduling problems in industry." |
| 0:08–0:18 | Click **Open the twin**. 3D floor fades in; orbit slowly over the bays. | "Each bay is a tool group: scanners, furnace banks, etch clusters. Overhead, hoist vehicles carry FOUPs on a one-way rail network. Tools glow by state: processing, setup, down, maintenance." |
| 0:18–0:28 | Press play, set speed to 300×. Zoom to a furnace bay; FOUP towers grow and shrink. | "Queues stack as FOUP towers. Furnaces wait to fill batches of up to six lots, and lots inside a Q-time window, like clean to furnace within four hours, pulse red as their deadline approaches." |
| 0:28–0:38 | Click **next failure** in the timeline. A scanner turns red; queue builds. | "Tools fail at random, with Weibull lifetimes and lognormal repairs. I can jump straight to failures, Q-time violations or hot-lot arrivals." |
| 0:38–0:50 | Toggle **Compare**: split screen, FIFO baseline vs FabTwin policy, same seed. Point at the KPI deltas. | "Compare mode runs two policies on exactly the same random seed: same lots, same failures. Left, FIFO with nearest-vehicle transport; right, setup-aware litho dispatching, Hungarian vehicle assignment and simulation-optimised maintenance. The KPIs tick live." |
| 0:50–0:58 | Click a FOUP; camera follows it; lot-journey Gantt strip appears. | "Click any lot and the camera follows its re-entrant route, with every step on a Gantt strip." |
| 0:58–1:12 | Scroll to **Results**: CI bars, exact-vs-heuristic gaps, Pareto front, convergence. | "Everything shown here comes from code in the repo. CP-SAT and a time-indexed MIP give proven optima on small instances, which measures the gap of dispatching rules, the decomposition and ALNS. Policies are compared over 200 replications with common random numbers and 95% confidence intervals." |
| 1:12–1:22 | Scroll to **What-if**; change rule and release rate; run. WIP chart updates. | "A TypeScript port of the simulator runs in a Web Worker for quick what-if questions. It's labelled as exploratory; the reported numbers come from the Python engine." |
| 1:22–1:30 | Method section, then GitHub README with the headline table. | "Assumptions and limitations are listed explicitly. Code, tests and every benchmark are on GitHub. Thanks for watching." |

**Recording tips:** disable OS notifications; use the light results section for the voice-over on numbers; keep the cursor slow; export 1080p, 30 fps.
