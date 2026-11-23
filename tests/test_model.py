"""Instance model, generator, dispatch rules and statistics."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from fabtwin.core import dispatch as D
from fabtwin.core.generator import PRESETS, generate
from fabtwin.core.instance import Instance, ToolKind
from fabtwin.sim.engine import SimConfig
from fabtwin.sim.experiment import compare_table, replicate
from fabtwin.sim.stats import mean_ci, mser, paired_diff_ci, relative_change_ci


@pytest.mark.parametrize("preset", ["tiny", "medium", "large"])
def test_presets_generate_valid(preset: str) -> None:
    inst = generate(preset, seed=0)
    inst.validate()
    n_steps = [len(p.route) for p in inst.products]
    assert all(s >= 10 for s in n_steps)
    assert all(1 <= len(g.machines) <= 6 for g in inst.groups)
    assert any(g.is_batch for g in inst.groups)
    # re-entrancy: litho is visited once per layer
    p = inst.products[0]
    litho = [s for s in p.route if inst.groups[s.group].kind is ToolKind.LITHO]
    assert len(litho) == len({s.layer for s in p.route})
    # litho is the designed bottleneck
    util = inst.nominal_utilization(fill=1.0, setup_prob=1.0)
    lith = max(u for g, u in zip(inst.groups, util) if g.kind is ToolKind.LITHO)
    assert lith == max(u for g, u in zip(inst.groups, util) if not g.is_batch)


def test_large_preset_in_spec() -> None:
    inst = generate("large", seed=1)
    assert 10 <= len(inst.groups) <= 40
    assert max(len(p.route) for p in inst.products) <= 200


def test_generator_deterministic_and_json_roundtrip() -> None:
    a = generate("medium", seed=4)
    assert a == generate("medium", seed=4)
    assert a != generate("medium", seed=5)
    b = Instance.from_json(a.to_json())
    assert b == a


def test_generator_rejects_infeasible_sizing() -> None:
    with pytest.raises(ValueError):
        generate(replace(PRESETS["medium"], max_machines=2), seed=0)


def test_validate_catches_errors() -> None:
    inst = generate("tiny", seed=0)
    d = inst.to_dict()
    bad = Instance.from_dict({**d, "warmup_h": d["horizon_h"] + 1})
    with pytest.raises(ValueError):
        bad.validate()
    d2 = inst.to_dict()
    d2["products"][0]["mix"] = 0.9
    with pytest.raises(ValueError):
        Instance.from_dict(d2).validate()
    d3 = inst.to_dict()
    d3["products"][0]["route"][0]["eligible"] = [999]
    with pytest.raises(ValueError):
        Instance.from_dict(d3).validate()


def test_failure_model_moments() -> None:
    f = generate("tiny", seed=0).groups[0].failure
    assert f is not None
    mean = f.weibull_scale * math.gamma(1 + 1 / f.weibull_shape)
    assert mean == pytest.approx(f.mtbf_h)
    assert 0 < f.availability < 1


def _c(**kw: float | bool | None) -> D.Candidate:
    base = dict(lot_id=0, hot=False, weight=1.0, q_arrival=0.0, release=0.0, due=100.0,
                proc_h=1.0, rem_work_h=10.0, done_work_h=5.0, flow_factor=2.0, q_deadline=None)
    base.update(kw)
    return D.Candidate(**base)  # type: ignore[arg-type]


def test_dispatch_rules_order() -> None:
    now, pbar = 50.0, 1.0
    early, late = _c(due=60.0, lot_id=1), _c(due=200.0, lot_id=2)
    assert D.edd(early, now, pbar) < D.edd(late, now, pbar)
    assert D.critical_ratio(early, now, pbar) < D.critical_ratio(late, now, pbar)
    assert D.atc(early, now, pbar) < D.atc(late, now, pbar)
    assert D.spt(_c(proc_h=0.5), now, pbar) < D.spt(_c(proc_h=2.0), now, pbar)
    assert D.fifo(_c(q_arrival=1.0), now, pbar) < D.fifo(_c(q_arrival=2.0), now, pbar)
    assert D.odd(_c(done_work_h=1.0), now, pbar) < D.odd(_c(done_work_h=9.0), now, pbar)
    key = D.rank_key(D.fifo, now, pbar)
    hot = _c(hot=True, q_arrival=99.0, lot_id=3)
    assert sorted([early, hot], key=key)[0] is hot


def test_stats_helpers() -> None:
    ci = mean_ci([1.0, 2.0, 3.0, 4.0])
    assert ci.mean == pytest.approx(2.5)
    assert ci.lo < 2.5 < ci.hi and ci.n == 4
    assert "±" in str(ci)
    assert math.isinf(mean_ci([1.0]).half_width)
    assert mean_ci([]).n == 0
    d = paired_diff_ci([2.0, 3.0, 4.0], [1.0, 2.0, 3.5])
    assert d.mean == pytest.approx(0.8333333)
    with pytest.raises(ValueError):
        paired_diff_ci([1.0], [1.0, 2.0])
    r = relative_change_ci([9.0, 9.0], [10.0, 10.0])
    assert r.mean == pytest.approx(-10.0)
    # warm-up: an initial transient is truncated
    series = [float(i) for i in range(50)] + [50.0] * 200
    assert 30 <= mser(series) <= 60
    assert mser([1.0] * 10) == 0


def test_replicate_and_compare() -> None:
    inst = generate("tiny", seed=0)
    cfg = SimConfig(horizon_h=15 * 24, warmup_h=2 * 24)
    a = replicate(inst, replace(cfg, rule="FIFO"), n=3, workers=1)
    b = replicate(inst, replace(cfg, rule="ATC"), n=3, workers=2)
    assert a.seeds == b.seeds == [1, 2, 3]
    assert a.ci("throughput_per_day").n == 3
    rows = compare_table([a, b], ["mean_ct_h"], baseline="FIFO")
    assert "mean_ct_h_vs_FIFO_pct" in rows[1]
