"""Adaptive large neighbourhood search (Ropke & Pisinger, 2006) for the static problem.

Solution encoding: a priority permutation of all operations, decoded by the
non-delay list scheduler :func:`fabtwin.core.static.decode` (always feasible
w.r.t. precedence, capacity, batching and setups; Q-time violations are
penalised in the objective).

Destroy operators
    random        remove q random operations
    worst_job     remove all operations of the most (weighted-)tardy jobs
    related       Shaw removal: operations on the same tool group close in time
    setup_cluster remove operations of one recipe on a setup tool (litho)
Repair operators
    greedy        insert each operation at the best of a few sampled positions
    due_order     reinsert in due-date order at due-date-consistent positions
    batch_merge   place batch-tool operations next to same-recipe operations
                  (so they are dispatched in the same batch)
    setup_seq     place litho operations next to same-reticle operations
                  (setup-aware litho resequencing)
    qtime_repair  move operations inside violated Q-time windows to the front

Acceptance: simulated annealing; operator weights adapt per segment.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fabtwin.core.static import (
    Schedule,
    StaticInstance,
    decode_best,
    evaluate,
    qtime_violations,
    rule_rank,
)

Key = tuple[int, int]


@dataclass
class ALNSResult:
    best_obj: float
    best_schedule: Schedule
    best_perm: list[Key]
    history: dict[str, list[float]] = field(default_factory=dict)
    op_weights: dict[str, float] = field(default_factory=dict)
    iterations: int = 0
    seconds: float = 0.0


def _perm_from_rank(rank: dict[Key, float]) -> list[Key]:
    return sorted(rank, key=lambda k: (rank[k], k))


class ALNS:
    def __init__(self, si: StaticInstance, seed: int = 0, q_frac: tuple[float, float] = (0.05, 0.25),
                 objective: Callable[[StaticInstance, Schedule], float] | None = None) -> None:
        self.si = si
        self.rng = random.Random(seed)
        self.q_frac = q_frac
        self.obj = objective or evaluate
        self.destroy: dict[str, Callable[[list[Key], Schedule, int], tuple[list[Key], list[Key]]]] = {
            "random": self._d_random, "worst_job": self._d_worst_job,
            "related": self._d_related, "setup_cluster": self._d_setup_cluster,
        }
        self.repair: dict[str, Callable[[list[Key], list[Key], Schedule], list[Key]]] = {
            "greedy": self._r_greedy, "due_order": self._r_due, "batch_merge": self._r_batch,
            "setup_seq": self._r_setup, "qtime_repair": self._r_qtime,
        }
        self.op = {o.job * 10_000 + o.k: o for o in si.ops}

    def _o(self, k: Key):  # type: ignore[no-untyped-def]
        return self.si.jobs[k[0]].ops[k[1]]

    def cost(self, perm: list[Key]) -> tuple[float, Schedule]:
        rank = {k: float(i) for i, k in enumerate(perm)}
        s = decode_best(self.si, rank)
        return self.obj(self.si, s), s

    # ------------------------------------------------------------- destroy ops
    def _q(self, n: int) -> int:
        lo, hi = self.q_frac
        return max(2, int(n * self.rng.uniform(lo, hi)))

    def _d_random(self, perm: list[Key], s: Schedule, q: int) -> tuple[list[Key], list[Key]]:
        rem = set(self.rng.sample(perm, min(q, len(perm))))
        return [k for k in perm if k not in rem], [k for k in perm if k in rem]

    def _d_worst_job(self, perm: list[Key], s: Schedule, q: int) -> tuple[list[Key], list[Key]]:
        si = self.si
        tard = sorted(si.jobs, key=lambda j: -j.weight * max(0, s.end[(j.id, len(j.ops) - 1)] - j.due)
                      + self.rng.random() * 1e-3)
        rem: set[Key] = set()
        for j in tard:
            if len(rem) >= q:
                break
            rem |= {(j.id, o.k) for o in j.ops}
        return [k for k in perm if k not in rem], [k for k in perm if k in rem]

    def _d_related(self, perm: list[Key], s: Schedule, q: int) -> tuple[list[Key], list[Key]]:
        seed = self.rng.choice(perm)
        g, t = self._o(seed).group, s.start[seed]
        ranked = sorted(perm, key=lambda k: (self._o(k).group != g, abs(s.start[k] - t)))
        rem = set(ranked[:q])
        return [k for k in perm if k not in rem], [k for k in perm if k in rem]

    def _d_setup_cluster(self, perm: list[Key], s: Schedule, q: int) -> tuple[list[Key], list[Key]]:
        setup_ops = [k for k in perm if self.si.setup[self._o(k).group] > 0
                     or self.si.is_batch(self._o(k).group)]
        if not setup_ops:
            return self._d_random(perm, s, q)
        r = self._o(self.rng.choice(setup_ops)).recipe
        g = self._o(setup_ops[0]).group
        rem = {k for k in setup_ops if self._o(k).recipe == r}
        # add same-group ops close in time to allow resequencing around them
        extra = [k for k in setup_ops if k not in rem]
        self.rng.shuffle(extra)
        rem |= set(extra[: max(0, q - len(rem))])
        _ = g
        return [k for k in perm if k not in rem], [k for k in perm if k in rem]

    # -------------------------------------------------------------- repair ops
    def _r_greedy(self, partial: list[Key], removed: list[Key], s: Schedule) -> list[Key]:
        self.rng.shuffle(removed)
        exact, rest = removed[:3], removed[3:]
        perm = self._r_due(partial, rest, s)
        partial = perm
        removed = exact
        for k in exact:
            n = len(perm)
            cand = {0, n}
            cand |= {self.rng.randint(0, n) for _ in range(4)}
            # near the op's previous relative position
            best_pos, best_c = 0, math.inf
            for pos in cand:
                trial = perm[:pos] + [k] + perm[pos:]
                pending = [x for x in removed if x not in trial]
                c, _ = self.cost(trial + pending)
                if c < best_c:
                    best_pos, best_c = pos, c
            perm.insert(best_pos, k)
        return perm

    def _r_due(self, partial: list[Key], removed: list[Key], s: Schedule) -> list[Key]:
        si = self.si
        due = {k: si.jobs[k[0]].due - (len(si.jobs[k[0]].ops) - k[1]) for k in partial + removed}
        perm = list(partial)
        for k in sorted(removed, key=lambda k: (due[k], k)):
            pos = next((i for i, x in enumerate(perm) if due[x] > due[k]), len(perm))
            perm.insert(pos, k)
        return perm

    def _insert_near(self, perm: list[Key], k: Key, pred: Callable[[Key], bool]) -> None:
        idx = [i for i, x in enumerate(perm) if pred(x)]
        if idx:
            perm.insert(self.rng.choice(idx) + 1, k)
        else:
            perm.insert(self.rng.randint(0, len(perm)), k)

    def _r_batch(self, partial: list[Key], removed: list[Key], s: Schedule) -> list[Key]:
        perm = list(partial)
        for k in removed:
            o = self._o(k)
            if self.si.is_batch(o.group):
                self._insert_near(perm, k, lambda x: self._o(x).group == o.group
                                  and self._o(x).recipe == o.recipe)
            else:
                perm.insert(self.rng.randint(0, len(perm)), k)
        return perm

    def _r_setup(self, partial: list[Key], removed: list[Key], s: Schedule) -> list[Key]:
        perm = list(partial)
        for k in sorted(removed, key=lambda k: self.si.jobs[k[0]].due):
            o = self._o(k)
            if self.si.setup[o.group] > 0:
                self._insert_near(perm, k, lambda x: self._o(x).group == o.group
                                  and self._o(x).recipe == o.recipe)
            else:
                pos = next((i for i, x in enumerate(perm)
                            if self.si.jobs[x[0]].due > self.si.jobs[k[0]].due), len(perm))
                perm.insert(pos, k)
        return perm

    def _r_qtime(self, partial: list[Key], removed: list[Key], s: Schedule) -> list[Key]:
        si = self.si
        viol: set[int] = set()
        for j in si.jobs:
            for o in j.ops[:-1]:
                if o.qtime is not None and s.start[(j.id, o.k + 1)] - s.end[(j.id, o.k)] > o.qtime:
                    viol.add(j.id)
        perm = self._r_due(partial, removed, s)
        if not viol:
            return perm
        urgent = [k for k in perm if k[0] in viol and (
            self._o(k).qtime is not None or (k[1] > 0 and si.jobs[k[0]].ops[k[1] - 1].qtime is not None))]
        return urgent + [k for k in perm if k not in set(urgent)]

    # -------------------------------------------------------------------- main
    def run(self, init_rank: dict[Key, float] | None = None, iters: int = 2000,
            time_limit_s: float = 30.0, segment: int = 50, reaction: float = 0.15,
            t_start_frac: float = 0.05, t_end_frac: float = 0.001) -> ALNSResult:
        si = self.si
        if init_rank is None:
            best = None
            for rule in ("ATC", "EDD", "CR", "FIFO"):
                rk = rule_rank(si, rule)
                c, sch = self.cost(_perm_from_rank(rk))
                if best is None or c < best[0]:
                    best = (c, _perm_from_rank(rk), sch)
            assert best is not None
            cur_c, cur, cur_s = best
        else:
            cur = _perm_from_rank(init_rank)
            cur_c, cur_s = self.cost(cur)
        best_c, best_p, best_s = cur_c, list(cur), cur_s
        w_d = {k: 1.0 for k in self.destroy}
        w_r = {k: 1.0 for k in self.repair}
        sc_d = {k: 0.0 for k in self.destroy}
        sc_r = {k: 0.0 for k in self.repair}
        n_d = {k: 0 for k in self.destroy}
        n_r = {k: 0 for k in self.repair}
        T0 = max(1.0, t_start_frac * max(cur_c, 1.0)) / math.log(2)
        T_end = max(1e-3, t_end_frac * max(cur_c, 1.0))
        hist: dict[str, list[float]] = {"iter": [], "best": [], "current": [], "time": []}
        t0 = time.perf_counter()
        it = 0
        while it < iters and time.perf_counter() - t0 < time_limit_s:
            it += 1
            frac = min(1.0, max(it / iters, (time.perf_counter() - t0) / time_limit_s))
            T = T0 * (T_end / T0) ** frac
            d = self.rng.choices(list(w_d), weights=list(w_d.values()))[0]
            r = self.rng.choices(list(w_r), weights=list(w_r.values()))[0]
            partial, removed = self.destroy[d](cur, cur_s, self._q(len(cur)))
            cand = self.repair[r](partial, removed, cur_s)
            c, s = self.cost(cand)
            score = 0.0
            if c < best_c - 1e-9:
                best_c, best_p, best_s = c, list(cand), s
                score = 33.0
            if c < cur_c - 1e-9:
                score = max(score, 9.0)
                cur, cur_c, cur_s = cand, c, s
            elif self.rng.random() < math.exp(-(c - cur_c) / max(T, 1e-9)):
                score = max(score, 13.0) if c != cur_c else score
                cur, cur_c, cur_s = cand, c, s
            sc_d[d] += score
            sc_r[r] += score
            n_d[d] += 1
            n_r[r] += 1
            if it % segment == 0:
                for k in w_d:
                    if n_d[k]:
                        w_d[k] = (1 - reaction) * w_d[k] + reaction * sc_d[k] / n_d[k]
                    w_d[k] = max(w_d[k], 0.05)
                    sc_d[k], n_d[k] = 0.0, 0
                for k in w_r:
                    if n_r[k]:
                        w_r[k] = (1 - reaction) * w_r[k] + reaction * sc_r[k] / n_r[k]
                    w_r[k] = max(w_r[k], 0.05)
                    sc_r[k], n_r[k] = 0.0, 0
            if it % 5 == 0 or it == 1:
                hist["iter"].append(it)
                hist["best"].append(best_c)
                hist["current"].append(cur_c)
                hist["time"].append(round(time.perf_counter() - t0, 3))
        weights = {**{f"destroy:{k}": v for k, v in w_d.items()},
                   **{f"repair:{k}": v for k, v in w_r.items()}}
        return ALNSResult(best_c, best_s, best_p, hist, weights, it, time.perf_counter() - t0)


def solve_alns(si: StaticInstance, seed: int = 0, iters: int = 2000, time_limit_s: float = 30.0,
               init_rank: dict[Key, float] | None = None) -> ALNSResult:
    res = ALNS(si, seed).run(init_rank=init_rank, iters=iters, time_limit_s=time_limit_s)
    assert qtime_violations(si, res.best_schedule) >= 0
    return res
