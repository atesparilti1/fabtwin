"""Headline comparison: full policies on the coupled fab (OHT transport, failures, PM).

Policies (same 200 CRN seeds):
  FIFO baseline      FIFO dispatching, nearest-vehicle OHT, run-to-failure
  CR baseline        critical ratio, nearest-vehicle OHT, run-to-failure
  ATCS + Hungarian   setup-aware litho dispatching, Hungarian OHT, run-to-failure
  FabTwin            ATCS + Hungarian OHT + robust PM (from bench_maintenance)
Plus the rolling-horizon CP-SAT litho planner on top of FabTwin (fewer
replications: one CP-SAT solve every 8 h of simulated time).

    python scripts/bench_headline.py --reps 200 --rh-reps 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fabtwin.core.generator import generate
from fabtwin.sim.engine import SimConfig
from fabtwin.sim.experiment import replicate
from fabtwin.sim.oht import OHTConfig
from fabtwin.sim.stats import mean_ci, relative_change_ci

KPIS = [("mean_weighted_tardiness_h", "Weighted tardiness (h/lot)", "lower"),
        ("mean_ct_days", "Cycle time (days)", "lower"),
        ("on_time_pct", "On-time (%)", "higher"),
        ("throughput_per_day", "Throughput (lots/day)", "higher"),
        ("qtime_viol_pct", "Q-time violations (%)", "lower"),
        ("hot_mean_ct_h", "Hot-lot cycle time (h)", "lower"),
        ("down_frac", "Unplanned down (frac)", "lower"),
        ("oht_mean_wait_min", "Wait for vehicle (min)", "lower")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--rh-reps", type=int, default=30)
    ap.add_argument("--vehicles", type=int, default=4)
    a = ap.parse_args()
    inst = generate("medium", seed=0)
    pm = tuple(json.loads(Path("results/maintenance/best_policy.json").read_text())["pm_interval_h"])
    near = OHTConfig(n_vehicles=a.vehicles, policy="nearest")
    hung = OHTConfig(n_vehicles=a.vehicles, policy="hungarian")
    pols = {
        "FIFO baseline": SimConfig(rule="FIFO", transport="oht", oht=near),
        "CR baseline": SimConfig(rule="CR", transport="oht", oht=near),
        "ATCS + Hungarian": SimConfig(rule="ATCS", transport="oht", oht=hung),
        "FabTwin": SimConfig(rule="ATCS", transport="oht", oht=hung, pm_interval_h=pm),
    }
    reps = {}
    for name, cfg in pols.items():
        reps[name] = replicate(inst, cfg, a.reps, seed0=1, label=name)
        print(name, {k: round(mean_ci(reps[name].kpis[k]).mean, 3) for k, _, _ in KPIS}, flush=True)
    rh = None
    if a.rh_reps > 0:
        rh_cfg = SimConfig(**{**pols["FabTwin"].__dict__, "plan_every_h": 8.0})
        rh = replicate(inst, rh_cfg, a.rh_reps, seed0=1, label="FabTwin + rolling CP-SAT litho")
        print("RH", {k: round(mean_ci(rh.kpis[k]).mean, 3) for k, _, _ in KPIS}, flush=True)

    rows = [{"policy": n, "values": {k: {"mean": mean_ci(r.kpis[k]).mean, "hw": mean_ci(r.kpis[k]).half_width}
                                     for k, _, _ in KPIS}} for n, r in reps.items()]
    deltas = []
    for ref in ("CR baseline", "FIFO baseline"):
        for k, lbl, _ in KPIS[:5] + KPIS[6:7]:
            d = relative_change_ci(reps["FabTwin"].kpis[k], reps[ref].kpis[k])
            deltas.append({"label": f"{lbl}: FabTwin vs {ref}", "kpi": k, "ref": ref,
                           "mean": d.mean, "hw": d.half_width, "unit": "%"})
    rh_doc = None
    if rh is not None:
        ft = {k: v[: a.rh_reps] for k, v in reps["FabTwin"].kpis.items()}
        rh_doc = {"replications": a.rh_reps,
                  "values": {k: {"mean": mean_ci(rh.kpis[k]).mean, "hw": mean_ci(rh.kpis[k]).half_width}
                             for k, _, _ in KPIS},
                  "vs_fabtwin_pct": {k: {"mean": relative_change_ci(rh.kpis[k], ft[k]).mean,
                                         "hw": relative_change_ci(rh.kpis[k], ft[k]).half_width}
                                     for k, _, _ in KPIS[:3]}}
    out = Path("results/headline")
    out.mkdir(parents=True, exist_ok=True)
    doc = {"replications": a.reps, "vehicles": a.vehicles, "pm_interval_h": pm,
           "kpis": [{"key": k, "label": l, "better": b} for k, l, b in KPIS],
           "rows": rows, "deltas": deltas, "rolling_horizon": rh_doc}
    (out / "summary.json").write_text(json.dumps(doc, indent=1))
    Path("results/web").mkdir(parents=True, exist_ok=True)
    Path("results/web/headline.json").write_text(json.dumps(doc, indent=1))
    lines = [f"Coupled fab ({a.vehicles} OHT vehicles, failures, rework, hot lots), {a.reps} CRN replications, mean ± 95% CI.", "",
             "| Policy | " + " | ".join(l for _, l, _ in KPIS) + " |", "|---" * (len(KPIS) + 1) + "|"]
    for r in rows:
        lines.append(f"| {r['policy']} | " + " | ".join(
            f"{r['values'][k]['mean']:.3f} ± {r['values'][k]['hw']:.3f}" for k, _, _ in KPIS) + " |")
    lines += ["", "FabTwin, paired change:", ""]
    lines += [f"- {d['label']}: {d['mean']:+.1f}% ± {d['hw']:.1f}%" for d in deltas]
    if rh_doc:
        lines += ["", f"Rolling-horizon CP-SAT litho planning on top of FabTwin ({a.rh_reps} reps, paired vs FabTwin):", ""]
        lines += [f"- {k}: {v['mean']:+.1f}% ± {v['hw']:.1f}%" for k, v in rh_doc["vs_fabtwin_pct"].items()]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
