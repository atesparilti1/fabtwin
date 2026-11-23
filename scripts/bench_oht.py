"""Step 4 benchmark: OHT fleet size x vehicle dispatching policy (CRN, ATCS dispatching).

    python scripts/bench_oht.py --reps 60
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

KPIS = ["oht_mean_wait_min", "oht_mean_transport_min", "oht_vehicle_util", "oht_blocked_s_per_move",
        "qtime_viol_pct", "mean_ct_days", "mean_weighted_tardiness_h", "hot_mean_ct_h"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=60)
    ap.add_argument("--fleets", default="3,4,6")
    a = ap.parse_args()
    inst = generate("medium", seed=0)
    rows, reps = [], {}
    for nv in [int(x) for x in a.fleets.split(",")]:
        for pol in ("nearest", "hungarian"):
            cfg = SimConfig(rule="ATCS", transport="oht", oht=OHTConfig(n_vehicles=nv, policy=pol))
            r = replicate(inst, cfg, a.reps, seed0=1, label=f"{nv}-{pol}")
            reps[(nv, pol)] = r
            row = {"vehicles": nv, "policy": pol}
            for k in KPIS:
                c = mean_ci(r.kpis[k])
                row[k] = {"mean": c.mean, "hw": c.half_width}
            rows.append(row)
            print(nv, pol, {k: round(row[k]["mean"], 3) for k in KPIS}, flush=True)
    for row in rows:
        if row["policy"] == "hungarian":
            nv = row["vehicles"]
            for k in ("oht_mean_wait_min", "qtime_viol_pct", "mean_weighted_tardiness_h"):
                d = relative_change_ci(reps[(nv, "hungarian")].kpis[k], reps[(nv, "nearest")].kpis[k])
                row[f"{k}_vs_nearest_pct"] = {"mean": d.mean, "hw": d.half_width}
    out = Path("results/oht")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps({"replications": a.reps, "rows": rows}, indent=1))
    web = [{"vehicles": r["vehicles"], "policy": r["policy"], "wait_min": r["oht_mean_wait_min"],
            "transport_min": r["oht_mean_transport_min"], "util": r["oht_vehicle_util"],
            "qviol_pct": r["qtime_viol_pct"], "ct_days": r["mean_ct_days"],
            "wt_h": r["mean_weighted_tardiness_h"]} for r in rows]
    Path("results/web").mkdir(parents=True, exist_ok=True)
    Path("results/web/oht.json").write_text(json.dumps({"replications": a.reps, "rows": web}, indent=1))
    lines = [f"OHT fleet x policy, ATCS dispatching, {a.reps} CRN replications, mean ± 95% CI", "",
             "| Vehicles | Policy | Wait for vehicle (min) | Transport (min) | Vehicle util. | Blocked (s/move) | Q-time viol. (%) | CT (days) | Weighted tardiness (h) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['vehicles']} | {r['policy']} | " + " | ".join(
            f"{r[k]['mean']:.3f} ± {r[k]['hw']:.3f}" for k in KPIS[:3] + KPIS[3:7]) + " |")
    lines += ["", "Hungarian vs nearest (paired, % of nearest):", ""]
    for r in rows:
        if r["policy"] == "hungarian":
            lines.append(f"- {r['vehicles']} vehicles: wait {r['oht_mean_wait_min_vs_nearest_pct']['mean']:+.1f}% "
                         f"± {r['oht_mean_wait_min_vs_nearest_pct']['hw']:.1f}%, Q-time violations "
                         f"{r['qtime_viol_pct_vs_nearest_pct']['mean']:+.1f}% ± {r['qtime_viol_pct_vs_nearest_pct']['hw']:.1f}%")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
