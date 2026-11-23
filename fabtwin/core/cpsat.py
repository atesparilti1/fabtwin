"""CP-SAT model of the static batching flexible job shop (OR-Tools).

Formulation
-----------
Variables: for each operation o a start S_o and end E_o; for each eligible
machine m an optional interval I_om with presence literal x_om
(``sum_m x_om = 1``) and duration p_om.

* Precedence + transport:  S_{o+1} >= E_o + tau;  S_first >= r_j.
* Q-time:                  S_{o+1} - E_o <= Q_o.
* Non-batch machine m with setup s: AddCircuit over the present operations on
  m (plus a depot node). Arc i -> j implies S_j >= E_i + s * [recipe_i != recipe_j].
  Without setups, NoOverlap(I_om).
* Batch machine m (capacity K): for every pair (i, j) of same-recipe
  operations a literal b_ij ("same batch") with b_ij => S_i = S_j; every pair
  that is not batched must not overlap (E_i <= S_j or E_j <= S_i); different
  recipes never batch. Cumulative(I_om, demand 1, capacity K) bounds the batch
  size. Same-recipe batch durations are equal per machine by construction.
* Objective: min sum_j w_j T_j with T_j >= E_last(j) - d_j, T_j >= 0.

Weights are scaled to integers (hot lots weigh 10). Optional extra objective
terms: total flow time (epsilon-constraint for Pareto fronts).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from fabtwin.core.static import Schedule, StaticInstance


@dataclass
class CPResult:
    status: str
    objective: float | None
    bound: float
    seconds: float
    schedule: Schedule | None
    flow: float | None = None


def solve_cpsat(si: StaticInstance, time_limit_s: float = 30.0, workers: int = 8,
                flow_cap: int | None = None, objective: str = "wt",
                hint: Schedule | None = None, seed: int = 0) -> CPResult:
    """Solve to optimality or until the time limit.

    ``objective``: "wt" (weighted tardiness) or "flow" (total flow time).
    ``flow_cap``: optional epsilon constraint on total flow time.
    """
    md = cp_model.CpModel()
    H = si.horizon
    S: dict[tuple[int, int], cp_model.IntVar] = {}
    E: dict[tuple[int, int], cp_model.IntVar] = {}
    X: dict[tuple[int, int, int], cp_model.IntVar] = {}
    on_m: dict[int, list[tuple[tuple[int, int], cp_model.IntervalVar, cp_model.IntVar]]] = {}
    for j in si.jobs:
        for o in j.ops:
            key = (j.id, o.k)
            s = md.NewIntVar(j.release if o.k == 0 else 0, H, f"S{key}")
            e = md.NewIntVar(0, H, f"E{key}")
            S[key], E[key] = s, e
            lits = []
            for m, p in o.p.items():
                x = md.NewBoolVar(f"x{key}_{m}")
                iv = md.NewOptionalIntervalVar(s, p, e, x, f"I{key}_{m}")
                X[(j.id, o.k, m)] = x
                on_m.setdefault(m, []).append((key, iv, x))
                lits.append(x)
            md.AddExactlyOne(lits)
            if o.k > 0:
                prev = (j.id, o.k - 1)
                md.Add(s >= E[prev] + si.tau)
                q = j.ops[o.k - 1].qtime
                if q is not None:
                    md.Add(s - E[prev] <= q)

    def recipe(key: tuple[int, int]) -> int:
        return si.jobs[key[0]].ops[key[1]].recipe

    for m, items in on_m.items():
        g = si.machines[m]
        if si.is_batch(g):
            md.AddCumulative([iv for _, iv, _ in items], [1] * len(items), si.batch_max[g])
            for a in range(len(items)):
                for b in range(a + 1, len(items)):
                    ka, _, xa = items[a]
                    kb, _, xb = items[b]
                    if ka[0] == kb[0]:
                        before = md.NewBoolVar("")  # same job: precedence already orders them
                        md.Add(E[ka] <= S[kb]).OnlyEnforceIf(before) if ka[1] < kb[1] else md.Add(E[kb] <= S[ka]).OnlyEnforceIf(before)
                        md.AddBoolOr([before, xa.Not(), xb.Not()])
                        continue
                    o1, o2 = md.NewBoolVar(""), md.NewBoolVar("")
                    md.Add(E[ka] <= S[kb]).OnlyEnforceIf(o1)
                    md.Add(E[kb] <= S[ka]).OnlyEnforceIf(o2)
                    if recipe(ka) == recipe(kb):
                        same = md.NewBoolVar("")
                        md.Add(S[ka] == S[kb]).OnlyEnforceIf(same)
                        md.AddBoolOr([o1, o2, same, xa.Not(), xb.Not()])
                    else:
                        md.AddBoolOr([o1, o2, xa.Not(), xb.Not()])
        elif si.setup[g] > 0:
            st = si.setup[g]
            arcs: list[tuple[int, int, cp_model.IntVar]] = []
            n = len(items)
            for a, (ka, _, xa) in enumerate(items):
                arcs.append((a + 1, a + 1, xa.Not()))  # skip node if not on m
                first, last = md.NewBoolVar(""), md.NewBoolVar("")
                arcs.append((0, a + 1, first))
                arcs.append((a + 1, 0, last))
                for b, (kb, _, _) in enumerate(items):
                    if a == b:
                        continue
                    lit = md.NewBoolVar("")
                    arcs.append((a + 1, b + 1, lit))
                    gap = st if recipe(ka) != recipe(kb) else 0
                    md.Add(S[kb] >= E[ka] + gap).OnlyEnforceIf(lit)
            empty = md.NewBoolVar("")
            arcs.append((0, 0, empty))
            md.AddCircuit(arcs)
            if n == 0:
                continue
        else:
            md.AddNoOverlap([iv for _, iv, _ in items])

    T = []
    flow_terms = []
    for j in si.jobs:
        last = (j.id, len(j.ops) - 1)
        t = md.NewIntVar(0, H, f"T{j.id}")
        md.Add(t >= E[last] - j.due)
        T.append((t, int(round(j.weight))))
        flow_terms.append(E[last] - j.release)
    flow = sum(flow_terms)
    if flow_cap is not None:
        md.Add(flow <= flow_cap)
    if objective == "wt":
        md.Minimize(sum(w * t for t, w in T))
    elif objective == "flow":
        md.Minimize(flow)
    else:
        raise ValueError(objective)
    if hint is not None:
        for key, v in hint.start.items():
            md.AddHint(S[key], v)
        for (jid, k, m), x in X.items():
            md.AddHint(x, 1 if hint.machine.get((jid, k)) == m else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    t0 = time.perf_counter()
    st = solver.Solve(md)
    secs = time.perf_counter() - t0
    name = solver.StatusName(st)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return CPResult(name, None, solver.BestObjectiveBound(), secs, None)
    sched = Schedule()
    for (jid, k, m), x in X.items():
        if solver.Value(x):
            key = (jid, k)
            sched.machine[key] = m
            sched.start[key] = solver.Value(S[key])
            sched.end[key] = solver.Value(E[key])
    return CPResult(name, solver.ObjectiveValue(), solver.BestObjectiveBound(), secs, sched,
                    flow=float(solver.Value(flow)))
