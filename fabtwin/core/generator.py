"""Synthetic, SMT2020-inspired instance generator with documented parameters.

The public SMT2020 testbed (Kopp et al., 2020) has ~1,000 tools and routes of
300-600 steps, far too large for exact methods and for 200-replication studies
in Python. This generator builds smaller fabs with the same *structure*:
layer-by-layer re-entrant routes (clean, film, litho, metrology, etch, strip,
implant/anneal, CMP), batch furnaces, reticle setups, Q-time windows from
clean to furnace, metrology rework and hot lots. Every number below is an
assumption, and every assumption is stored in ``Instance.params`` so a report
can print exactly what was simulated.

Sizing: the release rate is set so the *litho* groups run at
``target_bottleneck_util`` of their failure-adjusted capacity, counting a
reticle setup on ``sizing_setup_prob`` of litho visits; every other group
gets just enough machines to stay below its own (lower) utilization target.
That makes litho the designed bottleneck, as in real fabs.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field

from fabtwin.core.instance import (
    FailureModel,
    Instance,
    Machine,
    Product,
    Step,
    ToolGroup,
    ToolKind,
)

# Assumed nominal processing time ranges per lot (hours, 25-wafer lot).
# Furnace times are per batch. Sources: order-of-magnitude values used in the
# SMT2020 / MIMAC literature; they are labelled assumptions, not fab data.
PROC_RANGE_H: dict[ToolKind, tuple[float, float]] = {
    ToolKind.LITHO: (0.45, 0.75),
    ToolKind.ETCH: (0.40, 0.90),
    ToolKind.DEP: (0.50, 1.00),
    ToolKind.FURNACE: (3.0, 5.0),
    ToolKind.IMPLANT: (0.60, 1.00),
    ToolKind.CMP: (0.50, 0.90),
    ToolKind.CLEAN: (0.25, 0.45),
    ToolKind.METRO: (0.15, 0.30),
}
PROC_CV: dict[ToolKind, float] = {
    ToolKind.LITHO: 0.05,
    ToolKind.ETCH: 0.10,
    ToolKind.DEP: 0.08,
    ToolKind.FURNACE: 0.03,
    ToolKind.IMPLANT: 0.08,
    ToolKind.CMP: 0.10,
    ToolKind.CLEAN: 0.10,
    ToolKind.METRO: 0.15,
}
SETUP_H: dict[ToolKind, float] = {ToolKind.LITHO: 0.20, ToolKind.IMPLANT: 0.25}
# (MTBF h, Weibull shape, MTTR h, repair CV, PM duration h). Shape > 1 means
# wear-out, so preventive maintenance can pay off; PM is shorter than a repair.
FAILURES: dict[ToolKind, tuple[float, float, float, float, float]] = {
    ToolKind.LITHO: (200.0, 2.2, 10.0, 0.8, 3.0),
    ToolKind.ETCH: (110.0, 1.8, 4.0, 0.8, 1.5),
    ToolKind.DEP: (150.0, 1.6, 4.0, 0.8, 1.5),
    ToolKind.FURNACE: (300.0, 1.5, 8.0, 0.6, 3.0),
    ToolKind.IMPLANT: (130.0, 1.6, 5.0, 0.8, 2.0),
    ToolKind.CMP: (120.0, 1.4, 3.0, 0.8, 1.2),
    ToolKind.CLEAN: (200.0, 1.3, 2.0, 0.6, 1.0),
    ToolKind.METRO: (250.0, 1.2, 2.0, 0.6, 1.0),
}


@dataclass(frozen=True)
class GeneratorConfig:
    """Size and policy knobs of a synthetic fab."""

    name: str = "medium"
    n_products: int = 3
    layers_min: int = 7
    layers_max: int = 9
    groups_per_kind: dict[str, int] = field(
        default_factory=lambda: {
            "litho": 2, "etch": 3, "dep": 2, "furnace": 3,
            "implant": 1, "cmp": 1, "clean": 2, "metro": 2,
        }
    )
    litho_machines: int = 3
    max_machines: int = 6
    target_bottleneck_util: float = 0.95
    other_util_range: tuple[float, float] = (0.55, 0.78)
    furnace_batch_max: int = 6
    furnace_min_batch: int = 3
    furnace_max_wait_h: float = 2.0
    sizing_batch_fill: float = 0.5
    sizing_setup_prob: float = 1.0
    speed_range: tuple[float, float] = (0.9, 1.1)
    qtime_clean_to_furnace_h: float = 4.0
    litho_rework_prob: float = 0.03
    hot_lot_share: float = 0.03
    flow_factor: float = 2.2
    hot_flow_factor: float = 1.6
    hot_weight: float = 10.0
    transport_h: float = 0.1
    release_cv: float = 1.0
    horizon_days: float = 120.0
    warmup_days: float = 30.0
    failures: bool = True


PRESETS: dict[str, GeneratorConfig] = {
    "tiny": GeneratorConfig(
        name="tiny", n_products=2, layers_min=2, layers_max=3,
        groups_per_kind={"litho": 1, "etch": 1, "dep": 1, "furnace": 1,
                         "implant": 1, "cmp": 1, "clean": 1, "metro": 1},
        litho_machines=2, horizon_days=60.0, warmup_days=10.0,
    ),
    "medium": GeneratorConfig(),
    "large": GeneratorConfig(
        name="large", n_products=5, layers_min=12, layers_max=18,
        groups_per_kind={"litho": 4, "etch": 6, "dep": 5, "furnace": 8,
                         "implant": 2, "cmp": 3, "clean": 6, "metro": 4},
        litho_machines=4, horizon_days=150.0, warmup_days=40.0,
    ),
}


def _layer_template(layer: int) -> list[tuple[ToolKind, str]]:
    """Process steps of one mask layer. Tags mark special semantics."""
    t: list[tuple[ToolKind, str]] = [(ToolKind.CLEAN, "pre")]
    t.append((ToolKind.FURNACE, "ox") if layer % 2 == 0 else (ToolKind.DEP, ""))
    t += [(ToolKind.LITHO, ""), (ToolKind.METRO, "ovl"), (ToolKind.ETCH, ""),
          (ToolKind.CLEAN, "strip")]
    if layer % 3 == 1:
        t += [(ToolKind.IMPLANT, ""), (ToolKind.CLEAN, "pre"), (ToolKind.FURNACE, "anneal")]
    if layer % 2 == 1:
        t.append((ToolKind.CMP, ""))
    t.append((ToolKind.METRO, "thk"))
    return t


def generate(cfg: GeneratorConfig | str = "medium", seed: int = 0) -> Instance:
    """Build a validated instance. Same ``cfg`` and ``seed`` give the same fab."""
    if isinstance(cfg, str):
        cfg = PRESETS[cfg]
    rng = random.Random(seed)

    # ---- tool groups (machines are added after sizing)
    kinds: list[tuple[ToolKind, int]] = []  # (kind, index within kind)
    for kname, n in cfg.groups_per_kind.items():
        kinds += [(ToolKind(kname), i) for i in range(n)]
    gid_of: dict[tuple[ToolKind, int], int] = {k: i for i, k in enumerate(kinds)}
    n_per_kind = {ToolKind(k): n for k, n in cfg.groups_per_kind.items()}

    # ---- products and routes (eligibility filled in after machines exist)
    raw_routes: list[list[dict[str, object]]] = []
    kind_load: dict[tuple[ToolKind, int], float] = {k: 0.0 for k in kinds}
    for p in range(cfg.n_products):
        n_layers = rng.randint(cfg.layers_min, cfg.layers_max)
        route: list[dict[str, object]] = []
        for layer in range(n_layers):
            litho_pos = -1
            for kind, tag in _layer_template(layer):
                k = n_per_kind[kind]
                lo, hi = PROC_RANGE_H[kind]
                proc = round(rng.uniform(lo, hi), 2)
                if kind is ToolKind.LITHO:
                    # critical (early) layers on group 0, later layers spread
                    idx = min(k - 1, layer * k // n_layers)
                else:
                    # least-loaded group of this kind so far (balanced areas)
                    idx = min(range(k), key=lambda j: (kind_load[(kind, j)], j))
                kind_load[(kind, idx)] += proc
                step: dict[str, object] = {
                    "group": gid_of[(kind, idx)],
                    "kind": kind,
                    "proc_h": proc,
                    "layer": layer,
                    "qtime": None,
                    "rework_prob": 0.0,
                    "rework_to": None,
                }
                if kind is ToolKind.LITHO:
                    step["recipe"] = 1000 * p + layer  # one reticle per product layer
                    litho_pos = len(route)
                elif kind is ToolKind.FURNACE:
                    step["recipe"] = 900 if tag == "anneal" else layer % 3  # shared -> batchable
                elif kind is ToolKind.IMPLANT:
                    step["recipe"] = (layer // 3) % 3  # dopant species
                else:
                    step["recipe"] = layer % 4
                if kind is ToolKind.METRO and tag == "ovl":
                    step["rework_prob"] = cfg.litho_rework_prob
                    step["rework_to"] = litho_pos
                route.append(step)
        # Q-time: a pre-clean directly followed by a furnace step
        for i in range(len(route) - 1):
            if route[i]["kind"] is ToolKind.CLEAN and route[i + 1]["kind"] is ToolKind.FURNACE:
                route[i]["qtime"] = cfg.qtime_clean_to_furnace_h
        raw_routes.append(route)

    mix_raw = [rng.uniform(0.6, 1.4) for _ in range(cfg.n_products)]
    mix = [round(m / sum(mix_raw), 4) for m in mix_raw]
    mix[-1] = round(1.0 - sum(mix[:-1]), 4)

    # ---- sizing: per-lot load (machine-hours at nominal speed) per group
    load = [0.0] * len(kinds)
    for p, route in enumerate(raw_routes):
        for s in route:
            kind = s["kind"]  # type: ignore[assignment]
            assert isinstance(kind, ToolKind)
            # sizing assumes a setup on a fraction ``sizing_setup_prob`` of visits
            per_lot = float(s["proc_h"]) + cfg.sizing_setup_prob * SETUP_H.get(kind, 0.0)  # type: ignore[arg-type]
            if kind is ToolKind.FURNACE:
                per_lot /= cfg.furnace_batch_max * cfg.sizing_batch_fill
            load[int(s["group"])] += mix[p] * per_lot  # type: ignore[call-overload]

    def avail(kind: ToolKind) -> float:
        if not cfg.failures:
            return 1.0
        mtbf, _, mttr, _, _ = FAILURES[kind]
        return mtbf / (mtbf + mttr)

    litho_groups = [i for i, (k, _) in enumerate(kinds) if k is ToolKind.LITHO]
    rate = min(
        cfg.target_bottleneck_util * cfg.litho_machines * avail(ToolKind.LITHO) / load[g]
        for g in litho_groups
        if load[g] > 0
    )
    n_machines: list[int] = []
    for i, (kind, _) in enumerate(kinds):
        if kind is ToolKind.LITHO:
            n_machines.append(cfg.litho_machines)
            continue
        u = rng.uniform(*cfg.other_util_range)
        m = max(1, math.ceil(rate * load[i] / (u * avail(kind))))
        if m > cfg.max_machines:
            raise ValueError(
                f"group {kind}-{i} needs {m} machines > max {cfg.max_machines}; "
                "add groups of this kind or raise max_machines"
            )
        n_machines.append(m)

    # ---- machines and groups
    machines: list[Machine] = []
    groups: list[ToolGroup] = []
    for i, (kind, idx) in enumerate(kinds):
        ids = []
        for j in range(n_machines[i]):
            mid = len(machines)
            machines.append(Machine(mid, f"{kind.value.upper()}{idx + 1}-{j + 1}", i,
                                    round(rng.uniform(*cfg.speed_range), 3)))
            ids.append(mid)
        f = FAILURES[kind]
        is_furnace = kind is ToolKind.FURNACE
        groups.append(ToolGroup(
            id=i,
            name=f"{kind.value.upper()}{idx + 1}",
            kind=kind,
            machines=tuple(ids),
            batch_max=cfg.furnace_batch_max if is_furnace else 1,
            min_batch=cfg.furnace_min_batch if is_furnace else 1,
            max_batch_wait_h=cfg.furnace_max_wait_h if is_furnace else 0.0,
            setup_h=SETUP_H.get(kind, 0.0),
            failure=FailureModel(*f) if cfg.failures else None,
        ))

    # ---- eligibility: each litho step is qualified on all but one scanner of its
    # group. The excluded scanner is the one with the most load assigned so far,
    # so dedication creates flexibility limits without a structural imbalance.
    m_load = [0.0] * len(machines)
    products: list[Product] = []
    for p, route in enumerate(raw_routes):
        steps: list[Step] = []
        for s in route:
            g = groups[int(s["group"])]  # type: ignore[call-overload]
            elig = list(g.machines)
            if g.kind is ToolKind.LITHO and len(elig) >= 3:
                drop = max(elig, key=lambda m: (m_load[m], rng.random()))
                elig = [m for m in elig if m != drop]
            w = mix[p] * (float(s["proc_h"]) + g.setup_h) / len(elig)  # type: ignore[arg-type]
            for m in elig:
                m_load[m] += w
            kind = s["kind"]  # type: ignore[assignment]
            assert isinstance(kind, ToolKind)
            steps.append(Step(
                group=g.id,
                recipe=int(s["recipe"]),  # type: ignore[call-overload]
                proc_h=float(s["proc_h"]),  # type: ignore[arg-type]
                proc_cv=PROC_CV[kind],
                eligible=tuple(elig),
                qtime_max_h=s["qtime"],  # type: ignore[arg-type]
                rework_prob=float(s["rework_prob"]),  # type: ignore[arg-type]
                rework_to=s["rework_to"],  # type: ignore[arg-type]
                layer=int(s["layer"]),  # type: ignore[call-overload]
            ))
        products.append(Product(p, f"P{p + 1}", tuple(steps), mix[p]))

    inst = Instance(
        name=f"{cfg.name}-s{seed}",
        groups=tuple(groups),
        machines=tuple(machines),
        products=tuple(products),
        release_rate_per_h=round(rate, 5),
        hot_lot_rate_per_h=round(rate * cfg.hot_lot_share, 6),
        flow_factor=cfg.flow_factor,
        hot_flow_factor=cfg.hot_flow_factor,
        hot_weight=cfg.hot_weight,
        transport_h=cfg.transport_h,
        horizon_h=cfg.horizon_days * 24.0,
        warmup_h=cfg.warmup_days * 24.0,
        params={"generator": json.loads(json.dumps(asdict(cfg))), "seed": seed},
        release_cv=cfg.release_cv,
    )
    inst.validate()
    return inst
