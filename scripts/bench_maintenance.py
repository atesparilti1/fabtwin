"""Step 5 benchmark: PM policy optimisation under uncertainty, robust vs nominal.

1. Nominal plan: availability-optimal age-based PM interval per tool kind.
2. Candidates: tau = m_litho * tau* on litho, m_other * tau* elsewhere.
3. Two-stage screen-and-select with CRN (seeds 1001+), objective mean cycle time.
4. Validation on fresh seeds 1..reps: run-to-failure vs nominal vs robust.

    python scripts/bench_maintenance.py
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from fabtwin.core.generator import generate
from fabtwin.core.maintenance import nominal_plan, scaled_plan, screen
from fabtwin.sim.engine import SimConfig
from fabtwin.sim.experiment import replicate
from fabtwin.sim.stats import mean_ci, relative_change_ci

OBJ = "mean_ct_days"
REPORT = ["mean_ct_days", "mean_weighted_tardiness_h", "on_time_pct", "throughput_per_day",
          "down_frac", "pm_frac", "litho_down_frac", "failures", "litho_util"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n0", type=int, default=20)
    ap.add_argument("--n1", type=int, default=40)
    ap.add_argument("--reps", type=int, default=200)
    a = ap.parse_args()
    inst = generate("medium", seed=0)
    nominal = nominal_plan(inst)
    base = SimConfig(rule="ATCS")
    m_l = [None, 0.5, 0.7, 1.0, 1.4, 2.0]
    m_o = [None, 0.7, 1.0, 1.4]
    cands = list(itertools.product(m_l, m_o))
    plans = [scaled_plan(inst, nominal, ml, mo) for ml, mo in cands]

    def run(plan, n, seed0, label):  # type: ignore[no-untyped-def]
        return replicate(inst, SimConfig(**{**base.__dict__, "pm_interval_h": plan}), n,
                         seed0=seed0, label=label)

    s1 = [run(p, a.n0, 1001, str(c)) for p, c in zip(plans, cands)]
    sc = screen([r.kpis[OBJ] for r in s1])
    print("stage 1 survivors:", [cands[i] for i in sc.survivors], flush=True)
    s2 = {i: run(plans[i], a.n1, 1001 + a.n0, str(cands[i])) for i in sc.survivors}
    means = {i: (sum(s1[i].kpis[OBJ]) + sum(s2[i].kpis[OBJ])) / (a.n0 + a.n1) for i in sc.survivors}
    best = min(means, key=lambda i: means[i])
    robust = plans[best]
    print("selected", cands[best], robust, flush=True)

    # ---- validation on fresh seeds
    policies = {"Run-to-failure": None, "Nominal PM (availability-optimal)": nominal,
                "Robust PM (simulation-optimised)": robust}
    val = {name: run(plan, a.reps, 1, name) for name, plan in policies.items()}
    rows = []
    for name, r in val.items():
        row = {"policy": name}
        for k in REPORT:
            c = mean_ci(r.kpis[k])
            row[k] = {"mean": c.mean, "hw": c.half_width}
        rows.append(row)
    deltas = {}
    for ref in ("Run-to-failure", "Nominal PM (availability-optimal)"):
        for k in ("mean_ct_days", "mean_weighted_tardiness_h", "down_frac", "litho_down_frac", "failures"):
            d = relative_change_ci(val["Robust PM (simulation-optimised)"].kpis[k], val[ref].kpis[k])
            deltas[f"{k} vs {ref}"] = {"mean": d.mean, "hw": d.half_width}
    out = Path("results/maintenance")
    out.mkdir(parents=True, exist_ok=True)
    stage1 = [{"m_litho": c[0], "m_other": c[1], "mean": mean_ci(r.kpis[OBJ]).mean,
               "hw": mean_ci(r.kpis[OBJ]).half_width, "survived": i in sc.survivors}
              for i, (c, r) in enumerate(zip(cands, s1))]
    doc = {"objective": OBJ, "nominal_tau_h": nominal, "candidates": stage1,
           "selected": {"m_litho": cands[best][0], "m_other": cands[best][1]},
           "validation_reps": a.reps, "rows": rows, "deltas": deltas}
    (out / "summary.json").write_text(json.dumps(doc, indent=1))
    (out / "best_policy.json").write_text(json.dumps({"pm_interval_h": list(robust),
                                                       "m_litho": cands[best][0],
                                                       "m_other": cands[best][1]}, indent=1))
    Path("results/web").mkdir(parents=True, exist_ok=True)
    Path("results/web/maintenance.json").write_text(json.dumps({
        "replications": a.reps, "objective": OBJ, "selected": doc["selected"],
        "rows": [{"policy": r["policy"], "ct_days": r["mean_ct_days"], "tardiness": r["mean_weighted_tardiness_h"],
                  "down_pct": {"mean": 100 * r["down_frac"]["mean"], "hw": 100 * r["down_frac"]["hw"]},
                  "pm_pct": {"mean": 100 * r["pm_frac"]["mean"], "hw": 100 * r["pm_frac"]["hw"]},
                  "failures": r["failures"]} for r in rows],
        "candidates": stage1, "deltas": deltas}, indent=1))
    lines = [f"PM policies, ATCS dispatching, validation on {a.reps} fresh CRN replications (mean ± 95% CI).",
             f"Selected multipliers: litho {cands[best][0]}, other {cands[best][1]} (stage 1 n0={a.n0}, "
             f"{len(sc.survivors)} survivors, stage 2 n1={a.n1}).", "",
             "| Policy | CT (days) | Weighted tardiness (h) | On-time (%) | Down (%) | PM (%) | Litho down (%) | Failures |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['policy']} | {r['mean_ct_days']['mean']:.3f} ± {r['mean_ct_days']['hw']:.3f} | "
                     f"{r['mean_weighted_tardiness_h']['mean']:.2f} ± {r['mean_weighted_tardiness_h']['hw']:.2f} | "
                     f"{r['on_time_pct']['mean']:.1f} ± {r['on_time_pct']['hw']:.1f} | "
                     f"{100 * r['down_frac']['mean']:.2f} ± {100 * r['down_frac']['hw']:.2f} | "
                     f"{100 * r['pm_frac']['mean']:.2f} | {100 * r['litho_down_frac']['mean']:.2f} | "
                     f"{r['failures']['mean']:.0f} ± {r['failures']['hw']:.0f} |")
    lines += ["", "Robust PM, paired change:", ""]
    lines += [f"- {k}: {v['mean']:+.1f}% ± {v['hw']:.1f}%" for k, v in deltas.items()]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
