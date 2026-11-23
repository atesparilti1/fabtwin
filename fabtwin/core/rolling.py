"""Rolling-horizon, bottleneck-first planner for the simulator.

Every ``plan_every_h`` hours the simulator calls :class:`LithoPlanner`. It
builds the litho subproblem from the live fab state -- lots queued at litho
plus lots finishing the step right before a litho step (expected arrival =
machine finish + transport) -- with operation due dates
``d_op = d_lot - FF * remaining work after the litho step``, machine
availability (busy until the current job ends, down machines until an
expected repair) and the reticle currently loaded. CP-SAT
(:func:`fabtwin.core.decomposition.solve_litho`) sequences it; the planned
start order becomes the litho dispatch priority until the next plan. All
other tool groups keep their dispatching rule ("schedule the bottleneck
first, dispatch the rest around it").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fabtwin.core.decomposition import LithoTask, solve_litho

if TYPE_CHECKING:
    from fabtwin.sim.engine import Simulator


class LithoPlanner:
    def __init__(self, unit_h: float = 0.05, time_limit_s: float = 0.5, workers: int = 1,
                 max_tasks: int = 40) -> None:
        self.unit = unit_h
        self.time_limit_s = time_limit_s
        self.workers = workers
        self.max_tasks = max_tasks
        self.calls = 0

    def __call__(self, sim: Simulator) -> dict[int, float]:
        from fabtwin.sim.engine import MState

        self.calls += 1
        inst, now, u = sim.inst, sim.now, self.unit
        rank: dict[int, float] = {}
        for g in inst.groups:
            if g.kind != "litho":
                continue
            tasks: list[LithoTask] = []
            cand = [(lot, now) for lot in sim.queues[g.id]]
            # lots one step upstream of this litho group, finishing soon
            for m in sim.machines:
                for lot in m.batch:
                    route = inst.products[lot.product].route
                    if lot.step + 1 < len(route) and route[lot.step + 1].group == g.id:
                        cand.append((lot, max(now, m.phase_end) + inst.transport_h))
            cand.sort(key=lambda x: (not x[0].hot, x[0].due))
            for lot, arr in cand[: self.max_tasks]:
                route = inst.products[lot.product].route
                k = lot.step if lot in sim.queues[g.id] else lot.step + 1
                step = route[k]
                rem_after = sim.rem[lot.product][k + 1]
                ff = inst.hot_flow_factor if lot.hot else inst.flow_factor
                d_op = lot.due - ff * rem_after
                p = {m: max(1, round(step.proc_h / inst.machines[m].speed / u)) for m in step.eligible}
                tasks.append(LithoTask(lot.id, round((arr - now) / u), round((d_op - now) / u),
                                       int(lot.weight), step.recipe, p))
            free, recipe = {}, {}
            for mid in g.machines:
                m = sim.machines[mid]
                if m.state in (MState.BUSY, MState.SETUP):
                    t_free = m.phase_end - now
                elif m.state == MState.DOWN:
                    f = g.failure
                    t_free = f.mttr_h if f is not None else 0.0
                elif m.state == MState.PM:
                    t_free = g.failure.pm_h if g.failure is not None else 0.0
                else:
                    t_free = 0.0
                free[mid] = max(0, round(t_free / u))
                recipe[mid] = m.last_recipe
            plan = solve_litho(tasks, round(g.setup_h / u), recipe, free,
                               time_limit_s=self.time_limit_s, workers=self.workers)
            for lid, (_, start) in plan.items():
                rank[int(lid)] = float(start)  # type: ignore[call-overload]
        return rank
