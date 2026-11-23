"""Export a simulation trace as a compact JSON replay for the browser twin.

The schema is documented in ``web/DATA_FORMAT.md``. Times are hours since the
start of the simulation, rounded to 1e-4 h (0.36 s).
"""

from __future__ import annotations

import bisect
import math
from typing import Any

from fabtwin.core.instance import Instance
from fabtwin.core.layout import build_layout
from fabtwin.sim.engine import MState, SimConfig, SimResult

R = 4


def _r(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(x, R)


def kpi_series(res: SimResult, inst: Instance, t0: float, t1: float,
               step_h: float = 0.25, window_h: float = 24.0) -> dict[str, list[float]]:
    """Ticking KPIs for the replay: WIP and rolling 24 h throughput, CT, on-time,
    litho utilisation (busy + setup share of litho machine time)."""
    lots = res.lots
    releases = sorted(lot["release"] for lot in lots)
    exits = sorted(lot["done"] if lot["done"] is not None else lot["scrapped"]
                   for lot in lots if lot["done"] is not None or lot["scrapped"] is not None)
    done = sorted((lot["done"], lot["done"] - lot["release"], lot["done"] <= lot["due"])
                  for lot in lots if lot["done"] is not None)
    done_t = [d[0] for d in done]
    litho = {m for g in inst.groups if g.kind == "litho" for m in g.machines}
    # litho productive-time intervals from the machine state trace
    mst = res.trace.get("mstate", [])
    cur: dict[int, tuple[float, int]] = {}
    busy_iv: list[tuple[float, float]] = []
    for t, m, s in mst:
        if m not in litho:
            continue
        if m in cur and cur[m][1] in (int(MState.BUSY), int(MState.SETUP)):
            busy_iv.append((cur[m][0], t))
        cur[m] = (t, s)
    for m, (t, s) in cur.items():
        if s in (int(MState.BUSY), int(MState.SETUP)):
            busy_iv.append((t, t1))

    def busy_in(a: float, b: float) -> float:
        return sum(max(0.0, min(e, b) - max(s, a)) for s, e in busy_iv)

    out: dict[str, list[float]] = {"t": [], "wip": [], "thr": [], "ct": [], "ontime": [],
                                   "litho": []}
    t = t0
    while t <= t1 + 1e-9:
        wip = bisect.bisect_right(releases, t) - bisect.bisect_right(exits, t)
        lo, hi = bisect.bisect_right(done_t, t - window_h), bisect.bisect_right(done_t, t)
        recent = done[lo:hi]
        out["t"].append(round(t, R))
        out["wip"].append(wip)
        out["thr"].append(round(len(recent) * 24.0 / window_h, 3))
        out["ct"].append(round(sum(r[1] for r in recent) / len(recent) / 24.0, 4) if recent else 0.0)
        out["ontime"].append(round(100.0 * sum(r[2] for r in recent) / len(recent), 2) if recent else 100.0)
        a = max(t0, t - window_h)
        out["litho"].append(round(busy_in(a, t) / (len(litho) * (t - a)), 4) if t > a else 0.0)
        t += step_h
    return out


def export_replay(inst: Instance, cfg: SimConfig, res: SimResult, scenario: dict[str, Any]) -> dict[str, Any]:
    """Build the replay document for one run (trace must have been recorded)."""
    tr = res.trace
    if not tr:
        raise ValueError("run the simulation with trace_from_h set")
    t0, t1 = tr["t0"], tr["t1"]
    layout = build_layout(inst)
    alive = {lid for _, lid, _, _ in tr["lotloc"]}
    lots = [[lot["id"], lot["product"], int(lot["hot"]), _r(lot["release"]), _r(lot["due"]),
             _r(lot["done"]), _r(lot["scrapped"])]
            for lot in res.lots if lot["id"] in alive]
    ops = [[op.lot, op.step, op.machine, _r(op.setup_start), _r(op.proc_start), _r(op.end),
            op.recipe, op.batch_id]
           for op in res.ops
           if op.lot in alive and (op.end != op.end or op.end >= t0 - 48) and op.setup_start <= t1]
    ops.sort(key=lambda o: (o[3] or 0.0))
    ev_types = {"fail", "repair", "qviol", "pm", "pm_end", "scrap"}
    events = [[_r(t), k, lot, m] for t, k, lot, m, _ in res.events if t0 <= t <= t1 and k in ev_types]
    hot_rel = [[_r(lot["release"]), "hot", lot["id"], -1] for lot in res.lots
               if lot["hot"] and t0 <= lot["release"] <= t1]
    events = sorted(events + hot_rel, key=lambda e: e[0] or 0.0)
    vehicles = [[[leg_lot, [[_r(t), n] for t, n in pts]] for leg_lot, pts in legs
                 if pts and pts[-1][0] >= t0 and pts[0][0] <= t1]
                for legs in tr["vehicles"]]
    return {
        "version": 1,
        "meta": {
            **scenario,
            "instance": inst.name,
            "seed": cfg.seed,
            "rule": cfg.rule,
            "transport": cfg.transport,
            "t0": t0,
            "t1": t1,
            "kpis_full_run": {k: (None if isinstance(v, float) and math.isnan(v) else round(v, 4))
                              for k, v in res.kpis.items()},
            "generated_by": "scripts/export_scenarios.py",
        },
        "layout": layout.to_dict(inst),
        "groups": [{"id": g.id, "name": g.name, "kind": g.kind.value, "batch_max": g.batch_max,
                    "setup_h": g.setup_h, "machines": list(g.machines)} for g in inst.groups],
        "products": [{"id": p.id, "name": p.name,
                      "steps": [[s.group, s.recipe, s.proc_h, int(s.qtime_max_h is not None), s.layer]
                                for s in p.route]}
                     for p in inst.products],
        "lots": lots,
        "mstate": [[_r(t), m, s] for t, m, s in tr["mstate"]],
        "lotloc": [[_r(t), lid, k, i] for t, lid, k, i in tr["lotloc"]],
        "qtime": [[int(q[0]), _r(q[1]), _r(q[2]), _r(q[3]), int(q[4])] for q in tr["qtime"]],
        "vehicles": vehicles,
        "ops": ops,
        "events": events,
        "series": kpi_series(res, inst, t0, t1),
    }
