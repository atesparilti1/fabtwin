"""Warm-up sensitivity: re-estimate key KPIs with a 40-day truncation (vs 30 days).

Same seeds as bench_dispatch.py; reports the paired difference of the policy
comparison (ATCS vs CR) under both truncation points.

    python scripts/bench_warmup.py --reps 200
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from fabtwin.core.generator import generate
from fabtwin.sim.engine import SimConfig
from fabtwin.sim.experiment import replicate
from fabtwin.sim.stats import mean_ci, relative_change_ci

KPIS = ["mean_ct_days", "mean_weighted_tardiness_h", "on_time_pct", "throughput_per_day"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=200)
    a = ap.parse_args()
    inst = generate("medium", seed=0)
    out: dict = {"reps": a.reps, "warmups_days": [30, 40], "rows": []}
    reps = {}
    for wd in (30, 40):
        for rule in ("CR", "ATCS"):
            r = replicate(inst, replace(SimConfig(rule=rule), warmup_h=wd * 24.0), a.reps, seed0=1)
            reps[(wd, rule)] = r
            out["rows"].append({"warmup_days": wd, "rule": rule,
                                **{k: {"mean": mean_ci(r.kpis[k]).mean, "hw": mean_ci(r.kpis[k]).half_width}
                                   for k in KPIS}})
    lines = [f"Warm-up sensitivity ({a.reps} CRN replications): KPIs and ATCS-vs-CR paired change", "",
             "| Warm-up | Rule | CT (days) | Weighted tardiness (h) | On-time (%) |", "|---|---|---|---|---|"]
    for row in out["rows"]:
        lines.append(f"| {row['warmup_days']} d | {row['rule']} | {row['mean_ct_days']['mean']:.3f} ± {row['mean_ct_days']['hw']:.3f} | "
                     f"{row['mean_weighted_tardiness_h']['mean']:.2f} ± {row['mean_weighted_tardiness_h']['hw']:.2f} | "
                     f"{row['on_time_pct']['mean']:.1f} ± {row['on_time_pct']['hw']:.1f} |")
    lines.append("")
    for wd in (30, 40):
        for k in ("mean_ct_days", "mean_weighted_tardiness_h"):
            d = relative_change_ci(reps[(wd, "ATCS")].kpis[k], reps[(wd, "CR")].kpis[k])
            out[f"atcs_vs_cr_{k}_{wd}d"] = {"mean": d.mean, "hw": d.half_width}
            lines.append(f"- warm-up {wd} d, {k}: ATCS vs CR {d.mean:+.1f}% ± {d.half_width:.1f}%")
    p = Path("results/warmup")
    p.mkdir(parents=True, exist_ok=True)
    (p / "summary.json").write_text(json.dumps(out, indent=1))
    (p / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
