"""Layout, OHT transport, PM in the simulator, rolling planner and replay export."""

from __future__ import annotations

import json
from collections import defaultdict

import pytest

from fabtwin.core.generator import generate
from fabtwin.core.instance import Instance
from fabtwin.core.layout import build_layout, strongly_connected
from fabtwin.core.maintenance import nominal_plan
from fabtwin.core.rolling import LithoPlanner
from fabtwin.sim.engine import Loc, SimConfig, simulate
from fabtwin.sim.export import export_replay
from fabtwin.sim.oht import OHTConfig


@pytest.fixture(scope="module")
def tiny() -> Instance:
    return generate("tiny", seed=2)


@pytest.mark.parametrize("preset", ["tiny", "medium", "large"])
def test_layout_strongly_connected(preset: str) -> None:
    inst = generate(preset, seed=0)
    lay = build_layout(inst)
    assert strongly_connected(lay.graph)
    assert len(lay.bays) == len(inst.groups) and len(lay.tools) == len(inst.machines)
    ports = [t.port for t in lay.tools]
    assert len(set(ports)) == len(ports)
    path, cost = lay.graph.astar(lay.tools[0].port, lay.bays[-1].stocker)
    assert path and cost > 0
    assert lay.graph.astar(3, 3) == ([], 0.0)
    d = lay.to_dict(inst)
    assert len(d["machines"]) == len(inst.machines)


@pytest.mark.parametrize("policy", ["nearest", "hungarian"])
def test_oht_run_and_vehicle_invariants(tiny: Instance, policy: str) -> None:
    cfg = SimConfig(rule="ATC", seed=4, transport="oht", oht=OHTConfig(n_vehicles=3, policy=policy),
                    horizon_h=8 * 24, warmup_h=24, trace_from_h=2 * 24, trace_to_h=4 * 24,
                    record_events=True)
    res = simulate(tiny, cfg)
    k = res.kpis
    assert k["oht_moves"] > 0 and 0 < k["oht_vehicle_util"] < 1
    assert k["oht_mean_transport_min"] >= k["oht_mean_wait_min"] >= 0
    assert k["lots_done"] > 0
    # vehicle waypoints are time-ordered and follow rail edges
    lay = build_layout(tiny)
    edges = set(lay.graph.edges)
    for legs in res.trace["vehicles"]:
        last_t = -1.0
        for _lot, pts in legs:
            for (t1, n1), (t2, n2) in zip(pts, pts[1:]):
                assert t2 >= t1 - 1e-9
                assert n1 == n2 or (n1, n2) in edges
            assert pts[0][0] >= last_t - 1e-9
            last_t = pts[-1][0]
    # headway: no two vehicles enter the same edge within less than the headway
    enters: dict[tuple[int, int], list[float]] = defaultdict(list)
    for legs in res.trace["vehicles"]:
        for _lot, pts in legs:
            for (t1, n1), (t2, n2) in zip(pts, pts[1:]):
                if n1 != n2:
                    enters[(n1, n2)].append(t1)
    hw = OHTConfig().headway_m / (OHTConfig().speed_mps * 3600)
    for ts in enters.values():
        ts.sort()
        assert all(b - a >= hw - 1e-6 for a, b in zip(ts, ts[1:]))


def test_lot_locations_consistent(tiny: Instance) -> None:
    res = simulate(tiny, SimConfig(rule="FIFO", seed=1, transport="oht", horizon_h=6 * 24,
                                   warmup_h=24, trace_from_h=24, trace_to_h=5 * 24))
    kinds = {k for _, _, k, _ in res.trace["lotloc"]}
    assert {int(Loc.QUEUE), int(Loc.MACHINE), int(Loc.VEHICLE)} <= kinds
    assert int(Loc.TRANSIT) not in kinds
    mst = res.trace["mstate"]
    assert all(a[0] <= b[0] for a, b in zip(mst, mst[1:]))


def test_pm_reduces_failures_and_validates(tiny: Instance) -> None:
    plan = nominal_plan(tiny)
    a = simulate(tiny, rule="ATC", seed=3, horizon_h=90 * 24, warmup_h=10 * 24)
    b = simulate(tiny, rule="ATC", seed=3, horizon_h=90 * 24, warmup_h=10 * 24, pm_interval_h=plan)
    assert b.kpis["pm_count"] > 0 and b.kpis["pm_frac"] > 0
    assert b.kpis["failures"] < a.kpis["failures"]
    with pytest.raises(ValueError):
        simulate(tiny, pm_interval_h=(100.0,))
    with pytest.raises(ValueError):
        simulate(tiny, transport="teleport")
    with pytest.raises(ValueError):
        simulate(tiny, transport="oht", oht=OHTConfig(policy="random"))


def test_rolling_planner_runs(tiny: Instance) -> None:
    pl = LithoPlanner(time_limit_s=0.3)
    res = simulate(tiny, SimConfig(rule="ATCS", seed=2, plan_every_h=12.0, horizon_h=6 * 24,
                                   warmup_h=24), planner=pl)
    assert pl.calls >= 10 and res.kpis["lots_done"] > 0


def test_export_replay_schema(tiny: Instance) -> None:
    cfg = SimConfig(rule="ATCS", seed=5, transport="oht", record_events=True,
                    horizon_h=5 * 24, warmup_h=24, trace_from_h=2 * 24, trace_to_h=3 * 24)
    res = simulate(tiny, cfg)
    doc = export_replay(tiny, cfg, res, {"id": "t", "title": "test"})
    text = json.dumps(doc)
    assert "NaN" not in text
    for key in ("meta", "layout", "groups", "products", "lots", "mstate", "lotloc", "qtime",
                "vehicles", "ops", "events", "series"):
        assert key in doc
    s = doc["series"]
    assert len(s["t"]) == len(s["wip"]) == len(s["litho"]) > 10
    assert all(0 <= u <= 1.0001 for u in s["litho"])
    with pytest.raises(ValueError):
        export_replay(tiny, cfg, simulate(tiny, rule="FIFO", horizon_h=48, warmup_h=12), {})
