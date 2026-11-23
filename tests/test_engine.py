"""Simulator invariants: schedule feasibility, Little's Law, CRN, determinism."""

from __future__ import annotations

from collections import defaultdict

import pytest

from fabtwin.core.generator import generate
from fabtwin.core.instance import Instance
from fabtwin.sim.engine import OpRecord, SimConfig, SimResult, simulate

EPS = 1e-6


@pytest.fixture(scope="module")
def tiny() -> Instance:
    return generate("tiny", seed=3)


@pytest.fixture(scope="module", params=["FIFO", "CR", "ATC"])
def traced(request: pytest.FixtureRequest, tiny: Instance) -> tuple[Instance, SimResult]:
    cfg = SimConfig(rule=request.param, seed=7, record_ops=True, record_events=True,
                    horizon_h=30 * 24, warmup_h=5 * 24)
    return tiny, simulate(tiny, cfg)


def _batches(ops: list[OpRecord]) -> dict[int, list[list[OpRecord]]]:
    by_m: dict[int, dict[int, list[OpRecord]]] = defaultdict(dict)
    for op in ops:
        by_m[op.machine].setdefault(op.batch_id, []).append(op)
    return {m: sorted(b.values(), key=lambda x: x[0].setup_start) for m, b in by_m.items()}


def test_machine_capacity_and_batching(traced: tuple[Instance, SimResult]) -> None:
    inst, res = traced
    assert res.ops
    for m, batches in _batches(res.ops).items():
        g = inst.groups[inst.machines[m].group]
        prev_end = -1.0
        for b in batches:
            assert len(b) <= g.batch_max
            assert len({op.recipe for op in b}) == 1, "mixed recipes in a batch"
            assert len({(op.setup_start, op.end) for op in b}) == 1
            assert b[0].setup_start >= prev_end - EPS, f"overlap on machine {m}"
            if b[0].end == b[0].end:  # finished (not NaN)
                prev_end = b[0].end
            else:
                prev_end = float("inf")


def test_eligibility_and_recipes(traced: tuple[Instance, SimResult]) -> None:
    inst, res = traced
    for op in res.ops:
        step = inst.products[op.product].route[op.step]
        assert op.machine in step.eligible
        assert op.recipe == step.recipe
        assert inst.machines[op.machine].group == step.group


def test_setups_follow_recipe_changes(traced: tuple[Instance, SimResult]) -> None:
    inst, res = traced
    for m, batches in _batches(res.ops).items():
        g = inst.groups[inst.machines[m].group]
        last = None
        for b in batches:
            expected = g.setup_h if (last is not None and last != b[0].recipe) else 0.0
            assert b[0].setup_h == pytest.approx(expected)
            assert b[0].proc_start != b[0].proc_start or b[0].proc_start >= b[0].setup_start + b[0].setup_h - EPS
            last = b[0].recipe


def test_precedence_transport_and_qtime(traced: tuple[Instance, SimResult]) -> None:
    inst, res = traced
    by_lot: dict[int, list[OpRecord]] = defaultdict(list)
    for op in res.ops:
        by_lot[op.lot].append(op)
    for ops in by_lot.values():
        ops.sort(key=lambda o: o.setup_start)
        assert ops[0].step == 0
        for a, b in zip(ops, ops[1:]):
            assert b.ready >= a.end + inst.transport_h - EPS
            route = inst.products[a.product].route
            q = route[a.step].qtime_max_h
            if q is not None and b.step == a.step + 1:
                assert b.setup_start - a.end <= q + EPS, "Q-time exceeded without violation"
            # the next step is either the successor, a rework target or a Q-time re-clean
            ok = {a.step + 1, a.step}
            if route[a.step].rework_to is not None:
                ok.add(route[a.step].rework_to)  # type: ignore[arg-type]
            assert b.step in ok


def test_no_start_while_down(traced: tuple[Instance, SimResult]) -> None:
    _, res = traced
    down: dict[int, float | None] = defaultdict(lambda: None)
    for t, kind, lot, m, _x in res.events:
        if kind == "fail":
            assert down[m] is None
            down[m] = t
        elif kind == "repair":
            down[m] = None
        elif kind == "start":
            assert down[m] is None, f"machine {m} started while down at {t}"


def test_wip_area_identity(traced: tuple[Instance, SimResult]) -> None:
    inst, res = traced
    T = 30 * 24
    def exit_t(lot: dict[str, float | None]) -> float:
        t = lot["done"] if lot["done"] is not None else lot["scrapped"]
        return T if t is None else min(t, T)

    area = sum(exit_t(lot) - lot["release"] for lot in res.lots)  # type: ignore[operator]
    assert res.kpis["wip_area_full"] == pytest.approx(area, rel=1e-9)


