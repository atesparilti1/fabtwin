"""Step 1 benchmark: classic dispatching rules on the medium fab.

Regenerates ``results/dispatch/summary.{json,md}``. Every number in the README's
dispatching table comes from this script.

    python scripts/bench_dispatch.py --reps 200
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from fabtwin.core.dispatch import RULES
from fabtwin.core.generator import generate
from fabtwin.core.instance import ToolKind
from fabtwin.sim.engine import SimConfig
from fabtwin.sim.experiment import replicate
from fabtwin.sim.stats import mean_ci, mser, relative_change_ci

KPIS = [
    ("throughput_per_day", "Throughput (lots/day)"),
    ("mean_ct_days", "Cycle time (days)"),
    ("x_factor", "X-factor"),
    ("on_time_pct", "On-time (%)"),
    ("mean_weighted_tardiness_h", "Weighted tardiness (h/lot)"),
    ("hot_mean_ct_h", "Hot-lot CT (h)"),
    ("qtime_viol_pct", "Q-time violations (%)"),
    ("litho_util", "Litho util."),
    ("avg_wip", "WIP (lots)"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--instance-seed", type=int, default=0)
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--warmup-reps", type=int, default=30)
    ap.add_argument("--out", default="results/dispatch")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    inst = generate(args.preset, seed=args.instance_seed)
    (out / f"{inst.name}.json").write_text(inst.to_json())
    base = SimConfig(rule="FIFO")

    # ---- warm-up: MSER-5 on the across-replication mean daily WIP (FIFO)
    wu = replicate(inst, replace(base, warmup_h=0.0), args.warmup_reps, seed0=10_001)
    days = min(len(s) for s in wu.wip_series)
    mean_wip = [sum(s[d] for s in wu.wip_series) / len(wu.wip_series) for d in range(days)]
    mser_day = mser(mean_wip, batch=5)

    # ---- main experiment: all rules, common random numbers (same seeds)
    reps = {rule: replicate(inst, replace(base, rule=rule), args.reps, seed0=1)
            for rule in RULES}

    def little_err(r: str) -> list[float]:
        k = reps[r].kpis
        return [abs(a - b) / a for a, b in zip(k["avg_wip"], k["little_wip"])]

    summary = {
        "instance": {
            "name": inst.name,
            "tool_groups": len(inst.groups),
            "machines": len(inst.machines),
            "products": len(inst.products),
            "route_steps": [len(p.route) for p in inst.products],
            "litho_visits": [sum(1 for s in p.route if inst.groups[s.group].kind is ToolKind.LITHO)
                             for p in inst.products],
            "release_lots_per_day": inst.release_rate_per_h * 24,
            "hot_lots_per_day": inst.hot_lot_rate_per_h * 24,
            "horizon_days": inst.horizon_h / 24,
            "warmup_days": inst.warmup_h / 24,
        },
        "warmup": {"mser5_truncation_day": mser_day, "mean_daily_wip": mean_wip,
                   "replications": args.warmup_reps},
        "replications": args.reps,
        "rules": {},
        "runtime_s": None,
    }
    for rule, r in reps.items():
        row: dict[str, object] = {}
        for k, _ in KPIS:
            c = r.ci(k)
            row[k] = {"mean": c.mean, "hw": c.half_width}
        le = little_err(rule)
        row["little_rel_err"] = {"mean": sum(le) / len(le), "max": max(le)}
        for ref in ("CR", "FIFO"):
            if rule != ref:
                for k in ("mean_weighted_tardiness_h", "mean_ct_days"):
                    d = relative_change_ci(r.kpis[k], reps[ref].kpis[k])
                    row[f"{k}_vs_{ref}_pct"] = {"mean": d.mean, "hw": d.half_width}
        summary["rules"][rule] = row  # type: ignore[index]
    summary["runtime_s"] = time.time() - t0
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    # ---- markdown table
    lines = [
        f"Instance `{inst.name}`: {len(inst.groups)} tool groups, {len(inst.machines)} machines, "
        f"{len(inst.products)} products, routes of {min(summary['instance']['route_steps'])}-"  # type: ignore[index]
        f"{max(summary['instance']['route_steps'])} steps, "  # type: ignore[index]
        f"{inst.release_rate_per_h * 24:.1f} lots/day + {inst.hot_lot_rate_per_h * 24:.2f} hot lots/day. "
        f"{args.reps} CRN replications of {inst.horizon_h / 24:.0f} days, "
        f"warm-up {inst.warmup_h / 24:.0f} days (MSER-5 suggests {mser_day} days). "
        "Mean ± 95% CI half-width.",
        "",
        "| Rule | " + " | ".join(lbl for _, lbl in KPIS) + " | Little err. |",
        "|---" * (len(KPIS) + 2) + "|",
    ]
    for rule, r in reps.items():
        cells = []
        for k, _ in KPIS:
            c = mean_ci(r.kpis[k])
            cells.append(f"{c.mean:.2f} ± {c.half_width:.2f}")
        le = little_err(rule)
        lines.append(f"| {rule} | " + " | ".join(cells) + f" | {100 * sum(le) / len(le):.2f}% |")
    lines += ["", "Paired change in weighted tardiness vs CR (% of CR mean, 95% CI):", ""]
    for rule, r in reps.items():
        if rule != "CR":
            d = relative_change_ci(r.kpis["mean_weighted_tardiness_h"], reps["CR"].kpis["mean_weighted_tardiness_h"])
            lines.append(f"- {rule}: {d.mean:+.1f}% ± {d.half_width:.1f}%")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nruntime {summary['runtime_s']:.0f}s")


if __name__ == "__main__":
    main()
