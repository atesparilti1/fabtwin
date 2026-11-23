"""Bottleneck-first decomposition (shifting-bottleneck style) and the litho
subproblem used both statically and in the rolling-horizon simulator policy.

Static version (``solve_decomposition``):
  1. Bottleneck = setup tool group(s) with the largest workload (litho).
  2. For every litho operation compute a release (job release + head: minimal
     upstream work + transport) and an operation due date (job due - tail).
  3. Solve the litho subproblem exactly-ish with CP-SAT: parallel non-identical
     machines with eligibility and sequence-dependent reticle setups,
     minimising weighted operation tardiness.
  4. Fix the litho sequence as priorities, schedule all other operations around
     it with ATC priorities via the list-scheduling decoder.
  5. Re-estimate heads/tails from the decoded schedule and repeat (2 passes),
     keep the best schedule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from fabtwin.core.static import Schedule, StaticInstance, decode_best, evaluate, rule_rank


@dataclass
class LithoTask:
    key: object  # caller's identifier
    release: int
    due: int
    weight: int
    recipe: int
    p: dict[int, int]  # machine -> duration


def solve_litho(tasks: list[LithoTask], setup: int, initial_recipe: dict[int, int | None],
                machine_free: dict[int, int], time_limit_s: float = 5.0,
                workers: int = 8) -> dict[object, tuple[int, int]]:
    """Parallel-machine scheduling with setups: returns key -> (machine, start).

    min sum w_i max(0, C_i - d_i), machines may be busy until ``machine_free``
    and start with ``initial_recipe`` loaded (a setup is needed for others).
    """
    if not tasks:
        return {}
    md = cp_model.CpModel()
    H = max(t.release for t in tasks) + sum(max(t.p.values()) + setup for t in tasks) + \
        max(machine_free.values(), default=0) + 1
    S, E, X = {}, {}, {}
    per_m: dict[int, list[int]] = {}
    for i, t in enumerate(tasks):
        S[i] = md.NewIntVar(t.release, H, "")
        E[i] = md.NewIntVar(0, H, "")
        lits = []
        for m, p in t.p.items():
            x = md.NewBoolVar("")
            md.NewOptionalIntervalVar(S[i], p, E[i], x, "")
            md.Add(E[i] == S[i] + p).OnlyEnforceIf(x)
            md.Add(S[i] >= machine_free.get(m, 0)).OnlyEnforceIf(x)
            X[(i, m)] = x
            per_m.setdefault(m, []).append(i)
            lits.append(x)
        md.AddExactlyOne(lits)
    for m, idx in per_m.items():
        arcs = []
        for a in idx:
            xa = X[(a, m)]
            arcs.append((a + 1, a + 1, xa.Not()))
            first = md.NewBoolVar("")
            arcs.append((0, a + 1, first))
            init = initial_recipe.get(m)
            if init is not None and init != tasks[a].recipe and setup > 0:
                md.Add(S[a] >= machine_free.get(m, 0) + setup).OnlyEnforceIf(first)
            last = md.NewBoolVar("")
            arcs.append((a + 1, 0, last))
            for b in idx:
                if a == b:
                    continue
                lit = md.NewBoolVar("")
                arcs.append((a + 1, b + 1, lit))
                gap = setup if tasks[a].recipe != tasks[b].recipe else 0
                md.Add(S[b] >= E[a] + gap).OnlyEnforceIf(lit)
        arcs.append((0, 0, md.NewBoolVar("")))
        md.AddCircuit(arcs)
    T = []
    for i, t in enumerate(tasks):
        tv = md.NewIntVar(0, H, "")
        md.Add(tv >= E[i] - t.due)
        T.append(t.weight * tv)
    # small secondary term: finish early (keeps the bottleneck busy)
    md.Minimize(100 * sum(T) + sum(E.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    st = solver.Solve(md)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {}
    out = {}
    for (i, m), x in X.items():
        if solver.Value(x):
            out[tasks[i].key] = (m, solver.Value(S[i]))
    return out


@dataclass
class DecompResult:
    objective: float
    schedule: Schedule
    seconds: float
    passes: int


def _bottleneck_groups(si: StaticInstance) -> set[int]:
    load: dict[int, float] = {}
    for o in si.ops:
        load[o.group] = load.get(o.group, 0.0) + min(o.p.values()) / max(
            1, sum(1 for g in si.machines.values() if g == o.group))
    setup_groups = [g for g in load if si.setup[g] > 0 and not si.is_batch(g)]
    if not setup_groups:
        return {max(load, key=lambda g: load[g])}
    return {g for g in setup_groups if si.kinds[g] == "litho"} or {max(setup_groups, key=lambda g: load[g])}


def solve_decomposition(si: StaticInstance, sub_time_s: float = 5.0, passes: int = 2) -> DecompResult:
    t0 = time.perf_counter()
    bn = _bottleneck_groups(si)
    base = rule_rank(si, "ATC")
    best_c, best_s = None, None
    est_start: dict[tuple[int, int], int] | None = None
    for _ in range(passes):
        tasks: list[LithoTask] = []
        for j in si.jobs:
            head = j.release
            mins = [min(o.p.values()) for o in j.ops]
            for o in j.ops:
                tail = sum(mins[o.k + 1:]) + si.tau * (len(j.ops) - 1 - o.k)
                if o.group in bn:
                    rel = est_start[(j.id, o.k)] if est_start else head
                    tasks.append(LithoTask((j.id, o.k), rel, j.due - tail, int(round(j.weight)),
                                           o.recipe, dict(o.p)))
                head += mins[o.k] + si.tau
        setup = max(si.setup[g] for g in bn)
        plan = solve_litho(tasks, setup, {m: None for m in si.machines},
                           {m: 0 for m in si.machines}, time_limit_s=sub_time_s)
        rank = dict(base)
        if plan:
            lo = min(base.values())
            for key, (_, start) in plan.items():
                rank[key] = lo - 1e6 + start  # litho order fixed by the subproblem
        sched = decode_best(si, rank)
        c = evaluate(si, sched)
        if best_c is None or c < best_c:
            best_c, best_s = c, sched
        est_start = {k: sched.start[k] for k in sched.start}
    assert best_c is not None and best_s is not None
    return DecompResult(best_c, best_s, time.perf_counter() - t0, passes)
