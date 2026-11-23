"""Replicated experiments with common random numbers, run in parallel."""

from __future__ import annotations

import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from fabtwin.core.instance import Instance
from fabtwin.sim.engine import SimConfig, simulate
from fabtwin.sim.stats import CI, mean_ci, relative_change_ci


@dataclass
class Replications:
    """KPI samples of one policy: ``kpis[name][r]`` for replication r."""

    policy: str
    seeds: list[int]
    kpis: dict[str, list[float]]
    wip_series: list[list[float]]

    def ci(self, kpi: str, level: float = 0.95) -> CI:
        return mean_ci(self.kpis[kpi], level)


def _one(args: tuple[str, SimConfig]) -> tuple[dict[str, float], list[float]]:
    inst_json, cfg = args
    planner = None
    if cfg.plan_every_h > 0:  # rolling-horizon CP-SAT litho planning
        from fabtwin.core.rolling import LithoPlanner

        planner = LithoPlanner()
    res = simulate(_cached(inst_json), cfg, planner=planner)
    return res.kpis, [float(n) for _, n in res.wip_series]


_CACHE: dict[int, Instance] = {}


def _cached(inst_json: str) -> Instance:
    key = hash(inst_json)
    if key not in _CACHE:
        _CACHE[key] = Instance.from_json(inst_json)
    return _CACHE[key]


def replicate(inst: Instance, cfg: SimConfig, n: int, seed0: int = 1,
              workers: int | None = None, label: str | None = None) -> Replications:
    """Run ``n`` replications with seeds ``seed0 .. seed0+n-1``.

    Using the same ``seed0`` for two policies gives common random numbers.
    """
    seeds = list(range(seed0, seed0 + n))
    jobs = [(inst.to_json(), replace(cfg, seed=s)) for s in seeds]
    workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 1)
    if workers == 1:
        out = [_one(j) for j in jobs]
    else:
        with ProcessPoolExecutor(workers) as ex:
            out = list(ex.map(_one, jobs, chunksize=max(1, n // (4 * workers))))
    names = out[0][0].keys()
    kpis = {k: [o[0][k] for o in out] for k in names}
    return Replications(label or cfg.rule, seeds, kpis, [o[1] for o in out])


def compare_table(reps: Sequence[Replications], kpis: Sequence[str],
                  baseline: str | None = None) -> list[dict[str, Any]]:
    """Rows of mean ± CI per policy, plus paired % change vs ``baseline``."""
    base = next((r for r in reps if r.policy == baseline), None)
    rows = []
    for r in reps:
        row: dict[str, Any] = {"policy": r.policy}
        for k in kpis:
            c = r.ci(k)
            row[k] = (c.mean, c.half_width)
            if base is not None and r is not base:
                d = relative_change_ci(r.kpis[k], base.kpis[k])
                row[f"{k}_vs_{baseline}_pct"] = (d.mean, d.half_width)
        rows.append(row)
    return rows