def test_littles_law_steady_state() -> None:
    inst = generate("tiny", seed=1)
    for seed in (1, 2):
        k = simulate(inst, rule="FIFO", seed=seed, horizon_h=300 * 24, warmup_h=50 * 24).kpis
        assert k["little_wip"] == pytest.approx(k["avg_wip"], rel=0.03)
        # stability: output rate matches input rate (regular + hot lots)
        lam_in = 24 * (inst.release_rate_per_h + inst.hot_lot_rate_per_h)
        assert k["throughput_per_day"] == pytest.approx(lam_in, rel=0.05)


def test_deterministic_given_seed(tiny: Instance) -> None:
    a = simulate(tiny, rule="CR", seed=11, horizon_h=20 * 24, warmup_h=2 * 24).kpis
    b = simulate(tiny, rule="CR", seed=11, horizon_h=20 * 24, warmup_h=2 * 24).kpis
    assert a == b


def test_common_random_numbers_share_arrivals(tiny: Instance) -> None:
    cfg = dict(seed=5, horizon_h=20 * 24, warmup_h=2 * 24)
    ra = simulate(tiny, rule="FIFO", **cfg)  # type: ignore[arg-type]
    rb = simulate(tiny, rule="ATC", **cfg)  # type: ignore[arg-type]
    arr_a = [(lot["release"], lot["product"], lot["hot"]) for lot in ra.lots]
    arr_b = [(lot["release"], lot["product"], lot["hot"]) for lot in rb.lots]
    assert arr_a == arr_b
    assert ra.kpis["failures"] == pytest.approx(rb.kpis["failures"], abs=3)


def test_nominal_mode_processing_times(tiny: Instance) -> None:
    res = simulate(tiny, rule="FIFO", stochastic=False, failures=False, rework=False,
                   hot_lots=False, record_ops=True, horizon_h=10 * 24, warmup_h=24)
    assert res.kpis["failures"] == 0
    for b in _batches(res.ops).values():
        for ops in b:
            op = ops[0]
            if op.end != op.end:
                continue
            step = tiny.products[op.product].route[op.step]
            g = tiny.groups[step.group]
            base = max(tiny.products[o.product].route[o.step].proc_h for o in ops) if g.is_batch else step.proc_h
            assert op.end - op.proc_start == pytest.approx(base / tiny.machines[op.machine].speed)


def test_qtime_violations_rework_then_scrap() -> None:
    inst = generate("tiny", seed=0)
    # an absurdly tight Q-time forces violations; lots must still finish
    tight = Instance.from_dict({
        **inst.to_dict(),
        "products": [
            {**p, "route": [{**s, "qtime_max_h": 0.01 if s["qtime_max_h"] else None}
                            for s in p["route"]]}
            for p in inst.to_dict()["products"]
        ],
    })
    res = simulate(tight, rule="FIFO", seed=2, record_events=True,
                   horizon_h=40 * 24, warmup_h=5 * 24)
    # transport alone exceeds the window: every lot is re-cleaned, then scrapped
    assert res.kpis["qtime_violations"] > 0
    assert res.kpis["scrapped"] > 0
    assert res.kpis["lots_done"] == 0
    assert all(lot["qviol"] <= 3 for lot in res.lots)
    assert res.kpis["little_wip"] == pytest.approx(res.kpis["avg_wip"], rel=0.2)


def test_rework_happens_and_bad_rule_rejected(tiny: Instance) -> None:
    res = simulate(tiny, rule="EDD", seed=3, horizon_h=60 * 24, warmup_h=5 * 24)
    assert sum(lot["reworks"] for lot in res.lots) > 0
    with pytest.raises(ValueError):
        simulate(tiny, rule="NOPE")
    with pytest.raises(ValueError):
        simulate(tiny, horizon_h=10.0, warmup_h=20.0)


@pytest.mark.parametrize("rule", ["FIFO", "SPT", "EDD", "ODD", "CR", "ATC"])
def test_all_rules_run(tiny: Instance, rule: str) -> None:
    k = simulate(tiny, rule=rule, seed=1, horizon_h=20 * 24, warmup_h=2 * 24).kpis
    assert k["lots_done"] > 0
    assert 0 <= k["on_time_pct"] <= 100
    assert 0 < k["litho_util"] <= 1
