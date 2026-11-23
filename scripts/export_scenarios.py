"""Export precomputed replay scenarios for the static web demo.

Writes ``web/public/data/<id>.json`` plus ``index.json``. All scenarios use the
same instance and the same random seed, so the compare mode shows two policies
facing identical lots, failures and processing-time draws (CRN).

    python scripts/export_scenarios.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fabtwin.core.generator import generate
from fabtwin.sim.engine import SimConfig, simulate
from fabtwin.sim.export import export_replay
from fabtwin.sim.oht import OHTConfig

SEED = 7
DAY = 24.0


def scenarios(n_groups: int, robust_pm: tuple[float | None, ...] | None) -> list[dict[str, Any]]:
    return [
        {
            "id": "baseline",
            "title": "FIFO baseline",
            "subtitle": "FIFO dispatching, nearest-vehicle OHT, run-to-failure maintenance",
            "cfg": dict(rule="FIFO", transport="oht",
                        oht=OHTConfig(n_vehicles=4, policy="nearest")),
        },
        {
            "id": "cr",
            "title": "Critical ratio",
            "subtitle": "Critical-ratio dispatching, nearest-vehicle OHT, run-to-failure",
            "cfg": dict(rule="CR", transport="oht",
                        oht=OHTConfig(n_vehicles=4, policy="nearest")),
        },
        {
            "id": "optimized",
            "title": "FabTwin policy",
            "subtitle": "Setup-aware ATCS litho dispatching, Hungarian OHT assignment, "
                        "optimized preventive maintenance",
            "cfg": dict(rule="ATCS", transport="oht",
                        oht=OHTConfig(n_vehicles=4, policy="hungarian"),
                        pm_interval_h=robust_pm),
        },
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="web/public/data")
    ap.add_argument("--from-day", type=float, default=40.0)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--pm", default="results/maintenance/best_policy.json",
                    help="JSON with the optimized PM intervals (step 5); optional")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inst = generate("medium", seed=0)
    pm_path = Path(args.pm)
    robust_pm = None
    if pm_path.exists():
        robust_pm = tuple(json.loads(pm_path.read_text())["pm_interval_h"])
    index = []
    for sc in scenarios(len(inst.groups), robust_pm):
        t0 = args.from_day * DAY
        cfg = SimConfig(seed=SEED, record_events=True, trace_from_h=t0,
                        trace_to_h=t0 + args.days * DAY, horizon_h=t0 + args.days * DAY + DAY,
                        warmup_h=30 * DAY, **sc["cfg"])
        res = simulate(inst, cfg)
        meta = {k: v for k, v in sc.items() if k != "cfg"}
        meta["pm"] = list(robust_pm) if sc["cfg"].get("pm_interval_h") else None
        meta["oht_policy"] = sc["cfg"]["oht"].policy
        meta["n_vehicles"] = sc["cfg"]["oht"].n_vehicles
        doc = export_replay(inst, cfg, res, meta)
        path = out / f"{sc['id']}.json"
        path.write_text(json.dumps(doc, separators=(",", ":")))
        index.append({"id": sc["id"], "title": sc["title"], "subtitle": sc["subtitle"],
                      "file": f"{sc['id']}.json", "bytes": path.stat().st_size})
        print(f"{sc['id']}: {path.stat().st_size / 1e6:.2f} MB, {len(doc['lotloc'])} moves")
    (out / "index.json").write_text(json.dumps({"seed": SEED, "instance": inst.name,
                                                "scenarios": index}, indent=2))


if __name__ == "__main__":
    main()
