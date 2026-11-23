"""Classic dispatching rules.

A rule maps a waiting lot to a *score*; lower scores are dispatched first.
Hot lots always precede normal lots (a fab-wide policy), so a rule only orders
lots within the same priority class. Ties break on queue arrival, then lot id.

Rules
-----
FIFO   queue arrival time.
SPT    processing time of the current step.
EDD    lot due date.
ODD    operation due date: release + FF * (raw work up to and including this
       step); spreads the lot due date over the route.
CR     critical ratio (d - t) / remaining work; < 1 means behind schedule.
ATC    apparent tardiness cost (Vepsalainen & Morton, 1987):
       I = (w / p) * exp(-max(0, d - p_rem - t) / (k * p_bar)); score = -I.
ATCS   ATC with a setup term, applied machine-first on setup tools (litho,
       implant) so the reticle already loaded counts.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Candidate:
    """What a rule may look at when ranking one waiting lot."""

    lot_id: int
    hot: bool
    weight: float
    q_arrival: float
    release: float
    due: float
    proc_h: float
    rem_work_h: float  # nominal work of this step and all later steps
    done_work_h: float  # nominal work of all earlier steps
    flow_factor: float
    q_deadline: float | None  # latest start time for this step (Q-time), if any


ScoreFn = Callable[[Candidate, float, float], float]
"""(candidate, now, mean proc time in queue) -> score (lower = first)."""


def fifo(c: Candidate, now: float, pbar: float) -> float:
    return c.q_arrival


def spt(c: Candidate, now: float, pbar: float) -> float:
    return c.proc_h


def edd(c: Candidate, now: float, pbar: float) -> float:
    return c.due


def odd(c: Candidate, now: float, pbar: float) -> float:
    return c.release + c.flow_factor * (c.done_work_h + c.proc_h)


def critical_ratio(c: Candidate, now: float, pbar: float) -> float:
    return (c.due - now) / max(c.rem_work_h, 1e-9)


ATC_K = 2.0


def atc(c: Candidate, now: float, pbar: float) -> float:
    slack = max(0.0, c.due - c.rem_work_h - now)
    return -(c.weight / c.proc_h) * math.exp(-slack / (ATC_K * max(pbar, 1e-9)))


ATCS_K2 = 0.5


def atcs(c: Candidate, now: float, pbar: float, setup_h: float, sbar: float) -> float:
    """ATC with setups (Lee, Bhaskaran & Pinedo, 1997); score = -index.

    I = (w / p) exp(-max(0, d - p_rem - t) / (k1 p_bar)) exp(-s / (k2 s_bar)).
    Used machine-first, since the setup depends on the machine's last recipe.
    """
    slack = max(0.0, c.due - c.rem_work_h - now)
    idx = (c.weight / c.proc_h) * math.exp(-slack / (ATC_K * max(pbar, 1e-9)))
    if sbar > 0:
        idx *= math.exp(-setup_h / (ATCS_K2 * sbar))
    return -idx


RULES: dict[str, ScoreFn] = {
    "FIFO": fifo,
    "SPT": spt,
    "EDD": edd,
    "ODD": odd,
    "CR": critical_ratio,
    "ATC": atc,
    "ATCS": atc,  # lot-first fallback; setup-aware (machine-first) on setup tools
}

SETUP_RULES = frozenset({"ATCS"})


def rank_key(rule: ScoreFn, now: float, pbar: float) -> Callable[[Candidate], tuple[int, float, float, int]]:
    """Sort key: hot class first, then rule score, arrival, id."""

    def key(c: Candidate) -> tuple[int, float, float, int]:
        return (0 if c.hot else 1, rule(c, now, pbar), c.q_arrival, c.lot_id)

    return key
