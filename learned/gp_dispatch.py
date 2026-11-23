"""Stretch goal: genetic programming that evolves a dispatching priority rule.

Kept outside the core package on purpose. A rule is an arithmetic expression
over normalised lot features (slack, proc, rem, wait, weight, qleft, cr; see
``fabtwin.core.dispatch.EXPR_FEATURES``), lower = dispatched first, applied
lot-first at every tool group (hot lots still go first).

Training: tree GP (ramped half-and-half init, tournament selection, subtree
crossover / mutation, elitism, depth limit) with fitness = mean weighted
tardiness over a fixed set of *training* seeds (CRN) on shorter runs.
Testing: the best evolved rule vs ATC and ATCS on 200 *held-out* seeds with the
full 120-day horizon. The rule is reported as an improvement only if the paired
95% CI against the best baseline lies entirely below zero.

    python learned/gp_dispatch.py --gens 15 --pop 40
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import replace
from pathlib import Path

from fabtwin.core.dispatch import EXPR_FEATURES
from fabtwin.core.generator import generate
from fabtwin.sim.engine import SimConfig
from fabtwin.sim.experiment import replicate
from fabtwin.sim.stats import mean_ci, relative_change_ci

OPS = ["+", "-", "*", "/", "min", "max"]
Tree = tuple  # ("op", left, right) | ("f", name) | ("c", value)


def rand_tree(rng: random.Random, depth: int, full: bool) -> Tree:
    if depth == 0 or (not full and rng.random() < 0.3):
        if rng.random() < 0.75:
            return ("f", rng.choice(EXPR_FEATURES))
        return ("c", round(rng.uniform(-2, 2), 2))
    return (rng.choice(OPS), rand_tree(rng, depth - 1, full), rand_tree(rng, depth - 1, full))


def to_expr(t: Tree) -> str:
    if t[0] == "f":
        return str(t[1])
    if t[0] == "c":
        return f"({t[1]})"
    a, b = to_expr(t[1]), to_expr(t[2])
    if t[0] in ("min", "max"):
        return f"{t[0]}({a}, {b})"
    return f"({a} {t[0]} {b})"


def depth(t: Tree) -> int:
    return 0 if t[0] in ("f", "c") else 1 + max(depth(t[1]), depth(t[2]))


def nodes(t: Tree, path: tuple = ()) -> list[tuple]:
    out = [path]
    if t[0] not in ("f", "c"):
        out += nodes(t[1], path + (1,)) + nodes(t[2], path + (2,))
    return out


def get(t: Tree, path: tuple) -> Tree:
    for i in path:
        t = t[i]
    return t


def put(t: Tree, path: tuple, sub: Tree) -> Tree:
    if not path:
        return sub
    lst = list(t)
    lst[path[0]] = put(t[path[0]], path[1:], sub)
    return tuple(lst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=15)
    ap.add_argument("--pop", type=int, default=40)
    ap.add_argument("--train-seeds", type=int, default=6)
    ap.add_argument("--test-reps", type=int, default=200)
    ap.add_argument("--max-depth", type=int, default=5)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    inst = generate("medium", seed=0)
    train = SimConfig(rule="EXPR", horizon_h=75 * 24, warmup_h=25 * 24)
    cache: dict[str, float] = {}

    def fitness(t: Tree) -> float:
        e = to_expr(t)
        if e not in cache:
            r = replicate(inst, replace(train, rule_expr=e), a.train_seeds, seed0=50_001)
            k = r.kpis["mean_weighted_tardiness_h"]
            cache[e] = sum(k) / len(k) + 1e-3 * len(nodes(t))  # parsimony pressure
        return cache[e]

    # seed the population with the classic rules expressed in the feature language
    seeds = [("f", "slack"), ("f", "cr"), ("-", ("c", 0.0), ("f", "wait")),
             ("/", ("f", "slack"), ("f", "weight"))]
    pop = seeds + [rand_tree(rng, rng.randint(2, 4), i % 2 == 0) for i in range(a.pop - len(seeds))]
    history = []
    for g in range(a.gens):
        scored = sorted(((fitness(t), t) for t in pop), key=lambda x: x[0])
        history.append({"gen": g, "best": scored[0][0], "median": scored[len(scored) // 2][0],
                        "best_expr": to_expr(scored[0][1])})
        print(history[-1], flush=True)
        nxt = [t for _, t in scored[:2]]  # elitism
        while len(nxt) < a.pop:
            def tour() -> Tree:
                return min(rng.sample(scored, 3), key=lambda x: x[0])[1]
            if rng.random() < 0.8:
                p1, p2 = tour(), tour()
                child = put(p1, rng.choice(nodes(p1)), get(p2, rng.choice(nodes(p2))))
            else:
                p1 = tour()
                child = put(p1, rng.choice(nodes(p1)), rand_tree(rng, 2, False))
            if depth(child) <= a.max_depth:
                nxt.append(child)
        pop = nxt
    best = min(pop, key=fitness)
    expr = to_expr(best)

    # ---- held-out test: full horizon, fresh seeds, paired vs baselines
    test = SimConfig()
    r_gp = replicate(inst, replace(test, rule="EXPR", rule_expr=expr), a.test_reps, seed0=1, label="GP")
    base = {r: replicate(inst, replace(test, rule=r), a.test_reps, seed0=1) for r in ("ATC", "ATCS", "CR")}
    k = "mean_weighted_tardiness_h"
    res = {"expr": expr, "train_history": history, "test_reps": a.test_reps,
           "gp": {"mean": mean_ci(r_gp.kpis[k]).mean, "hw": mean_ci(r_gp.kpis[k]).half_width}}
    for name, r in base.items():
        d = relative_change_ci(r_gp.kpis[k], r.kpis[k])
        res[f"vs_{name}_pct"] = {"mean": d.mean, "hw": d.half_width}
        res[name] = {"mean": mean_ci(r.kpis[k]).mean, "hw": mean_ci(r.kpis[k]).half_width}
    best_base = min(base, key=lambda n: res[n]["mean"])
    d = res[f"vs_{best_base}_pct"]
    res["beats_best_baseline"] = d["mean"] + d["hw"] < 0
    res["best_baseline"] = best_base
    out = Path("results/learned")
    out.mkdir(parents=True, exist_ok=True)
    (out / "gp.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k2: v for k2, v in res.items() if k2 != "train_history"}, indent=1))


if __name__ == "__main__":
    main()
