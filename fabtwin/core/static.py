"""Static (deterministic, finite) scheduling instances and a schedule decoder.

A static instance is a snapshot problem: a set of lots with release times, due
dates, weights and (truncated) re-entrant routes on the fab's tool groups, in
integer time units. It is the common ground on which the exact models
(CP-SAT, time-indexed MIP), the decomposition heuristic, ALNS and the classic
dispatching rules are compared.

Problem (all hard constraints except where noted)
    * each operation runs on one eligible machine, duration p[o, m]
    * route precedence with transport time tau between consecutive operations
    * non-batch machines: one operation at a time, sequence-dependent setup
      ``s_g`` between operations of different recipes (none before the first)
    * batch machines: up to K operations of the same recipe start together and
      occupy the machine for the batch duration (equal per recipe on a machine)
    * Q-time: start(o+1) - end(o) <= Q on steps with a Q-time limit
      (hard in the exact models; heuristics count violations and are penalised)
    * objective: total weighted tardiness  sum_j w_j max(0, C_j - d_j)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from fabtwin.core.generator import generate
from fabtwin.core.instance import Instance


@dataclass(frozen=True)
class SOp:
    job: int
    k: int  # position in the job's route
    group: int
    recipe: int
    p: dict[int, int]  # machine -> duration (time units)
    qtime: int | None  # max gap to the next op's start, if any


@dataclass(frozen=True)
class SJob:
    id: int
    product: int
    release: int
    due: int
    weight: float
    ops: tuple[SOp, ...]


@dataclass(frozen=True)
class StaticInstance:
    name: str
    unit_h: float
    tau: int
    jobs: tuple[SJob, ...]
    machines: dict[int, int]  # machine -> group
    batch_max: dict[int, int]  # group -> K (1 = no batching)
    setup: dict[int, int]  # group -> setup time units
    kinds: dict[int, str]
    horizon: int

    @property
    def ops(self) -> list[SOp]:
        return [o for j in self.jobs for o in j.ops]

    def is_batch(self, g: int) -> bool:
        return self.batch_max[g] > 1


def make_static(n_lots: int, n_steps: int, seed: int = 0, preset: str = "tiny",
                unit_h: float = 0.1, release_spread_h: float | None = None,
                due_factor: float = 1.6, hot_share: float = 0.15) -> StaticInstance:
    """Snapshot instance built from a generated fab (deterministic in ``seed``).

    Lots start at random route positions (a WIP snapshot), take the next
    ``n_steps`` operations, are released over ``release_spread_h`` and are due
    ``due_factor`` x their raw processing time after release.
    """
    inst: Instance = generate(preset, seed=0)
    rng = random.Random(seed)
    spread = release_spread_h if release_spread_h is not None else 0.5 * n_lots
    # batch duration per (group, recipe, machine) = max over all route steps
    batch_p: dict[tuple[int, int, int], int] = {}
    for p in inst.products:
        for s in p.route:
            g = inst.groups[s.group]
            if g.is_batch:
                for m in s.eligible:
                    d = max(1, round(s.proc_h / inst.machines[m].speed / unit_h))
                    key = (s.group, s.recipe, m)
                    batch_p[key] = max(batch_p.get(key, 0), d)
    jobs = []
    for j in range(n_lots):
        prod = inst.products[rng.randrange(len(inst.products))]
        start = rng.randrange(0, max(1, len(prod.route) - n_steps))
        steps = prod.route[start:start + n_steps]
        ops = []
        for k, s in enumerate(steps):
            g = inst.groups[s.group]
            if g.is_batch:
                pm = {m: batch_p[(s.group, s.recipe, m)] for m in s.eligible}
            else:
                pm = {m: max(1, round(s.proc_h / inst.machines[m].speed / unit_h))
                      for m in s.eligible}
            q = (round(s.qtime_max_h / unit_h) if s.qtime_max_h is not None and k < len(steps) - 1
                 else None)
            ops.append(SOp(j, k, s.group, s.recipe, pm, q))
        release = round(rng.uniform(0, spread) / unit_h)
        raw = sum(min(o.p.values()) for o in ops)
        hot = rng.random() < hot_share
        due = release + round((due_factor * 0.7 if hot else due_factor) * raw)
        jobs.append(SJob(j, prod.id, release, due, 10.0 if hot else 1.0, tuple(ops)))
    used = {m for jb in jobs for o in jb.ops for m in o.p}
    machines = {m: inst.machines[m].group for m in sorted(used)}
    groups = {g for g in machines.values()}
    tau = max(1, round(inst.transport_h / unit_h))
    horizon = (max(jb.release for jb in jobs)
               + sum(max(o.p.values()) + tau + inst.groups[o.group].setup_h / unit_h
                     for jb in jobs for o in jb.ops))
    return StaticInstance(
        name=f"{preset}-n{n_lots}-k{n_steps}-s{seed}",
        unit_h=unit_h,
        tau=tau,
        jobs=tuple(jobs),
        machines=machines,
        batch_max={g: inst.groups[g].batch_max for g in groups},
        setup={g: round(inst.groups[g].setup_h / unit_h) for g in groups},
        kinds={g: inst.groups[g].kind.value for g in groups},
        horizon=int(horizon) + 1,
    )


# --------------------------------------------------------------------- schedules
@dataclass
class Schedule:
    """Assignment (op -> machine, start, end) with objective bookkeeping."""

    start: dict[tuple[int, int], int] = field(default_factory=dict)
    end: dict[tuple[int, int], int] = field(default_factory=dict)
    machine: dict[tuple[int, int], int] = field(default_factory=dict)
    batch: dict[tuple[int, int], int] = field(default_factory=dict)

    def completion(self, si: StaticInstance) -> list[int]:
        return [self.end[(j.id, len(j.ops) - 1)] for j in si.jobs]


def weighted_tardiness(si: StaticInstance, sched: Schedule) -> float:
    return sum(j.weight * max(0, c - j.due) for j, c in zip(si.jobs, sched.completion(si)))


def total_flow(si: StaticInstance, sched: Schedule) -> float:
    return float(sum(c - j.release for j, c in zip(si.jobs, sched.completion(si))))


def qtime_violations(si: StaticInstance, sched: Schedule) -> int:
    v = 0
    for j in si.jobs:
        for o in j.ops[:-1]:
            if o.qtime is not None and sched.start[(j.id, o.k + 1)] - sched.end[(j.id, o.k)] > o.qtime:
                v += 1
    return v


def check_schedule(si: StaticInstance, sched: Schedule, qtime_hard: bool = True) -> list[str]:
    """Return a list of constraint violations (empty = feasible)."""
    errs: list[str] = []
    for j in si.jobs:
        prev_end = None
        for o in j.ops:
            key = (j.id, o.k)
            m = sched.machine[key]
            if m not in o.p:
                errs.append(f"{key}: ineligible machine {m}")
                continue
            if sched.end[key] - sched.start[key] != o.p[m]:
                errs.append(f"{key}: wrong duration")
            if o.k == 0 and sched.start[key] < j.release:
                errs.append(f"{key}: starts before release")
            if prev_end is not None and sched.start[key] < prev_end + si.tau:
                errs.append(f"{key}: precedence/transport")
            prev_end = sched.end[key]
    if qtime_hard and qtime_violations(si, sched):
        errs.append(f"{qtime_violations(si, sched)} Q-time violations")
    by_m: dict[int, list[tuple[int, int, int, tuple[int, int]]]] = {}
    for key, m in sched.machine.items():
        o = si.jobs[key[0]].ops[key[1]]
        by_m.setdefault(m, []).append((sched.start[key], sched.end[key], o.recipe, key))
    for m, lst in by_m.items():
        g = si.machines[m]
        lst.sort()
        if si.is_batch(g):
            groups: dict[int, list[tuple[int, int, int, tuple[int, int]]]] = {}
            for it in lst:
                groups.setdefault(it[0], []).append(it)
            batches = sorted(groups.items())
            for s, b in batches:
                if len(b) > si.batch_max[g]:
                    errs.append(f"machine {m}: batch over capacity at {s}")
                if len({x[2] for x in b}) > 1:
                    errs.append(f"machine {m}: mixed recipes at {s}")
            for (s1, b1), (s2, _) in zip(batches, batches[1:]):
                if s2 < max(x[1] for x in b1):
                    errs.append(f"machine {m}: batches overlap at {s2}")
        else:
            for x, y in zip(lst, lst[1:]):
                gap = si.setup[g] if x[2] != y[2] else 0
                if y[0] < x[1] + gap:
                    errs.append(f"machine {m}: overlap/setup between {x[3]} and {y[3]}")
    return errs


# ----------------------------------------------------------------------- decoder
def decode(si: StaticInstance, rank: dict[tuple[int, int], float],
           qtime_hold: bool = False) -> Schedule:
    """Giffler-Thompson style active-schedule decoder for a priority ``rank``.

    Repeatedly: among all ready (operation, machine) pairs take the one with the
    earliest completion C* on machine m*; the conflict set is every ready
    operation that could start on m* before C*; the lowest-``rank`` operation
    of the conflict set is scheduled on m*. On a batch tool, further
    same-recipe operations of the conflict set join the batch (in rank order)
    and the batch starts when its last member is ready, so the decoder can wait
    to fill a batch. Setups are included in the earliest start. Every priority
    vector therefore maps to a feasible schedule (Q-time is evaluated, not
    enforced); ``qtime_hold`` is kept for API compatibility and ignored.
    """
    sched = Schedule()
    free_at = {m: 0 for m in si.machines}
    last_recipe: dict[int, int | None] = {m: None for m in si.machines}
    ready: dict[tuple[int, int], int] = {(j.id, 0): j.release for j in si.jobs}
    batch_id = 0

    def est(key: tuple[int, int], m: int) -> int:
        o = si.jobs[key[0]].ops[key[1]]
        g = o.group
        s = si.setup[g] if (last_recipe[m] is not None and last_recipe[m] != o.recipe) else 0
        return max(ready[key], free_at[m] + s)

    while ready:
        best = None
        for key in ready:
            o = si.jobs[key[0]].ops[key[1]]
            for m, p in o.p.items():
                c = est(key, m) + p
                if best is None or c < best[0] or (c == best[0] and (m, key) < (best[1], best[2])):
                    best = (c, m, key)
        assert best is not None
        c_star, m_star, _ = best
        conflict = [k for k in ready if m_star in si.jobs[k[0]].ops[k[1]].p and est(k, m_star) < c_star]
        conflict.sort(key=lambda k: (rank.get(k, 1e18), k))
        chosen = conflict[0]
        o = si.jobs[chosen[0]].ops[chosen[1]]
        g = o.group
        members = [chosen]
        if si.is_batch(g):
            for k2 in conflict[1:]:
                if len(members) >= si.batch_max[g]:
                    break
                if si.jobs[k2[0]].ops[k2[1]].recipe == o.recipe:
                    members.append(k2)
        setup = si.setup[g] if (last_recipe[m_star] is not None and last_recipe[m_star] != o.recipe) else 0
        start = max(max(ready[k] for k in members), free_at[m_star] + setup)
        dur = max(si.jobs[k[0]].ops[k[1]].p[m_star] for k in members)
        batch_id += 1
        for k in members:
            ok = si.jobs[k[0]].ops[k[1]]
            sched.start[k] = start
            sched.end[k] = start + (dur if si.is_batch(g) else ok.p[m_star])
            sched.machine[k] = m_star
            sched.batch[k] = batch_id
            del ready[k]
            if k[1] + 1 < len(si.jobs[k[0]].ops):
                ready[(k[0], k[1] + 1)] = sched.end[k] + si.tau
        free_at[m_star] = start + dur
        last_recipe[m_star] = o.recipe
    return sched


def decode_nondelay(si: StaticInstance, rank: dict[tuple[int, int], float],
                    qtime_hold: bool = True) -> Schedule:
    """Non-delay list scheduling (dispatching-rule emulation): whenever a machine
    can start, the ready operation with the lowest ``rank`` goes first; batch
    tools take up to K same-recipe ready operations; machine choice avoids
    setups, then earliest completion. With ``qtime_hold`` an operation that
    opens a Q-time window is held while no machine of the next group can take
    it in time (how fabs gate lots into Q-time zones).
    """
    sched = Schedule()
    free_at = {m: 0 for m in si.machines}
    last_recipe: dict[int, int | None] = {m: None for m in si.machines}
    ready: dict[tuple[int, int], int] = {(j.id, 0): j.release for j in si.jobs}
    batch_id = 0

    def place(key: tuple[int, int], m: int, t: int, members: list[tuple[int, int]]) -> None:
        nonlocal batch_id
        o = si.jobs[key[0]].ops[key[1]]
        g = o.group
        setup = si.setup[g] if (last_recipe[m] is not None and last_recipe[m] != o.recipe) else 0
        start = t + setup
        dur = max(si.jobs[k[0]].ops[k[1]].p[m] for k in members)
        batch_id += 1
        for k in members:
            ok = si.jobs[k[0]].ops[k[1]]
            sched.start[k] = start
            sched.end[k] = start + (dur if si.is_batch(g) else ok.p[m])
            sched.machine[k] = m
            sched.batch[k] = batch_id
            del ready[k]
            if k[1] + 1 < len(si.jobs[k[0]].ops):
                ready[(k[0], k[1] + 1)] = sched.end[k] + si.tau
        free_at[m] = start + dur
        last_recipe[m] = o.recipe

    while ready:
        t = min(min(max(r, free_at[m]) for m in si.jobs[k[0]].ops[k[1]].p) for k, r in ready.items())
        cands = [k for k, r in ready.items() if r <= t
                 and any(free_at[m] <= t for m in si.jobs[k[0]].ops[k[1]].p)]
        cands.sort(key=lambda k: (rank.get(k, 1e18), k))
        progressed = False
        for key in cands:
            if key not in ready:
                continue
            o = si.jobs[key[0]].ops[key[1]]
            free = [m for m in o.p if free_at[m] <= t]
            if not free:
                continue
            g = o.group
            if qtime_hold and o.qtime is not None and len(cands) > 1:
                nxt = si.jobs[key[0]].ops[key[1] + 1]
                soonest = min(free_at[m] for m in nxt.p)
                if soonest > t + min(o.p[m] for m in free) + si.tau + o.qtime:
                    continue
            m = min(free, key=lambda m: (
                0 if (si.setup[g] == 0 or last_recipe[m] in (None, o.recipe)) else 1, t + o.p[m], m))
            members = [key]
            if si.is_batch(g):
                for k2 in cands:
                    if len(members) >= si.batch_max[g]:
                        break
                    if k2 != key and k2 in ready:
                        o2 = si.jobs[k2[0]].ops[k2[1]]
                        if o2.group == g and o2.recipe == o.recipe and m in o2.p:
                            members.append(k2)
            place(key, m, t, members)
            progressed = True
        if not progressed:
            key = cands[0]
            o = si.jobs[key[0]].ops[key[1]]
            m = min((m for m in o.p if free_at[m] <= t), key=lambda m: (t + o.p[m], m))
            place(key, m, t, [key])
    return sched


def decode_best(si: StaticInstance, rank: dict[tuple[int, int], float]) -> Schedule:
    """Decode with both schemes and keep the better (penalised) schedule."""
    a = decode(si, rank)
    b = decode_nondelay(si, rank)
    return a if evaluate(si, a) <= evaluate(si, b) else b


def rule_rank(si: StaticInstance, rule: str) -> dict[tuple[int, int], float]:
    """Static priority ranks emulating classic dispatching rules."""
    rank: dict[tuple[int, int], float] = {}
    pbar = sum(min(o.p.values()) for o in si.ops) / max(1, len(si.ops))
    for j in si.jobs:
        rem = [0] * (len(j.ops) + 1)
        for k in range(len(j.ops) - 1, -1, -1):
            rem[k] = rem[k + 1] + min(j.ops[k].p.values())
        done = 0
        for o in j.ops:
            p = min(o.p.values())
            hot = 0.0 if j.weight > 1 else 1e9
            v: float
            if rule == "FIFO":
                v = j.release + done
            elif rule == "EDD":
                v = j.due
            elif rule == "SPT":
                v = p
            elif rule == "CR":
                v = (j.due - j.release - done) / max(rem[o.k], 1)
            elif rule == "ODD":
                v = j.release + (j.due - j.release) * (done + p) / max(rem[0], 1)
            elif rule == "ATC":
                import math
                est = j.release + done * 1.5
                slack = max(0.0, j.due - rem[o.k] - est)
                v = -(j.weight / p) * math.exp(-slack / (2.0 * pbar))
            else:
                raise ValueError(rule)
            rank[(j.id, o.k)] = hot + v
            done += p
    return rank


def evaluate(si: StaticInstance, sched: Schedule, q_penalty: float = 1000.0) -> float:
    """Heuristic objective: weighted tardiness + penalty per Q-time violation."""
    return weighted_tardiness(si, sched) + q_penalty * qtime_violations(si, sched)
