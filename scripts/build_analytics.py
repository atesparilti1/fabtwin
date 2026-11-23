"""Collect benchmark outputs (results/*) into web/public/data/analytics.json.

Only numbers produced by the benchmark scripts are copied; missing sections are
simply omitted so the web UI shows them as not yet computed.
"""

from __future__ import annotations

import json
from pathlib import Path

RES = Path("results")
OUT = Path("web/public/data/analytics.json")

DISPATCH_KPIS = [
    ("mean_weighted_tardiness_h", "Weighted tardiness (h/lot)", "lower"),
    ("mean_ct_days", "Cycle time (days)", "lower"),
    ("on_time_pct", "On-time delivery (%)", "higher"),
    ("throughput_per_day", "Throughput (lots/day)", "higher"),
    ("qtime_viol_pct", "Q-time violations (%)", "lower"),
    ("litho_util", "Litho utilisation", "higher"),
]


def load(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    out: dict = {}
    d = load(RES / "dispatch" / "summary.json")
    if d:
        out["dispatch"] = {
            "replications": d["replications"],
            "instance": d["instance"]["name"],
            "kpis": [{"key": k, "label": lbl, "better": b} for k, lbl, b in DISPATCH_KPIS],
            "rows": [{"policy": rule, "values": {k: row[k] for k, _, _ in DISPATCH_KPIS if k in row}}
                     for rule, row in d["rules"].items()],
        }
    for name in ("exact", "scaling", "pareto", "convergence", "oht", "maintenance", "headline"):
        sec = load(RES / "web" / f"{name}.json")
        if sec:
            out[name] = sec
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print("sections:", sorted(out))


if __name__ == "__main__":
    main()
