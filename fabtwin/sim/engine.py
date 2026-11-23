"""Discrete-event simulation of the fab (own event engine, no SimPy).

The engine executes a dispatching policy on an :class:`Instance` under
uncertainty: lognormal processing-time noise, Weibull failures with lognormal
repairs (preempt-resume), metrology rework, Q-time expiry and random hot lots.

Common random numbers (CRN): every random quantity comes from a dedicated
stream keyed by ``(seed, source, entity)`` -- one stream per lot (processing
noise, rework draws), per machine (failures, batch noise) and one for hot-lot
arrivals. Two policies run with the same seed therefore see the same lots,
the same failure clocks and largely the same processing times, so paired
differences between policies have much lower variance.

Simplifications (documented in the README):
* Failures run on calendar time and restart after each repair (renewal).
* A failure during setup or processing pauses the job; it resumes afterwards.
* Transport is a constant delay here; the OHT layer replaces it later.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from fabtwin.core.dispatch import RULES, Candidate, rank_key
from fabtwin.core.instance import Instance


class MState(IntEnum):
    IDLE = 0
    SETUP = 1
    BUSY = 2
    DOWN = 3
    PM = 4


class Ev(IntEnum):
    RELEASE = 0
    HOT = 1
    ARRIVE = 2
    SETUP_END = 3
    END = 4
    FAIL = 5
    REPAIR = 6
    WAKE = 7
    QEXPIRE = 8
    SAMPLE = 9


@dataclass(frozen=True)
class SimConfig:
    """Policy and uncertainty switches for one simulation run."""

    rule: str = "FIFO"
    seed: int = 0
    stochastic: bool = True
    failures: bool = True
    rework: bool = True
    hot_lots: bool = True
    qtime_guard_h: float = 1.0  # start a partial furnace batch this close to a Q-time deadline
    qtime_max_reworks: int = 2  # a lot violating Q-time more often than this is scrapped
    horizon_h: float | None = None
    warmup_h: float | None = None
    sample_every_h: float = 24.0
    record_ops: bool = False
    record_events: bool = False


@dataclass
class OpRecord:
    """One executed operation (a lot on a machine), for feasibility checks."""

    lot: int
    product: int
    step: int
    machine: int
    batch_id: int
    recipe: int
    ready: float  # arrival in queue
    setup_start: float
    setup_h: float
    proc_start: float = math.nan
    end: float = math.nan


class Lot:
    __slots__ = (
        "id", "product", "step", "release", "due", "weight", "hot", "q_arrival",
        "q_deadline", "q_origin", "q_token", "in_transit", "expired", "done", "rng",
        "reworks", "qviol", "scrapped",
    )

    def __init__(self, lid: int, product: int, release: float, due: float,
                 weight: float, hot: bool, rng: random.Random) -> None:
        self.id = lid
        self.product = product
        self.step = 0
        self.release = release
        self.due = due
        self.weight = weight
        self.hot = hot
        self.q_arrival = release
        self.q_deadline: float | None = None
        self.q_origin = -1
        self.q_token = 0
        self.in_transit = False
        self.expired = False
        self.done: float | None = None
        self.rng = rng
        self.reworks = 0
        self.qviol = 0
        self.scrapped: float | None = None


class Mach:
    __slots__ = (
        "id", "group", "speed", "state", "since", "last_recipe", "batch", "token",
        "phase_end", "pending_proc", "resume_phase", "remaining", "acc", "rng_fail",
        "rng_batch", "ops",
    )

    def __init__(self, mid: int, group: int, speed: float, seed: int) -> None:
        self.id = mid
        self.group = group
        self.speed = speed
        self.state = MState.IDLE
        self.since = 0.0
        self.last_recipe: int | None = None
        self.batch: list[Lot] = []
        self.token = 0
        self.phase_end = 0.0
        self.pending_proc = 0.0
        self.resume_phase: MState | None = None
        self.remaining = 0.0
        self.acc = [0.0] * len(MState)
        self.rng_fail = stream(seed, "fail", mid)
        self.rng_batch = stream(seed, "batch", mid)
        self.ops: list[OpRecord] = []


def stream(seed: int, source: str, idx: int) -> random.Random:
    """Independent, reproducible random stream for one entity."""
    return random.Random(f"fabtwin:{seed}:{source}:{idx}")


def lognormal_factor(rng: random.Random, cv: float) -> float:
    """Multiplicative noise with mean 1 and coefficient of variation ``cv``."""
    if cv <= 0:
        return 1.0
    s2 = math.log(1.0 + cv * cv)
    return rng.lognormvariate(-0.5 * s2, math.sqrt(s2))


@dataclass
class SimResult:
    """KPIs plus optional traces of one run."""

    kpis: dict[str, float]
    group_util: dict[str, dict[str, float]]
    wip_series: list[tuple[float, int]]
    ops: list[OpRecord] = field(default_factory=list)
    events: list[tuple[float, str, int, int, float]] = field(default_factory=list)
    lots: list[dict[str, Any]] = field(default_factory=list)


class Simulator:
    """Event-driven fab simulator. Use :func:`simulate` for one-shot runs."""

    def __init__(self, inst: Instance, cfg: SimConfig) -> None:
        if cfg.rule not in RULES:
            raise ValueError(f"unknown rule {cfg.rule!r}; choose from {sorted(RULES)}")
        self.inst = inst
        self.cfg = cfg
        self.rule = RULES[cfg.rule]
        self.T = cfg.horizon_h if cfg.horizon_h is not None else inst.horizon_h
        self.W = cfg.warmup_h if cfg.warmup_h is not None else inst.warmup_h
        if not 0 <= self.W < self.T:
            raise ValueError("need 0 <= warm-up < horizon")
        self.now = 0.0
        self.heap: list[tuple[float, int, int, int, int]] = []
        self.seq = 0
        self.machines = [Mach(m.id, m.group, m.speed, cfg.seed) for m in inst.machines]
        self.queues: list[list[Lot]] = [[] for _ in inst.groups]
        self.next_wake: list[float | None] = [None] * len(inst.groups)
        self.lots: list[Lot] = []
        self.rem = [p.remaining_work() for p in inst.products]
        self.raw = [p.raw_process_h for p in inst.products]
        self.elig = [[frozenset(s.eligible) for s in p.route] for p in inst.products]
        self.batch_seq = 0
        # statistics
        self.wip = 0
        self.wip_last_t = 0.0
        self.wip_area_win = 0.0
        self.wip_area_full = 0.0
        self.wip_series: list[tuple[float, int]] = []
        self.q_opened_win = 0
        self.q_viol_win = 0
        self.q_viol_total = 0
        self.failures_win = 0
        self.batch_starts_win = 0
        self.batch_lots_win = 0
        self.batch_cap = max(g.batch_max for g in inst.groups)
        self.events: list[tuple[float, str, int, int, float]] = []
        # release bookkeeping (smooth weighted round-robin for the product mix)
        self.wrr = [0.0] * len(inst.products)
        self.rng_hot = stream(cfg.seed, "hot", 0)
        self.rng_rel = stream(cfg.seed, "release", 0)

    # ------------------------------------------------------------- event queue
    def _push(self, t: float, kind: Ev, a: int = 0, b: int = 0) -> None:
        self.seq += 1
        heapq.heappush(self.heap, (t, self.seq, int(kind), a, b))

    def _log(self, kind: str, lot: int = -1, machine: int = -1, x: float = 0.0) -> None:
        if self.cfg.record_events:
            self.events.append((self.now, kind, lot, machine, x))

    def _in_win(self, t: float) -> bool:
        return self.W <= t <= self.T

    # -------------------------------------------------------------- accounting
    def _overlap(self, a: float, b: float) -> float:
        return max(0.0, min(b, self.T) - max(a, self.W))

    def _set_state(self, m: Mach, s: MState) -> None:
        m.acc[m.state] += self._overlap(m.since, self.now)
        m.since = self.now
        m.state = s

    def _wip_change(self, delta: int) -> None:
        self.wip_area_win += self.wip * self._overlap(self.wip_last_t, self.now)
        self.wip_area_full += self.wip * max(0.0, min(self.now, self.T) - self.wip_last_t)
        self.wip_last_t = self.now
        self.wip += delta

    # --------------------------------------------------------------------- run
    def run(self) -> SimResult:
        inst, cfg = self.inst, self.cfg
        self._push(0.0, Ev.RELEASE)
        if cfg.hot_lots and inst.hot_lot_rate_per_h > 0:
            self._push(self.rng_hot.expovariate(inst.hot_lot_rate_per_h), Ev.HOT)
        if cfg.failures:
            for m in self.machines:
                f = inst.groups[m.group].failure
                if f is not None:
                    self._push(m.rng_fail.weibullvariate(f.weibull_scale, f.weibull_shape),
                               Ev.FAIL, m.id)
        self._push(0.0, Ev.SAMPLE)
        handlers = {
            Ev.RELEASE: self._on_release, Ev.HOT: self._on_hot, Ev.ARRIVE: self._on_arrive,
            Ev.SETUP_END: self._on_setup_end, Ev.END: self._on_end, Ev.FAIL: self._on_fail,
            Ev.REPAIR: self._on_repair, Ev.WAKE: self._on_wake, Ev.QEXPIRE: self._on_qexpire,
            Ev.SAMPLE: self._on_sample,
        }
        while self.heap:
            t, _, kind, a, b = heapq.heappop(self.heap)
            if t > self.T:
                break
            self.now = t
            handlers[Ev(kind)](a, b)
        self.now = self.T
        self._wip_change(0)
        for m in self.machines:
            self._set_state(m, m.state)
        return self._result()

    # ---------------------------------------------------------------- releases
    def _new_lot(self, product: int, hot: bool) -> None:
        inst = self.inst
        ff = inst.hot_flow_factor if hot else inst.flow_factor
        lid = len(self.lots)
        lot = Lot(lid, product, self.now, self.now + ff * self.raw[product],
                  inst.hot_weight if hot else 1.0, hot, stream(self.cfg.seed, "lot", lid))
        self.lots.append(lot)
        self._wip_change(+1)
        self._log("release", lid, -1, 1.0 if hot else 0.0)
        self._push(self.now, Ev.ARRIVE, lid)

    def _on_release(self, a: int, b: int) -> None:
        mix = [p.mix for p in self.inst.products]
        for i, w in enumerate(mix):
            self.wrr[i] += w
        p = max(range(len(mix)), key=lambda i: (self.wrr[i], -i))
        self.wrr[p] -= 1.0
        self._new_lot(p, hot=False)
        mean = 1.0 / self.inst.release_rate_per_h
        cv = self.inst.release_cv
        gap = mean if cv <= 0 else self.rng_rel.gammavariate(1.0 / cv**2, mean * cv**2)
        self._push(self.now + gap, Ev.RELEASE)

    def _on_hot(self, a: int, b: int) -> None:
        r = self.rng_hot.random()
        acc, p = 0.0, len(self.inst.products) - 1
        for i, prod in enumerate(self.inst.products):
            acc += prod.mix
            if r < acc:
                p = i
                break
        self._new_lot(p, hot=True)
        self._push(self.now + self.rng_hot.expovariate(self.inst.hot_lot_rate_per_h), Ev.HOT)

    # ------------------------------------------------------------- lot motion
    def _on_arrive(self, lid: int, b: int) -> None:
        lot = self.lots[lid]
        if lot.scrapped is not None:
            return
        lot.in_transit = False
        if lot.expired:
            lot.expired = False
            self._send(lot, lot.q_origin)
            return
        lot.q_arrival = self.now
        g = self.inst.products[lot.product].route[lot.step].group
        self.queues[g].append(lot)
        self._log("arrive", lid, g, float(lot.step))
        self._dispatch(g)

    def _send(self, lot: Lot, step: int) -> None:
        lot.step = step
        lot.in_transit = True
        self._push(self.now + self.inst.transport_h, Ev.ARRIVE, lot.id)

    def _complete(self, lot: Lot) -> None:
        prod = self.inst.products[lot.product]
        k = lot.step
        s = prod.route[k]
        nxt = k + 1
        if s.rework_prob > 0:
            u = lot.rng.random()  # always drawn: keeps the lot stream in sync (CRN)
            if self.cfg.rework and u < s.rework_prob and s.rework_to is not None:
                nxt = s.rework_to
                lot.reworks += 1
                self._log("rework", lot.id, -1, float(nxt))
        if nxt == len(prod.route):
            lot.done = self.now
            self._wip_change(-1)
            self._log("done", lot.id)
            return
        if s.qtime_max_h is not None and nxt == k + 1:
            lot.q_deadline = self.now + s.qtime_max_h
            lot.q_origin = k
            lot.q_token += 1
            if self._in_win(self.now):
                self.q_opened_win += 1
            self._push(lot.q_deadline, Ev.QEXPIRE, lot.id, lot.q_token)
        self._send(lot, nxt)

    def _on_qexpire(self, lid: int, token: int) -> None:
        lot = self.lots[lid]
        if token != lot.q_token or lot.q_deadline is None:
            return
        lot.q_deadline = None
        lot.qviol += 1
        self.q_viol_total += 1
        if self._in_win(self.now):
            self.q_viol_win += 1
        self._log("qviol", lid, -1, float(lot.q_origin))
        if lot.qviol > self.cfg.qtime_max_reworks:
            self._scrap(lot)
            return
        if lot.in_transit:
            lot.expired = True
            return
        g = self.inst.products[lot.product].route[lot.step].group
        self.queues[g].remove(lot)
        self._send(lot, lot.q_origin)

    def _scrap(self, lot: Lot) -> None:
        lot.scrapped = self.now
        lot.q_token += 1
        if lot.in_transit:
            lot.expired = False
            lot.q_token += 1
        else:
            g = self.inst.products[lot.product].route[lot.step].group
            self.queues[g].remove(lot)
        self._wip_change(-1)
        self._log("scrap", lot.id)

    # --------------------------------------------------------------- dispatch
    def _candidate(self, lot: Lot) -> Candidate:
        prod = self.inst.products[lot.product]
        rem = self.rem[lot.product]
        return Candidate(
            lot_id=lot.id, hot=lot.hot, weight=lot.weight, q_arrival=lot.q_arrival,
            release=lot.release, due=lot.due, proc_h=prod.route[lot.step].proc_h,
            rem_work_h=rem[lot.step], done_work_h=self.raw[lot.product] - rem[lot.step],
            flow_factor=self.inst.hot_flow_factor if lot.hot else self.inst.flow_factor,
            q_deadline=lot.q_deadline,
        )

    def _dispatch(self, g: int) -> None:
        queue = self.queues[g]
        if not queue:
            return
        group = self.inst.groups[g]
        idle = [self.machines[m] for m in group.machines
                if self.machines[m].state == MState.IDLE]
        if not idle:
            return
        idle.sort(key=lambda m: (-m.speed, m.id))
        cands = [self._candidate(lot) for lot in queue]
        pbar = sum(c.proc_h for c in cands) / len(cands)
        key = rank_key(self.rule, self.now, pbar)
        if group.is_batch:
            self._dispatch_batch(g, idle, cands, key)
            return
        cands.sort(key=key)
        by_id = {lot.id: lot for lot in queue}
        for c in cands:
            if not idle:
                break
            lot = by_id[c.lot_id]
            step = self.inst.products[lot.product].route[lot.step]
            elig = self.elig[lot.product][lot.step]
            options = [m for m in idle if m.id in elig]
            if not options:
                continue
            # machine choice: avoid a setup if possible, then fastest
            m = min(options, key=lambda m: (m.last_recipe != step.recipe, -m.speed, m.id))
            idle.remove(m)
            queue.remove(lot)
            self._start(m, [lot], step.recipe)

    def _dispatch_batch(self, g: int, idle: list[Mach], cands: list[Candidate],
                        key: Any) -> None:
        group = self.inst.groups[g]
        queue = self.queues[g]
        by_id = {lot.id: lot for lot in queue}
        for m in idle:
            by_recipe: dict[int, list[Candidate]] = {}
            for c in cands:
                lot = by_id.get(c.lot_id)
                if lot is None or m.id not in self.elig[lot.product][lot.step]:
                    continue
                r = self.inst.products[lot.product].route[lot.step].recipe
                by_recipe.setdefault(r, []).append(c)
            best: tuple[Any, int, int, list[Candidate]] | None = None
            wake = math.inf
            for r, cs in by_recipe.items():
                cs.sort(key=key)
                batch = cs[: group.batch_max]
                oldest = min(c.q_arrival for c in cs)
                qdl = min((c.q_deadline for c in cs if c.q_deadline is not None),
                          default=math.inf)
                ready = (
                    len(batch) >= group.min_batch
                    or any(c.hot for c in batch)
                    or self.now - oldest >= group.max_batch_wait_h - 1e-9
                    or qdl - self.now <= self.cfg.qtime_guard_h + 1e-9
                )
                if ready:
                    cand = (key(batch[0]), -len(batch), r, batch)
                    if best is None or cand[:3] < best[:3]:
                        best = cand
                else:
                    wake = min(wake, oldest + group.max_batch_wait_h,
                               qdl - self.cfg.qtime_guard_h)
            if best is None:
                if wake < math.inf:
                    self._schedule_wake(g, max(wake, self.now))
                continue
            _, _, recipe, batch = best
            lots = [by_id.pop(c.lot_id) for c in batch]
            for lot in lots:
                queue.remove(lot)
            self._start(m, lots, recipe)

    def _schedule_wake(self, g: int, t: float) -> None:
        nw = self.next_wake[g]
        if nw is None or t < nw - 1e-9:
            self.next_wake[g] = t
            self._push(t, Ev.WAKE, g)

    def _on_wake(self, g: int, b: int) -> None:
        nw = self.next_wake[g]
        if nw is not None and abs(nw - self.now) < 1e-9:
            self.next_wake[g] = None
            self._dispatch(g)

    # ---------------------------------------------------------------- machines
    def _start(self, m: Mach, lots: list[Lot], recipe: int) -> None:
        group = self.inst.groups[m.group]
        for lot in lots:
            if lot.q_deadline is not None:  # Q-time met: close the window
                lot.q_deadline = None
                lot.q_token += 1
        setup = group.setup_h if (m.last_recipe is not None and m.last_recipe != recipe) else 0.0
        m.last_recipe = recipe
        steps = [self.inst.products[lot.product].route[lot.step] for lot in lots]
        if group.is_batch:
            if self._in_win(self.now):
                self.batch_starts_win += 1
                self.batch_lots_win += len(lots)
            base = max(s.proc_h for s in steps)
            noise = lognormal_factor(m.rng_batch, steps[0].proc_cv) if self.cfg.stochastic else 1.0
        else:
            base = steps[0].proc_h
            noise = lognormal_factor(lots[0].rng, steps[0].proc_cv) if self.cfg.stochastic else 1.0
        m.pending_proc = base * noise / m.speed
        m.batch = lots
        self.batch_seq += 1
        if self.cfg.record_ops:
            for lot in lots:
                m.ops.append(OpRecord(lot.id, lot.product, lot.step, m.id, self.batch_seq,
                                      recipe, lot.q_arrival, self.now, setup))
        self._log("start", lots[0].id, m.id, float(len(lots)))
        m.token += 1
        if setup > 0:
            self._set_state(m, MState.SETUP)
            m.phase_end = self.now + setup
            self._push(m.phase_end, Ev.SETUP_END, m.id, m.token)
        else:
            self._begin_proc(m)

    def _begin_proc(self, m: Mach) -> None:
        self._set_state(m, MState.BUSY)
        m.phase_end = self.now + m.pending_proc
        if self.cfg.record_ops:
            for op in m.ops[-len(m.batch):]:
                op.proc_start = self.now
        self._push(m.phase_end, Ev.END, m.id, m.token)

    def _on_setup_end(self, mid: int, token: int) -> None:
        m = self.machines[mid]
        if token == m.token and m.state == MState.SETUP:
            self._begin_proc(m)

    def _on_end(self, mid: int, token: int) -> None:
        m = self.machines[mid]
        if token != m.token or m.state != MState.BUSY:
            return
        lots, m.batch = m.batch, []
        if self.cfg.record_ops:
            for op in m.ops[-len(lots):]:
                op.end = self.now
        self._set_state(m, MState.IDLE)
        self._log("end", lots[0].id, m.id, float(len(lots)))
        for lot in lots:
            self._complete(lot)
        self._dispatch(m.group)

    def _on_fail(self, mid: int, b: int) -> None:
        m = self.machines[mid]
        f = self.inst.groups[m.group].failure
        assert f is not None
        if m.state in (MState.SETUP, MState.BUSY):
            m.resume_phase = m.state
            m.remaining = m.phase_end - self.now
            m.token += 1
        else:
            m.resume_phase = None
        self._set_state(m, MState.DOWN)
        if self._in_win(self.now):
            self.failures_win += 1
        self._log("fail", -1, mid)
        repair = f.mttr_h * lognormal_factor(m.rng_fail, f.repair_cv)
        self._push(self.now + repair, Ev.REPAIR, mid)

    def _on_repair(self, mid: int, b: int) -> None:
        m = self.machines[mid]
        f = self.inst.groups[m.group].failure
        assert f is not None
        self._log("repair", -1, mid)
        if m.resume_phase is not None:
            phase = m.resume_phase
            m.resume_phase = None
            m.token += 1
            self._set_state(m, phase)
            m.phase_end = self.now + m.remaining
            self._push(m.phase_end, Ev.SETUP_END if phase == MState.SETUP else Ev.END,
                       mid, m.token)
        else:
            self._set_state(m, MState.IDLE)
            self._dispatch(m.group)
        self._push(self.now + m.rng_fail.weibullvariate(f.weibull_scale, f.weibull_shape),
                   Ev.FAIL, mid)

    def _on_sample(self, a: int, b: int) -> None:
        self.wip_series.append((self.now, self.wip))
        self._push(self.now + self.cfg.sample_every_h, Ev.SAMPLE)

    # ----------------------------------------------------------------- results
    def _result(self) -> SimResult:
        inst, W, T = self.inst, self.W, self.T
        span = T - W
        done = [lot for lot in self.lots if lot.done is not None and W <= lot.done <= T]
        n = len(done)
        ct = [lot.done - lot.release for lot in done if lot.done is not None]
        tard = [max(0.0, lot.done - lot.due) for lot in done if lot.done is not None]
        wt = [lot.weight * t for lot, t in zip(done, tard)]
        hot_ct = [c for lot, c in zip(done, ct) if lot.hot]
        late_wip = sum(1 for lot in self.lots
                       if lot.done is None and lot.scrapped is None and lot.due < T)
        scrapped = [lot for lot in self.lots
                    if lot.scrapped is not None and W <= lot.scrapped <= T]
        # Little's Law over all departures (completions and scraps)
        sojourn = ct + [lot.scrapped - lot.release for lot in scrapped
                        if lot.scrapped is not None]
        n_dep = len(sojourn)
        mean_ct = sum(ct) / n if n else math.nan
        L = self.wip_area_win / span
        lam = n / span
        kpis: dict[str, float] = {
            "lots_done": float(n),
            "throughput_per_day": lam * 24.0,
            "mean_ct_h": mean_ct,
            "mean_ct_days": mean_ct / 24.0,
            "hot_mean_ct_h": sum(hot_ct) / len(hot_ct) if hot_ct else math.nan,
            "x_factor": (sum(c / self.raw[lot.product] for lot, c in zip(done, ct)) / n
                         if n else math.nan),
            "mean_tardiness_h": sum(tard) / n if n else math.nan,
            "mean_weighted_tardiness_h": sum(wt) / n if n else math.nan,
            "on_time_pct": 100.0 * sum(1 for t in tard if t <= 0) / n if n else math.nan,
            "avg_wip": L,
            "little_wip": (n_dep / span) * (sum(sojourn) / n_dep) if n_dep else math.nan,
            "scrapped": float(len(scrapped)),
            "qtime_windows": float(self.q_opened_win),
            "qtime_violations": float(self.q_viol_win),
            "qtime_viol_pct": (100.0 * self.q_viol_win / self.q_opened_win
                               if self.q_opened_win else 0.0),
            "failures": float(self.failures_win),
            "late_wip_at_end": float(late_wip),
            "released": float(len(self.lots)),
            "wip_area_full": self.wip_area_full,
        }
        group_util: dict[str, dict[str, float]] = {}
        for g in inst.groups:
            ms = [self.machines[i] for i in g.machines]
            frac = {s.name.lower(): sum(m.acc[s] for m in ms) / (span * len(ms)) for s in MState}
            group_util[g.name] = frac
        litho = [group_util[g.name] for g in inst.groups if g.kind == "litho"]
        kpis["litho_util"] = max((f["busy"] + f["setup"] for f in litho), default=math.nan)
        kpis["litho_setup_frac"] = max((f["setup"] for f in litho), default=math.nan)
        kpis["furnace_batch_fill"] = (self.batch_lots_win / (self.batch_starts_win * self.batch_cap)
                                      if self.batch_starts_win else math.nan)
        kpis["max_util"] = max(f["busy"] + f["setup"] for f in group_util.values())
        lots_out = [
            {"id": lot.id, "product": lot.product, "hot": lot.hot, "release": lot.release,
             "due": lot.due, "done": lot.done, "scrapped": lot.scrapped,
             "reworks": lot.reworks, "qviol": lot.qviol}
            for lot in self.lots
        ]
        ops = [op for m in self.machines for op in m.ops]
        return SimResult(kpis, group_util, self.wip_series, ops, self.events, lots_out)


def simulate(inst: Instance, cfg: SimConfig | None = None, **overrides: Any) -> SimResult:
    """Run one replication. ``overrides`` are applied on top of ``cfg``."""
    base = cfg or SimConfig()
    if overrides:
        base = SimConfig(**{**base.__dict__, **overrides})
    return Simulator(inst, base).run()
