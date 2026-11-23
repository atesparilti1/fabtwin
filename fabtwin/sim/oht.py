"""Overhead hoist transport (OHT): vehicle dispatching, routing, reservations.

Dispatching
    At every decision epoch (a new request or a vehicle becoming free) the
    idle vehicles and waiting requests form an assignment problem solved with
    the Hungarian algorithm (``scipy.optimize.linear_sum_assignment``). The cost
    of vehicle v for request r is the empty travel time to the pickup minus a
    priority credit for hot lots, open Q-time windows and waiting time. The
    baseline ``nearest`` policy serves requests first-come-first-served, each
    with the nearest idle vehicle.

Routing
    A* on the directed rail graph. Edge cost = free travel time plus the delay
    already booked on that edge (congestion-aware); the Euclidean heuristic
    stays admissible because costs never drop below free travel time.

Reservations / deadlock avoidance
    A vehicle books its whole trip before it moves. Each rail edge keeps the
    earliest next entry and exit times; a booking enters no earlier than one
    headway after the previous vehicle and exits no earlier than one headway
    after it (no overtaking). If a vehicle has to wait before entering an edge,
    the exit booking of the edge it is waiting on is extended. Every booking
    is a finite time window fixed at planning time, so no circular wait (and
    hence no deadlock) can occur, and vehicle spacing never drops below the
    headway. Idle vehicles park on stocker spurs off the running rail.

Simplifications: point vehicles with constant speed (no acceleration), a lot
is delivered to the destination bay's stocker, and the stocker-to-tool hand-off
is instantaneous.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import linear_sum_assignment

from fabtwin.core.layout import FabLayout

if TYPE_CHECKING:
    from fabtwin.sim.engine import Simulator


@dataclass(frozen=True)
class OHTConfig:
    n_vehicles: int = 10
    policy: str = "hungarian"  # or "nearest"
    speed_mps: float = 3.0
    headway_m: float = 4.0
    load_s: float = 15.0
    unload_s: float = 15.0
    hot_credit_s: float = 120.0
    qtime_credit_s: float = 90.0
    age_credit_per_min: float = 2.0  # seconds of credit per minute waited


@dataclass
class Request:
    lot: int
    src: int
    dst: int
    t_req: float
    hot: bool
    qtime: bool


@dataclass
class Vehicle:
    id: int
    node: int
    busy: bool = False
    busy_h: float = 0.0
    legs: list[tuple[int, list[tuple[float, int]]]] = field(default_factory=list)


class OHT:
    """Transport system attached to a :class:`Simulator`."""

    def __init__(self, sim: Simulator, layout: FabLayout, cfg: OHTConfig) -> None:
        if cfg.policy not in ("hungarian", "nearest"):
            raise ValueError(f"unknown OHT policy {cfg.policy!r}")
        self.sim = sim
        self.G = layout.graph
        self.cfg = cfg
        self.v_mph = cfg.speed_mps * 3600.0
        self.headway = cfg.headway_m / self.v_mph
        self.free = [self.G.length(e) / self.v_mph for e in range(len(self.G.edges))]
        self.next_in = [0.0] * len(self.G.edges)
        self.next_out = [0.0] * len(self.G.edges)
        stockers = [b.stocker for b in layout.bays]
        self.vehicles = [Vehicle(i, stockers[i % len(stockers)]) for i in range(cfg.n_vehicles)]
        self.pending: list[Request] = []
        self.epoch_scheduled = False
        self.dist = self._all_pairs()
        # statistics (window only)
        self.n_moves = 0
        self.sum_transport = 0.0
        self.sum_wait = 0.0
        self.sum_empty = 0.0
        self.sum_blocked = 0.0
        self.max_wait = 0.0

    def _all_pairs(self) -> np.ndarray:
        n = len(self.G.nodes)
        D = np.full((n, n), math.inf)
        for s in range(n):
            D[s, s] = 0.0
            pq = [(0.0, s)]
            while pq:
                d, u = heapq.heappop(pq)
                if d > D[s, u]:
                    continue
                for e, v in self.G.out[u]:
                    nd = d + self.free[e]
                    if nd < D[s, v]:
                        D[s, v] = nd
                        heapq.heappush(pq, (nd, v))
        return D

    # ---------------------------------------------------------------- requests
    def request(self, lot: int, src: int, dst: int, hot: bool, qtime: bool) -> None:
        self.pending.append(Request(lot, src, dst, self.sim.now, hot, qtime))
        self._schedule_epoch()

    def cancel(self, lot: int) -> bool:
        """Drop a not-yet-assigned request (e.g. the lot was scrapped)."""
        for i, r in enumerate(self.pending):
            if r.lot == lot:
                del self.pending[i]
                return True
        return False

    def _schedule_epoch(self) -> None:
        if not self.epoch_scheduled:
            self.epoch_scheduled = True
            from fabtwin.sim.engine import Ev

            self.sim._push(self.sim.now, Ev.OHT_EPOCH)

    def on_epoch(self) -> None:
        self.epoch_scheduled = False
        idle = [v for v in self.vehicles if not v.busy]
        if not idle or not self.pending:
            return
        now = self.sim.now
        if self.cfg.policy == "nearest":
            pairs = []
            free = list(idle)
            for r in sorted(self.pending, key=lambda r: r.t_req):
                if not free:
                    break
                v = min(free, key=lambda v: (self.dist[v.node, r.src], v.id))
                free.remove(v)
                pairs.append((v, r))
        else:
            C = np.empty((len(idle), len(self.pending)))
            for j, r in enumerate(self.pending):
                credit = (self.cfg.hot_credit_s * r.hot + self.cfg.qtime_credit_s * r.qtime
                          + self.cfg.age_credit_per_min * (now - r.t_req) * 60.0) / 3600.0
                for i, v in enumerate(idle):
                    C[i, j] = self.dist[v.node, r.src] - credit
            rows, cols = linear_sum_assignment(C)
            pairs = [(idle[i], self.pending[j]) for i, j in zip(rows, cols)]
        for v, r in pairs:
            self.pending.remove(r)
            self._dispatch(v, r)

    # ----------------------------------------------------------------- moving
    def _book(self, src: int, dst: int, t: float) -> tuple[float, list[tuple[float, int]], float]:
        """Route src->dst departing at t; book edges. Returns (arrival, waypoints, blocked)."""
        if src == dst:
            return t, [(t, src)], 0.0
        now = self.sim.now
        cost = [self.free[e] + max(0.0, self.next_in[e] - now) for e in range(len(self.free))]
        path, _ = self.G.astar(src, dst, cost)
        pts = [(t, src)]
        blocked = 0.0
        prev: int | None = None
        for e in path:
            t_in = max(t, self.next_in[e])
            if t_in > t:
                blocked += t_in - t
                if prev is not None:  # we keep occupying the previous edge while waiting
                    self.next_out[prev] = max(self.next_out[prev], t_in + self.headway)
            t_out = max(t_in + self.free[e], self.next_out[e])
            self.next_in[e] = t_in + self.headway
            self.next_out[e] = t_out + self.headway
            if t_in > t:
                pts.append((t_in, self.G.edges[e][0]))
            pts.append((t_out, self.G.edges[e][1]))
            t = t_out
            prev = e
        return t, pts, blocked

    def _dispatch(self, v: Vehicle, r: Request) -> None:
        from fabtwin.sim.engine import Ev

        now = self.sim.now
        v.busy = True
        t_at_src, pts1, b1 = self._book(v.node, r.src, now)
        t_pick = t_at_src + self.cfg.load_s / 3600.0
        t_at_dst, pts2, b2 = self._book(r.src, r.dst, t_pick)
        t_drop = t_at_dst + self.cfg.unload_s / 3600.0
        v.node = r.dst
        sim = self.sim
        if sim._in_win(now):
            self.n_moves += 1
            self.sum_transport += t_drop - r.t_req
            self.sum_wait += t_pick - r.t_req
            self.max_wait = max(self.max_wait, t_pick - r.t_req)
            self.sum_empty += t_at_src - now
            self.sum_blocked += b1 + b2
        v.busy_h += sim._overlap(now, t_drop)
        if sim.tracing:
            v.legs.append((-1, pts1))
            v.legs.append((r.lot, [(t_pick, r.src)] + pts2[1:] + [(t_drop, r.dst)]))
        sim._push(t_pick, Ev.OHT_PICK, r.lot, v.id)
        sim._push(t_drop, Ev.OHT_DONE, r.lot, v.id)

    def on_done(self, lot: int, vid: int) -> None:
        self.vehicles[vid].busy = False
        self._schedule_epoch()

    # ----------------------------------------------------------------- results
    def kpis(self, span_h: float) -> dict[str, float]:
        n = max(self.n_moves, 1)
        return {
            "oht_moves": float(self.n_moves),
            "oht_mean_transport_min": 60.0 * self.sum_transport / n,
            "oht_mean_wait_min": 60.0 * self.sum_wait / n,
            "oht_max_wait_min": 60.0 * self.max_wait,
            "oht_mean_empty_min": 60.0 * self.sum_empty / n,
            "oht_blocked_s_per_move": 3600.0 * self.sum_blocked / n,
            "oht_vehicle_util": sum(v.busy_h for v in self.vehicles) / (span_h * len(self.vehicles)),
        }
