"""Steps 2-3 benchmark: exact models vs heuristics on static snapshot instances.

Outputs results/exact/{small,scaling,pareto,convergence}.json + summary.md and the
web copies in results/web/. Fixed seeds; all limits are wall-clock.

    python scripts/bench_exact.py            # full (~10 min on 16 cores)
    python scripts/bench_exact.py --quick    # CI smoke
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from fabtwin.core.alns import solve_alns
from fabtwin.core.cpsat import solve_cpsat
from fabtwin.core.decomposition import solve_decomposition
from fabtwin.core.mip import solve_mip
from fabtwin.core.static import (
    check_schedule,
    decode_nondelay,
    evaluate,
    make_static,
    qtime_violations,
    rule_rank,
    total_flow,
    weighted_tardiness,
)

RULES = ["FIFO", "EDD", "CR", "ATC"]
INST_KW = dict(due_factor=1.25)


def inst(n: int, k: int, seed: int):  # type: ignore[no-untyped-def]
    return make_static(n, k, seed=seed, release_spread_h=0.2 * n, **INST_KW)


def small_case(args: tuple[int, int, int, float, float, float]) -> dict[str, Any]:
    n, k, seed, cp_s, mip_s, alns_s = args
    si = inst(n, k, seed)
    row: dict[str, Any] = {"instance": si.name, "lots": n, "steps": k, "ops": len(si.ops)}
    heur = {}
    best_mk = None
    for r in RULES:
        s = decode_nondelay(si, rule_rank(si, r))
        heur[r] = evaluate(si, s)
        mk = max(s.end.values())
        best_mk = mk if best_mk is None else min(best_mk, mk)
    row["heuristics"] = heur
    d = solve_decomposition(si, sub_time_s=3.0)
    row["sbh"], row["sbh_s"] = d.objective, round(d.seconds, 2)
    a = solve_alns(si, seed=seed, iters=100_000, time_limit_s=alns_s)
    row["alns"], row["alns_s"] = a.best_obj, round(a.seconds, 2)
    c = solve_cpsat(si, time_limit_s=cp_s, workers=4)
    row.update(cpsat_obj=c.objective, cpsat_bound=c.bound, cpsat_status=c.status,
               cpsat_s=round(c.seconds, 2),
               cpsat_feasible=not check_schedule(si, c.schedule) if c.schedule else None)
    if mip_s > 0:
        assert best_mk is not None
        m = solve_mip(si, horizon=int(best_mk * 1.25) + 5, time_limit_s=mip_s, threads=4)
        row.update(mip_obj=m.objective, mip_bound=m.bound, mip_status=m.status,
                   mip_s=round(m.seconds, 2), mip_vars=m.n_vars, mip_rows=m.n_rows,
                   mip_feasible=not check_schedule(si, m.schedule) if m.schedule else None)
    return row


def scaling_case(args: tuple[int, int, int, float, float]) -> dict[str, Any]:
    n, k, seed, cp_s, alns_s = args
    si = inst(n, k, seed)
    t = time.perf_counter()
    best_rule = min(evaluate(si, decode_nondelay(si, rule_rank(si, r))) for r in RULES)
    rule_s = time.perf_counter() - t
    d = solve_decomposition(si, sub_time_s=5.0)
    a = solve_alns(si, seed=seed, iters=100_000, time_limit_s=alns_s)
    c = solve_cpsat(si, time_limit_s=cp_s, workers=4)
    return {"instance": si.name, "lots": n, "ops": len(si.ops), "best_rule": best_rule,
            "rule_s": round(rule_s, 3), "sbh": d.objective, "sbh_s": round(d.seconds, 2),
            "alns": a.best_obj, "alns_s": round(a.seconds, 2),
            "cpsat_obj": c.objective, "cpsat_bound": c.bound, "cpsat_status": c.status,
            "cpsat_s": round(c.seconds, 2)}


def pareto(n: int, k: int, seed: int, cp_s: float, points: int) -> dict[str, Any]:
    """Exact WT-vs-flow front by the epsilon-constraint method (CP-SAT)."""
    si = inst(n, k, seed)
    f_min = solve_cpsat(si, time_limit_s=cp_s, objective="flow", workers=8)
    w_min = solve_cpsat(si, time_limit_s=cp_s, workers=8)
    assert f_min.schedule and w_min.schedule
    lo, hi = int(f_min.objective or 0), int(total_flow(si, w_min.schedule))
    front = []
    for i in range(points):
        cap = int(round(lo + (hi - lo) * i / max(1, points - 1)))
        r = solve_cpsat(si, time_limit_s=cp_s, flow_cap=cap, workers=8)
        if r.schedule:
            front.append({"flow_h": total_flow(si, r.schedule) * si.unit_h / len(si.jobs),
                          "wt": weighted_tardiness(si, r.schedule), "status": r.status, "cap": cap})
    rules = []
    for rule in RULES:
        s = decode_nondelay(si, rule_rank(si, rule))
        rules.append({"method": rule, "flow_h": total_flow(si, s) * si.unit_h / len(si.jobs),
                      "wt": weighted_tardiness(si, s), "qviol": qtime_violations(si, s)})
    a = solve_alns(si, seed=seed, time_limit_s=20.0, iters=100_000)
    rules.append({"method": "ALNS", "flow_h": total_flow(si, a.best_schedule) * si.unit_h / len(si.jobs),
                  "wt": weighted_tardiness(si, a.best_schedule),
                  "qviol": qtime_violations(si, a.best_schedule)})
    return {"instance": si.name, "front": front, "methods": rules}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="results/exact")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    web = Path("results/web")
    web.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if a.quick:
        small_cfg = [(5, 6, 1, 10.0, 10.0, 2.0)]
        scale_cfg = [(8, 8, 1, 5.0, 2.0)]
        pareto_cfg = (5, 6, 1, 5.0, 3)
        conv_lim = 3.0
    else:
        small_cfg = [(n, k, s, 60.0, 90.0, 15.0)
                     for n, k in ((5, 8), (6, 8), (8, 10), (10, 10)) for s in (1, 2, 3)]
        scale_cfg = [(n, 12, s, 60.0, 30.0) for n in (10, 20, 40, 80) for s in (1, 2)]
        pareto_cfg = (8, 10, 2, 20.0, 8)
        conv_lim = 30.0
    with ProcessPoolExecutor(a.workers) as ex:
        small = list(ex.map(small_case, small_cfg))
        scaling = list(ex.map(scaling_case, scale_cfg))
    par = pareto(*pareto_cfg)
    # convergence: ALNS on a 20-lot instance, 3 seeds
    conv = []
    si = inst(20, 12, 20) if not a.quick else inst(8, 8, 1)
    for s in (1, 2, 3):
        r = solve_alns(si, seed=s, iters=1_000_000, time_limit_s=conv_lim)
        conv.append({"name": f"ALNS seed {s}", "iter": r.history["iter"], "time": r.history["time"],
                     "best": r.history["best"], "current": r.history["current"],
                     "weights": r.op_weights})
    (out / "small.json").write_text(json.dumps(small, indent=1))
    (out / "scaling.json").write_text(json.dumps(scaling, indent=1))
    (out / "pareto.json").write_text(json.dumps(par, indent=1))
    (out / "convergence.json").write_text(json.dumps({"instance": si.name, "series": conv}))

    # ---- web sections
    (web / "exact.json").write_text(json.dumps({"rows": small}, indent=1))
    (web / "scaling.json").write_text(json.dumps({"rows": scaling}, indent=1))
    pts = [{"method": "CP-SAT ε-constraint", "x": p["flow_h"], "y": p["wt"], "front": True}
           for p in par["front"]]
    pts += [{"method": m["method"], "x": m["flow_h"], "y": m["wt"], "front": False}
            for m in par["methods"]]
    (web / "pareto.json").write_text(json.dumps({
        "instance": par["instance"], "x": "Mean flow time (h/lot)", "y": "Weighted tardiness (units)",
        "points": pts}, indent=1))
    (web / "convergence.json").write_text(json.dumps({
        "instance": si.name,
        "series": [{k: v for k, v in c.items() if k != "weights"} for c in conv]}))

    # ---- markdown
    def gap(obj: float | None, ref: float | None) -> str:
        if obj is None or ref is None:
            return "–"
        if ref == 0:
            return "0.0%" if obj == 0 else f"+{obj:.0f} abs"
        return f"{100 * (obj - ref) / ref:+.1f}%"

    lines = ["## Small instances: optimality gaps (objective = weighted tardiness, time units of 0.1 h)", "",
             "| Instance | Ops | Best rule | SBH | ALNS | CP-SAT obj / bound (s) | MIP obj / bound (s) |",
             "|---|---|---|---|---|---|---|"]
    for r in small:
        br = min(r["heuristics"].values())
        ref = r["cpsat_obj"] if r["cpsat_status"] == "OPTIMAL" else None
        mip = (f"{r.get('mip_obj')} / {r.get('mip_bound', 0):.0f} ({r.get('mip_s')})"
               if "mip_s" in r else "–")
        lines.append(f"| {r['instance']} | {r['ops']} | {br:.0f} ({gap(br, ref)}) | {r['sbh']:.0f} ({gap(r['sbh'], ref)}) "
                     f"| {r['alns']:.0f} ({gap(r['alns'], ref)}) | {r['cpsat_obj']:.0f} / {r['cpsat_bound']:.0f} "
                     f"({r['cpsat_s']}, {r['cpsat_status']}) | {mip} |")
    lines += ["", "## Scaling (CP-SAT 60 s limit, ALNS 30 s)", "",
              "| Instance | Ops | Best rule | SBH (s) | ALNS | CP-SAT obj / bound | status |",
              "|---|---|---|---|---|---|---|"]
    for r in scaling:
        lines.append(f"| {r['instance']} | {r['ops']} | {r['best_rule']:.0f} | {r['sbh']:.0f} ({r['sbh_s']}) | "
                     f"{r['alns']:.0f} | {r['cpsat_obj']} / {r['cpsat_bound']:.0f} | {r['cpsat_status']} |")
    lines.append(f"\nruntime {time.time() - t0:.0f}s")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
