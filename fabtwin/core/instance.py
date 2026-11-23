"""Problem instance model for a re-entrant flexible job shop with batching.

All times are in **hours**. An instance is pure data: it can be serialised to
JSON (``to_dict`` / ``from_dict``) so the browser twin replays exactly the same
fab that the Python optimizers and the simulator used.

Modelling assumptions (also listed in the README):

* A *lot* (one FOUP, 25 wafers) is the unit of flow; wafers are never split.
* Each route step names one tool group, a recipe and a mean processing time for
  a nominal-speed machine. A machine with ``speed`` s processes in ``t / s``.
* Batch tools (``batch_max > 1``) process up to ``batch_max`` lots of the same
  recipe together; the processing time is per batch, independent of fill.
* A sequence-dependent setup of ``setup_h`` is incurred when a machine changes
  recipe (reticle change on litho, species change on implant).
* ``qtime_max_h`` on step i limits the time from the *end* of step i to the
  *start* of processing of step i+1. A violated lot is sent back to step i
  (re-clean) and the violation is counted.
* ``rework_prob`` on a metrology step sends the lot back to ``rework_to``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ToolKind(StrEnum):
    """Process area of a tool group."""

    LITHO = "litho"
    ETCH = "etch"
    DEP = "dep"
    FURNACE = "furnace"
    IMPLANT = "implant"
    CMP = "cmp"
    CLEAN = "clean"
    METRO = "metro"


@dataclass(frozen=True)
class FailureModel:
    """Weibull time-to-failure (calendar hours) and lognormal repair time."""

    mtbf_h: float
    weibull_shape: float
    mttr_h: float
    repair_cv: float

    @property
    def weibull_scale(self) -> float:
        """Scale parameter so the Weibull mean equals ``mtbf_h``."""
        return self.mtbf_h / math.gamma(1.0 + 1.0 / self.weibull_shape)

    @property
    def availability(self) -> float:
        """Long-run fraction of calendar time a machine is up (no PM)."""
        return self.mtbf_h / (self.mtbf_h + self.mttr_h)


@dataclass(frozen=True)
class Machine:
    """One physical tool. ``speed`` > 1 means faster than nominal."""

    id: int
    name: str
    group: int
    speed: float


@dataclass(frozen=True)
class ToolGroup:
    """A set of parallel, possibly non-identical machines of the same kind."""

    id: int
    name: str
    kind: ToolKind
    machines: tuple[int, ...]
    batch_max: int = 1
    min_batch: int = 1
    max_batch_wait_h: float = 0.0
    setup_h: float = 0.0
    failure: FailureModel | None = None

    @property
    def is_batch(self) -> bool:
        return self.batch_max > 1


@dataclass(frozen=True)
class Step:
    """One operation of a route."""

    group: int
    recipe: int
    proc_h: float
    proc_cv: float
    eligible: tuple[int, ...]
    qtime_max_h: float | None = None
    rework_prob: float = 0.0
    rework_to: int | None = None
    layer: int = 0


@dataclass(frozen=True)
class Product:
    """A product type with its re-entrant route and share of releases."""

    id: int
    name: str
    route: tuple[Step, ...]
    mix: float

    @property
    def raw_process_h(self) -> float:
        """Sum of nominal processing times (no setups, queueing or transport)."""
        return sum(s.proc_h for s in self.route)

    def remaining_work(self) -> tuple[float, ...]:
        """``rem[i]`` = nominal work of steps i..end (``rem[len]`` = 0)."""
        rem = [0.0] * (len(self.route) + 1)
        for i in range(len(self.route) - 1, -1, -1):
            rem[i] = rem[i + 1] + self.route[i].proc_h
        return tuple(rem)


@dataclass(frozen=True)
class Instance:
    """A complete fab scenario: tools, products and release/due-date policy."""

    name: str
    groups: tuple[ToolGroup, ...]
    machines: tuple[Machine, ...]
    products: tuple[Product, ...]
    release_rate_per_h: float
    hot_lot_rate_per_h: float
    flow_factor: float
    hot_flow_factor: float
    hot_weight: float
    transport_h: float
    horizon_h: float
    warmup_h: float
    params: dict[str, Any] = field(default_factory=dict)
    release_cv: float = 0.0  # CV of release interarrival times (0 = constant rate)

    # ------------------------------------------------------------------ checks
    def validate(self) -> None:
        """Raise ``ValueError`` if the instance is internally inconsistent."""
        for i, g in enumerate(self.groups):
            if g.id != i:
                raise ValueError(f"group ids must be 0..n-1, got {g.id} at {i}")
            if not g.machines:
                raise ValueError(f"group {g.name} has no machines")
            if g.batch_max < 1 or not 1 <= g.min_batch <= g.batch_max:
                raise ValueError(f"group {g.name}: bad batch parameters")
            for m in g.machines:
                if self.machines[m].group != g.id:
                    raise ValueError(f"machine {m} not in group {g.name}")
        for i, mach in enumerate(self.machines):
            if mach.id != i or mach.speed <= 0:
                raise ValueError(f"bad machine {mach}")
        total_mix = sum(p.mix for p in self.products)
        if abs(total_mix - 1.0) > 1e-9:
            raise ValueError(f"product mix sums to {total_mix}, expected 1")
        for p in self.products:
            for k, s in enumerate(p.route):
                g = self.groups[s.group]
                if not s.eligible or any(e not in g.machines for e in s.eligible):
                    raise ValueError(f"{p.name} step {k}: eligibility outside group")
                if s.proc_h <= 0:
                    raise ValueError(f"{p.name} step {k}: non-positive proc time")
                if s.rework_prob > 0 and (s.rework_to is None or not 0 <= s.rework_to <= k):
                    raise ValueError(f"{p.name} step {k}: bad rework target")
                if s.qtime_max_h is not None and k == len(p.route) - 1:
                    raise ValueError(f"{p.name}: Q-time on the last step")
        if self.warmup_h >= self.horizon_h:
            raise ValueError("warm-up must be shorter than the horizon")

    # --------------------------------------------------------------- analytics
    def group_load_per_lot(self, setup_prob: float = 0.0) -> list[float]:
        """Expected machine-hours per released lot at each group (nominal speed).

        Batch steps are divided by ``batch_max`` (full batches). A setup is
        counted on a fraction ``setup_prob`` of visits to setup tools.
        """
        load = [0.0] * len(self.groups)
        for p in self.products:
            for s in p.route:
                g = self.groups[s.group]
                load[s.group] += p.mix * (s.proc_h / g.batch_max + setup_prob * g.setup_h)
        return load

    def nominal_utilization(self, fill: float = 1.0, setup_prob: float = 0.0) -> list[float]:
        """Offered load / available capacity per group at the release rate.

        ``fill`` is the assumed average batch fill fraction for batch tools.
        Failures reduce capacity by the steady-state availability.
        """
        out = []
        for g, w in zip(self.groups, self.group_load_per_lot(setup_prob)):
            speed = sum(self.machines[m].speed for m in g.machines)
            avail = g.failure.availability if g.failure else 1.0
            batch_adj = 1.0 / fill if g.is_batch else 1.0
            out.append(self.release_rate_per_h * w * batch_adj / (speed * avail))
        return out

    # ----------------------------------------------------------- serialisation
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Instance:
        groups = tuple(
            ToolGroup(
                id=g["id"],
                name=g["name"],
                kind=ToolKind(g["kind"]),
                machines=tuple(g["machines"]),
                batch_max=g["batch_max"],
                min_batch=g["min_batch"],
                max_batch_wait_h=g["max_batch_wait_h"],
                setup_h=g["setup_h"],
                failure=FailureModel(**g["failure"]) if g["failure"] else None,
            )
            for g in d["groups"]
        )
        machines = tuple(Machine(**m) for m in d["machines"])
        products = tuple(
            Product(
                id=p["id"],
                name=p["name"],
                mix=p["mix"],
                route=tuple(Step(**{**s, "eligible": tuple(s["eligible"])}) for s in p["route"]),
            )
            for p in d["products"]
        )
        scalars = {
            k: d[k]
            for k in (
                "name",
                "release_rate_per_h",
                "hot_lot_rate_per_h",
                "flow_factor",
                "hot_flow_factor",
                "hot_weight",
                "transport_h",
                "horizon_h",
                "warmup_h",
                "params",
                "release_cv",
            )
            if k in d
        }
        return Instance(groups=groups, machines=machines, products=products, **scalars)

    @staticmethod
    def from_json(text: str) -> Instance:
        return Instance.from_dict(json.loads(text))
