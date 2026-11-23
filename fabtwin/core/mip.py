"""Time-indexed MIP of the static problem, solved with HiGHS (highspy).

Variables x[o, m, t] = 1 if operation o starts on machine m at period t;
for batch machines additionally z[m, r, t] = 1 if a batch of recipe r starts.

    sum_{m,t} x[o,m,t] = 1                                    (assignment)
    S_o = sum t x[o,m,t],  E_o = sum (t + p_om) x[o,m,t]
    S_{o+1} >= E_o + tau ;  S_{o+1} - E_o <= Q_o ;  S_first >= r_j
    non-batch m:  occ[m,r,t] = sum_{o in r} sum_{t'=t-p+1..t} x[o,m,t']
                  sum_r occ[m,r,t] <= 1                        (capacity)
                  occ[m,r,t] + sum_{o in r'} sum_{t'=t+1..t+s} x[o,m,t'] <= 1
                  for r != r' (setup s after a different recipe)
    batch m:      x[o,m,t] <= z[m,r(o),t] ;  sum_{o in r} x[o,m,t] <= K z[m,r,t]
                  sum_r sum_{t'=t-P_mr+1..t} z[m,r,t'] <= 1     (one batch at a time)
    T_j >= E_last - d_j,  T_j >= 0;   min sum w_j T_j

The time grid is the same integer grid as the CP-SAT model, so both models
solve the same problem; the horizon is capped at ``horizon`` periods, which
must be at least the makespan of a known feasible schedule (we pass the best
heuristic makespan + slack) to keep the model exact on that horizon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import highspy
import numpy as np

from fabtwin.core.static import Schedule, StaticInstance


@dataclass
class MIPResult:
    status: str
    objective: float | None
    bound: float
    seconds: float
    schedule: Schedule | None
    n_vars: int
    n_rows: int


def solve_mip(si: StaticInstance, horizon: int, time_limit_s: float = 60.0,
              threads: int = 8) -> MIPResult:
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit_s))
    h.setOptionValue("threads", threads)
    h.setOptionValue("mip_rel_gap", 0.0)
    inf = highspy.kHighsInf
    col_lo: list[float] = []
    col_hi: list[float] = []
    cost: list[float] = []
    integ: list[int] = []

    def var(lo: float, hi: float, c: float = 0.0, binary: bool = True) -> int:
        col_lo.append(lo)
        col_hi.append(hi)
        cost.append(c)
        integ.append(1 if binary else 0)
        return len(col_lo) - 1

    rows: list[tuple[list[int], list[float], float, float]] = []
    x: dict[tuple[int, int, int, int], int] = {}  # (job, k, m, t)
    by_op: dict[tuple[int, int], list[tuple[int, int, int]]] = {}  # op -> [(col, m, t)]
    for j in si.jobs:
        # earliest start from release + predecessors (valid tightening)
        est = j.release
        for o in j.ops:
            key = (j.id, o.k)
            lst = []
            for m, p in o.p.items():
                for t in range(est, horizon - p + 1):
                    c = var(0, 1)
                    x[(j.id, o.k, m, t)] = c
                    lst.append((c, m, t))
            by_op[key] = lst
            est += min(o.p.values()) + si.tau
    for key, lst in by_op.items():
        rows.append(([c for c, _, _ in lst], [1.0] * len(lst), 1.0, 1.0))

    def start_terms(key: tuple[int, int]) -> tuple[list[int], list[float]]:
        lst = by_op[key]
        return [c for c, _, _ in lst], [float(t) for _, _, t in lst]

    def end_terms(key: tuple[int, int]) -> tuple[list[int], list[float]]:
        o = si.jobs[key[0]].ops[key[1]]
        lst = by_op[key]
        return [c for c, _, _ in lst], [float(t + o.p[m]) for _, m, t in lst]

    for j in si.jobs:
        for o in j.ops[1:]:
            sc, sv = start_terms((j.id, o.k))
            ec, ev = end_terms((j.id, o.k - 1))
            rows.append((sc + ec, sv + [-v for v in ev], float(si.tau), inf))
            q = j.ops[o.k - 1].qtime
            if q is not None:
                rows.append((sc + ec, sv + [-v for v in ev], -inf, float(q)))
    # machines
    ops_on: dict[int, list[tuple[int, int]]] = {}
    for key in by_op:
        o = si.jobs[key[0]].ops[key[1]]
        for m in o.p:
            ops_on.setdefault(m, []).append(key)
    for m, keys in ops_on.items():
        g = si.machines[m]
        recipes = sorted({si.jobs[k[0]].ops[k[1]].recipe for k in keys})
        if si.is_batch(g):
            P = {r: max(si.jobs[k[0]].ops[k[1]].p[m] for k in keys
                        if si.jobs[k[0]].ops[k[1]].recipe == r) for r in recipes}
            z = {(r, t): var(0, 1) for r in recipes for t in range(horizon)}
            for r in recipes:
                rk = [k for k in keys if si.jobs[k[0]].ops[k[1]].recipe == r]
                for t in range(horizon):
                    cols = [x[(k[0], k[1], m, t)] for k in rk if (k[0], k[1], m, t) in x]
                    if not cols:
                        continue
                    for c in cols:
                        rows.append(([c, z[(r, t)]], [1.0, -1.0], -inf, 0.0))
                    rows.append((cols + [z[(r, t)]], [1.0] * len(cols) + [-float(si.batch_max[g])], -inf, 0.0))
            for t in range(horizon):
                cols = [z[(r, tt)] for r in recipes for tt in range(max(0, t - P[r] + 1), t + 1)]
                rows.append((cols, [1.0] * len(cols), -inf, 1.0))
        else:
            s = si.setup[g]
            occ_cols: dict[tuple[int, int], list[int]] = {}
            for k in keys:
                o = si.jobs[k[0]].ops[k[1]]
                p = o.p[m]
                for t in range(horizon):
                    for tt in range(max(0, t - p + 1), t + 1):
                        c = x.get((k[0], k[1], m, tt))
                        if c is not None:
                            occ_cols.setdefault((o.recipe, t), []).append(c)
            for t in range(horizon):
                cols = [c for r in recipes for c in occ_cols.get((r, t), [])]
                if len(cols) > 1:
                    rows.append((cols, [1.0] * len(cols), -inf, 1.0))
            if s > 0 and len(recipes) > 1:
                starts: dict[tuple[int, int], int] = {}
                for k in keys:
                    o = si.jobs[k[0]].ops[k[1]]
                    for t in range(horizon):
                        c = x.get((k[0], k[1], m, t))
                        if c is not None:
                            starts[(k[0] * 1000 + k[1], t)] = c
                for r in recipes:
                    other = [k for k in keys if si.jobs[k[0]].ops[k[1]].recipe != r]
                    for t in range(horizon):
                        occ = occ_cols.get((r, t), [])
                        if not occ:
                            continue
                        cols = list(occ)
                        for k in other:
                            for tt in range(t + 1, min(horizon, t + s + 1)):
                                c = x.get((k[0], k[1], m, tt))
                                if c is not None:
                                    cols.append(c)
                        if len(cols) > len(occ):
                            rows.append((cols, [1.0] * len(cols), -inf, 1.0))
    # tardiness
    for j in si.jobs:
        tj = var(0, inf, j.weight, binary=False)
        ec, ev = end_terms((j.id, len(j.ops) - 1))
        rows.append((ec + [tj], ev + [-1.0], -inf, float(j.due)))

    n = len(col_lo)
    lp = highspy.HighsLp()
    lp.num_col_ = n
    lp.num_row_ = len(rows)
    lp.col_cost_ = np.array(cost)
    lp.col_lower_ = np.array(col_lo)
    lp.col_upper_ = np.array(col_hi)
    lp.row_lower_ = np.array([r[2] for r in rows])
    lp.row_upper_ = np.array([r[3] for r in rows])
    starts_, idx, val = [0], [], []
    # build column-wise matrix
    cols_entries: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for i, (cs, vs, _, _) in enumerate(rows):
        for c, v in zip(cs, vs):
            cols_entries[c].append((i, v))
    for c in range(n):
        for i, v in cols_entries[c]:
            idx.append(i)
            val.append(v)
        starts_.append(len(idx))
    lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_ = np.array(starts_)
    lp.a_matrix_.index_ = np.array(idx)
    lp.a_matrix_.value_ = np.array(val)
    lp.integrality_ = [highspy.HighsVarType.kInteger if b else highspy.HighsVarType.kContinuous
                       for b in integ]
    h.passModel(lp)
    t0 = time.perf_counter()
    h.run()
    secs = time.perf_counter() - t0
    status = h.modelStatusToString(h.getModelStatus())
    info = h.getInfo()
    bound = float(info.mip_dual_bound)
    obj = float(info.objective_function_value) if info.primal_solution_status == 2 else None
    sched = None
    if obj is not None:
        sol = h.getSolution().col_value
        sched = Schedule()
        for (jid, k, m, t), c in x.items():
            if sol[c] > 0.5:
                o = si.jobs[jid].ops[k]
                sched.machine[(jid, k)] = m
                sched.start[(jid, k)] = t
                sched.end[(jid, k)] = t + o.p[m]
    return MIPResult(status, obj, bound, secs, sched, n, len(rows))
