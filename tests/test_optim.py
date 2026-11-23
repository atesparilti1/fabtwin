"""Exact models, heuristics and maintenance optimisation."""

from __future__ import annotations

import math

import pytest

from fabtwin.core.alns import solve_alns
from fabtwin.core.cpsat import solve_cpsat
from fabtwin.core.decomposition import LithoTask, solve_decomposition, solve_litho
from fabtwin.core.generator import generate
from fabtwin.core.maintenance import downtime_fraction, nominal_plan, nominal_tau, scaled_plan, screen
from fabtwin.core.mip import solve_mip
from fabtwin.core.static import (
    check_schedule,
    decode,
    decode_best,
    decode_nondelay,
    evaluate,
    make_static,
    qtime_violations,
    rule_rank,
    total_flow,
    weighted_tardiness,
)


@pytest.fixture(scope="module")
def si():  # type: ignore[no-untyped-def]
    return make_static(5, 6, seed=1, due_factor=1.25, release_spread_h=1.0)


def test_static_instance_structure(si) -> None:  # type: ignore[no-untyped-def]
    assert len(si.jobs) == 5 and all(len(j.ops) == 6 for j in si.jobs)
    assert si.horizon > max(j.release for j in si.jobs)
    assert any(si.is_batch(o.group) for o in si.ops) or any(si.setup[o.group] for o in si.ops)


@pytest.mark.parametrize("rule", ["FIFO", "EDD", "SPT", "CR", "ODD", "ATC"])
def test_decoders_feasible(si, rule: str) -> None:  # type: ignore[no-untyped-def]
    rank = rule_rank(si, rule)
    for dec in (decode, decode_nondelay, decode_best):
        s = dec(si, rank)
        assert check_schedule(si, s, qtime_hard=False) == []
        assert evaluate(si, s) >= weighted_tardiness(si, s)
    with pytest.raises(ValueError):
        rule_rank(si, "NOPE")


def test_cpsat_optimal_matches_mip_and_bounds_heuristics(si) -> None:  # type: ignore[no-untyped-def]
    c = solve_cpsat(si, time_limit_s=20)
    assert c.status == "OPTIMAL" and c.schedule is not None
    assert check_schedule(si, c.schedule) == []
    assert c.objective == pytest.approx(weighted_tardiness(si, c.schedule))
    mk = max(decode_nondelay(si, rule_rank(si, "FIFO")).end.values())
    m = solve_mip(si, horizon=int(mk * 1.25) + 5, time_limit_s=60, threads=2)
    assert m.status == "Optimal" and m.schedule is not None
    assert m.objective == pytest.approx(c.objective)
    assert check_schedule(si, m.schedule) == []
    for rule in ("FIFO", "ATC"):
        s = decode_nondelay(si, rule_rank(si, rule))
        assert evaluate(si, s) >= c.objective - 1e-9


def test_cpsat_flow_objective_and_epsilon(si) -> None:  # type: ignore[no-untyped-def]
    f = solve_cpsat(si, time_limit_s=10, objective="flow")
    assert f.schedule is not None and f.objective == pytest.approx(total_flow(si, f.schedule))
    w = solve_cpsat(si, time_limit_s=10, flow_cap=int(f.objective or 0))
    assert w.schedule is not None and total_flow(si, w.schedule) <= (f.objective or 0) + 1e-9
    with pytest.raises(ValueError):
        solve_cpsat(si, objective="bad")
    hinted = solve_cpsat(si, time_limit_s=5, hint=w.schedule)
    assert hinted.objective is not None


def test_alns_never_worse_than_best_rule(si) -> None:  # type: ignore[no-untyped-def]
    best_rule = min(evaluate(si, decode_best(si, rule_rank(si, r))) for r in ("ATC", "EDD", "CR", "FIFO"))
    res = solve_alns(si, seed=3, iters=150, time_limit_s=10)
    assert res.best_obj <= best_rule + 1e-9
    assert check_schedule(si, res.best_schedule, qtime_hard=False) == []
    assert res.history["best"] == sorted(res.history["best"], reverse=True)
    assert res.iterations > 0 and res.op_weights
    assert qtime_violations(si, res.best_schedule) >= 0


def test_decomposition_and_litho_subproblem(si) -> None:  # type: ignore[no-untyped-def]
    d = solve_decomposition(si, sub_time_s=2)
    assert check_schedule(si, d.schedule, qtime_hard=False) == []
    tasks = [LithoTask(i, release=i, due=5, weight=1 + (i == 2) * 9, recipe=i % 2, p={0: 3, 1: 4})
             for i in range(4)]
    plan = solve_litho(tasks, setup=2, initial_recipe={0: 1, 1: None}, machine_free={0: 2, 1: 0})
    assert set(plan) == {0, 1, 2, 3}
    for key, (m, start) in plan.items():
        assert start >= tasks[key].release
        assert m in (0, 1)
    assert solve_litho([], 1, {}, {}) == {}


def test_maintenance_math() -> None:
    inst = generate("medium", seed=0)
    litho = next(g for g in inst.groups if g.kind == "litho")
    f = litho.failure
    assert f is not None
    tau = nominal_tau(f)
    assert tau is not None and 0 < tau < 4 * f.mtbf_h
    assert downtime_fraction(f, tau) < downtime_fraction(f, None)
    assert downtime_fraction(f, None) == pytest.approx(f.mttr_h / (f.mtbf_h + f.mttr_h))
    plan = nominal_plan(inst)
    assert len(plan) == len(inst.groups)
    clean = next(i for i, g in enumerate(inst.groups) if g.kind == "clean")
    assert plan[clean] is None  # shape 1.3 with short repairs: PM never pays
    sp = scaled_plan(inst, plan, 0.5, None)
    li = next(i for i, g in enumerate(inst.groups) if g.kind == "litho")
    assert sp[li] == pytest.approx(round(0.5 * plan[li], 2))  # type: ignore[operator]
    assert all(t is None for g, t in zip(inst.groups, sp) if g.kind != "litho")
    sc = screen([[1.0, 1.1, 0.9, 1.0], [5.0, 5.2, 4.9, 5.1], [1.05, 1.1, 0.95, 1.0]])
    assert sc.best == 0 and 1 not in sc.survivors and 2 in sc.survivors
    assert math.isfinite(downtime_fraction(f, 50.0))
