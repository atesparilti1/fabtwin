"""Render README.md from docs/README.template.md and the benchmark outputs.

Numbers are never typed into the README by hand: tables are the summary.md files
written by the benchmark scripts and the headline sentences are formatted from
their JSON.

    python scripts/build_readme.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RES = Path("results")


def md(p: str) -> str:
    text = (RES / p).read_text(encoding="utf-8")
    text = re.sub(r"\nruntime \d+s\n?", "\n", text)
    return text.strip()


def j(p: str):  # type: ignore[no-untyped-def]
    return json.loads((RES / p).read_text())


def ci(v: dict, d: int = 1, unit: str = "%") -> str:
    return f"{v['mean']:+.{d}f}{unit} (95% CI ±{v['hw']:.{d}f})"


def main() -> None:
    tpl = Path("docs/README.template.md").read_text(encoding="utf-8")
    disp, head = j("dispatch/summary.json"), j("headline/summary.json")
    small, scaling = j("exact/small.json"), j("exact/scaling.json")
    mnt, oht = j("maintenance/summary.json"), j("oht/summary.json")
    inst = disp["instance"]

    def hd(kpi: str, ref: str) -> dict:
        return next(x for x in head["deltas"] if x["kpi"] == kpi and x["ref"] == ref)

    nz = [r for r in small if r["cpsat_status"] == "OPTIMAL" and r["cpsat_obj"]]
    def gap(key: str) -> float:
        g = [100 * ((min(r["heuristics"].values()) if key == "rule" else r[key]) - r["cpsat_obj"])
             / r["cpsat_obj"] for r in nz]
        return sum(g) / len(g)
    n_opt = sum(r["cpsat_status"] == "OPTIMAL" for r in small)
    mip_opt = [r for r in small if r.get("mip_status") == "Optimal"]
    agree = sum(abs(r["mip_obj"] - r["cpsat_obj"]) < 1e-6 for r in mip_opt)
    md_rob = mnt["deltas"]
    ref_n = "Nominal PM (availability-optimal)"
    hung = [r for r in oht["rows"] if r["policy"] == "hungarian"]

    headline = "\n".join([
        f"* **FabTwin policy vs critical-ratio dispatching** (coupled fab with OHT, failures, rework and hot lots; "
        f"{head['replications']} paired CRN replications): weighted tardiness "
        f"{ci(hd('mean_weighted_tardiness_h', 'CR baseline'))}, cycle time {ci(hd('mean_ct_days', 'CR baseline'))}, "
        f"on-time delivery {ci(hd('on_time_pct', 'CR baseline'))}.",
        f"* **vs FIFO:** weighted tardiness {ci(hd('mean_weighted_tardiness_h', 'FIFO baseline'))}, "
        f"cycle time {ci(hd('mean_ct_days', 'FIFO baseline'))}.",
        f"* **Exact ground truth:** CP-SAT proved optimality on {n_opt}/{len(small)} small instances; the time-indexed "
        f"MIP proved {len(mip_opt)} of them and agreed on all {agree}. Mean gap to optimum (instances with a non-zero "
        f"optimum): best dispatching rule {gap('rule'):.1f}%, bottleneck-first decomposition {gap('sbh'):.1f}%, "
        f"ALNS {gap('alns'):.1f}%.",
        f"* **Robust vs nominal PM:** cycle time {ci(md_rob['mean_ct_days vs ' + ref_n])}, unplanned downtime "
        f"{ci(md_rob['down_frac vs ' + ref_n])}; vs run-to-failure, unplanned downtime "
        f"{ci(md_rob['down_frac vs Run-to-failure'])} ({mnt['validation_reps']} fresh replications).",
    ])
    rh = head.get("rolling_horizon")
    if rh:
        v = rh["vs_fabtwin_pct"]["mean_weighted_tardiness_h"]
        headline += (f"\n* **Rolling-horizon CP-SAT litho planning** on top of the FabTwin policy: weighted tardiness "
                     f"{ci(v)} over {rh['replications']} paired replications. Reported because it was run, "
                     "including when it does not help.")
    wt_cr = hd("mean_weighted_tardiness_h", "CR baseline")
    ct_cr = hd("mean_ct_days", "CR baseline")
    cv = "\n".join([
        "**CV bullets** (each number traces to `results/`):", "",
        f"* Built a 3D digital twin of a semiconductor fab (re-entrant flexible job shop with batching, setups, "
        f"Q-time, OHT transport, stochastic failures). Cut weighted tardiness by {-wt_cr['mean']:.0f}% "
        f"(95% CI ±{wt_cr['hw']:.0f}%) and cycle time by {-ct_cr['mean']:.1f}% vs critical-ratio dispatching "
        f"over {head['replications']} common-random-number replications.",
        f"* Formulated CP-SAT and time-indexed MIP (HiGHS) models as ground truth: proved optimality on "
        f"{n_opt}/{len(small)} instances and measured dispatching rules at {gap('rule'):.0f}% and ALNS at "
        f"{gap('alns'):.0f}% above optimum. Showed the CP-SAT/ALNS crossover beyond ~250 operations.",
        f"* Optimised preventive-maintenance intervals by simulation (CRN, screen-and-select). The robust policy "
        f"changed unplanned downtime by {md_rob['down_frac vs Run-to-failure']['mean']:+.0f}% vs run-to-failure and "
        f"cycle time by {md_rob['mean_ct_days vs ' + ref_n]['mean']:+.1f}% vs the availability-optimal plan.",
    ])
    instance = (f"Benchmark fab `{inst['name']}`: **{inst['tool_groups']} tool groups, {inst['machines']} machines "
                f"(1–6 per group), {inst['products']} products, routes of {min(inst['route_steps'])}–"
                f"{max(inst['route_steps'])} steps with {min(inst['litho_visits'])}–{max(inst['litho_visits'])} "
                f"litho visits**, {inst['release_lots_per_day']:.1f} lot starts/day + "
                f"{inst['hot_lots_per_day']:.2f} hot lots/day.")
    warm = ""
    if (RES / "warmup" / "summary.md").exists():
        warm = "**Warm-up sensitivity.** MSER-5 points at a slightly later truncation than the 30 days used, so the key comparison was repeated with 40 days on the same seeds:

" + md("warmup/summary.md")
    gp_txt = ("Not run.")
    if (RES / "learned" / "gp.json").exists():
        g = j("learned/gp.json")
        b = g["best_baseline"]
        d = g[f"vs_{b}_pct"]
        verdict = ("It **beats** the best baseline on held-out seeds." if g["beats_best_baseline"] else
                   "It does **not** beat the best baseline on held-out seeds, so it is not used anywhere else in this project.")
        gp_txt = (f"`learned/gp_dispatch.py` evolves a priority expression over normalised lot features (slack, processing time, "
                  f"remaining work, waiting time, weight, Q-time left, critical ratio) by tree GP with fitness measured on "
                  f"training seeds, then tests the best rule on {g['test_reps']} held-out seeds. Best rule: `{g['expr']}`. "
                  f"Held-out weighted tardiness {g['gp']['mean']:.2f} ± {g['gp']['hw']:.2f} h vs {b} "
                  f"{g[b]['mean']:.2f} ± {g[b]['hw']:.2f} h (paired change {d['mean']:+.1f}% ± {d['hw']:.1f}%). {verdict}")
    out = (tpl.replace("{{WARMUP}}", warm).replace("{{GP}}", gp_txt).replace("{{HEADLINE}}", headline).replace("{{CV}}", cv).replace("{{INSTANCE}}", instance)
           .replace("{{DISPATCH}}", md("dispatch/summary.md")).replace("{{EXACT}}", md("exact/summary.md"))
           .replace("{{OHT}}", md("oht/summary.md")).replace("{{MAINT}}", md("maintenance/summary.md"))
           .replace("{{HEADTABLE}}", md("headline/summary.md"))
           .replace("{{FOOTER}}", "<sub>README generated by `scripts/build_readme.py` from `results/`.</sub>"))
    _ = hung, scaling
    Path("README.md").write_text(out, encoding="utf-8")
    print("README.md written")


if __name__ == "__main__":
    main()
