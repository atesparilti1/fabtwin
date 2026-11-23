"""Build the 2-page technical write-up (docs/fabtwin_writeup.pdf) from results/*.json.

Every number is read from the benchmark outputs; the HTML is printed to PDF
with headless Chrome/Edge.

    python scripts/build_writeup.py
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

RES = Path("results")
FIG = Path("docs/figures")
OUT_HTML = Path("docs/writeup.html")
OUT_PDF = Path("docs/fabtwin_writeup.pdf")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser",
]


def j(p: str):  # type: ignore[no-untyped-def]
    return json.loads((RES / p).read_text())


def img(name: str, width: str = "100%") -> str:
    p = FIG / name
    if not p.exists():
        return ""
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b64}" style="width:{width}">'


def pm(v: dict, d: int = 1) -> str:
    return f"{v['mean']:.{d}f}&nbsp;±&nbsp;{v['hw']:.{d}f}"


def main() -> None:
    disp, head = j("dispatch/summary.json"), j("headline/summary.json")
    small, scaling = j("exact/small.json"), j("exact/scaling.json")
    mnt, oht = j("maintenance/summary.json"), j("oht/summary.json")
    inst = disp["instance"]
    d = {x["label"]: x for x in head["deltas"]}

    def delta(kpi: str, ref: str) -> str:
        x = next(v for v in head["deltas"] if v["kpi"] == kpi and v["ref"] == ref)
        return f"{x['mean']:+.1f}%&nbsp;±&nbsp;{x['hw']:.1f}%"

    opt_rows = [r for r in small if r["cpsat_status"] == "OPTIMAL"]
    nz = [r for r in opt_rows if r["cpsat_obj"]]
    def mean_gap(key):  # type: ignore[no-untyped-def]
        g = [100 * ((min(r["heuristics"].values()) if key == "rule" else r[key]) - r["cpsat_obj"]) / r["cpsat_obj"] for r in nz]
        return sum(g) / len(g) if g else float("nan")
    mip_opt = [r for r in small if r.get("mip_status") == "Optimal"]
    agree = sum(1 for r in mip_opt if r["cpsat_status"] == "OPTIMAL" and abs(r["mip_obj"] - r["cpsat_obj"]) < 1e-6)
    rows_head = "".join(
        f"<tr><td>{r['policy']}</td>" + "".join(f"<td>{pm(r['values'][k], 2)}</td>" for k in
        ("mean_weighted_tardiness_h", "mean_ct_days", "on_time_pct", "qtime_viol_pct")) + "</tr>"
        for r in head["rows"])
    rows_m = "".join(
        f"<tr><td>{r['policy']}</td><td>{pm(r['mean_ct_days'], 3)}</td><td>{pm(r['mean_weighted_tardiness_h'], 2)}</td>"
        f"<td>{100 * r['down_frac']['mean']:.2f}%</td><td>{100 * r['pm_frac']['mean']:.2f}%</td></tr>"
        for r in mnt["rows"])
    rh = head.get("rolling_horizon")
    rh_txt = ""
    if rh:
        v = rh["vs_fabtwin_pct"]["mean_weighted_tardiness_h"]
        rh_txt = (f"Adding the rolling-horizon CP-SAT litho planner on top changed weighted tardiness by "
                  f"{v['mean']:+.1f}% ± {v['hw']:.1f}% ({rh['replications']} paired replications), "
                  "so ATCS already captures most of the litho sequencing value at this load.")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>FabTwin write-up</title>
<style>
@page {{ size: A4; margin: 13mm 14mm; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 8.6pt; line-height: 1.38; color: #1c2128; }}
h1 {{ font-size: 15pt; margin: 0 0 1mm; letter-spacing: -0.2px; }}
h2 {{ font-size: 9.6pt; margin: 3.2mm 0 1mm; color: #b45309; text-transform: uppercase; letter-spacing: .6px; }}
.sub {{ color: #6b7280; margin-bottom: 2mm; }}
.cols {{ column-count: 2; column-gap: 6mm; }}
table {{ border-collapse: collapse; width: 100%; font-size: 7.6pt; margin: 1mm 0 2mm; break-inside: avoid; }}
td, th {{ border-bottom: 0.4pt solid #d1d5db; padding: 0.8mm 1mm; text-align: right; }}
td:first-child, th:first-child {{ text-align: left; }}
th {{ color: #6b7280; font-weight: 600; }}
.fig {{ break-inside: avoid; margin: 1mm 0 2mm; }}
.cap {{ color: #6b7280; font-size: 7.2pt; }}
b {{ font-weight: 600; }}
</style></head><body>
<h1>FabTwin: stochastic scheduling and transport optimisation for a semiconductor fab</h1>
<div class="sub">Ates Parilti · Industrial Engineering, TU Eindhoven · code, data and live demo: github.com/atesparilti1/fabtwin · atesparilti1.github.io/fabtwin</div>
<div class="cols">
<h2>Problem</h2>
<p>Wafer fabs are re-entrant flexible job shops: a lot revisits lithography once per mask layer, furnaces process batches of up to 6 lots of the same recipe, scanners lose time on reticle changes, and some steps carry queue-time (Q-time) limits after which a lot must be re-cleaned or scrapped. Lots move on an overhead hoist transport (OHT) network, and tools fail stochastically. FabTwin models the three coupled layers (scheduling, transport, maintenance) and evaluates policies in a discrete-event digital twin under uncertainty.</p>
<p>The benchmark fab (<i>{inst['name']}</i>, synthetic, SMT2020-inspired, all parameters documented) has {inst['tool_groups']} tool groups, {inst['machines']} non-identical machines, {inst['products']} products with routes of {min(inst['route_steps'])}–{max(inst['route_steps'])} steps and {min(inst['litho_visits'])}–{max(inst['litho_visits'])} litho visits, {inst['release_lots_per_day']:.1f} lot starts/day plus hot lots, Weibull failures, lognormal repairs and processing times, 3% litho rework and a 4 h clean→furnace Q-time.</p>
<h2>Methods</h2>
<p><b>Exact.</b> A CP-SAT model (optional intervals, circuit constraints for sequence-dependent setups, pairwise batch synchronisation with a cumulative capacity, hard Q-time) and a time-indexed MIP solved with HiGHS give optima and lower bounds on static snapshot instances. <b>Heuristics.</b> Classic rules (FIFO, SPT, EDD, ODD, CR, ATC), setup-aware ATCS, a bottleneck-first decomposition that sequences litho with CP-SAT and dispatches the rest around it, and ALNS with problem-specific operators (batch merge, setup-aware litho resequencing, Q-time repair) on priority vectors decoded by active/non-delay schedule generation. <b>Transport.</b> Vehicles are assigned per decision epoch with the Hungarian algorithm (priority credits for hot and Q-time lots), routed by congestion-aware A*, and booked with headway time-window reservations, which excludes collisions and deadlocks by construction. <b>Maintenance.</b> Age-based PM: the nominal plan minimises per-tool downtime analytically (renewal reward); the robust plan is selected in the stochastic simulator by two-stage screening and selection with common random numbers, then validated on fresh seeds. <b>Simulation methodology.</b> Own event engine; 120-day runs, 30-day warm-up (MSER-5 suggests day {disp['warmup']['mser5_truncation_day']}), {disp['replications']} replications, CRN via per-entity random streams, paired 95% t-intervals. Little's law holds within {100 * max(r['little_rel_err']['mean'] for r in disp['rules'].values()):.1f}% on average.</p>
<h2>Exact vs heuristic</h2>
<p>CP-SAT proved optimality on {len(opt_rows)}/{len(small)} small instances (≤{max(r['ops'] for r in small)} operations); the time-indexed MIP reached proven optimality on {len(mip_opt)} of them and agreed with CP-SAT on all {agree}. Mean gap to the optimum on instances with a non-zero optimum: best dispatching rule {mean_gap('rule'):.1f}%, bottleneck-first decomposition {mean_gap('sbh'):.1f}%, ALNS {mean_gap('alns'):.1f}%. CP-SAT scales to {max(r['ops'] for r in scaling)} operations within 60 s but its lower bound weakens quickly (figure).</p>
<div class="fig">{img('exact_gaps.png')}</div>
<h2>Coupled fab results</h2>
<table><tr><th>Policy ({head['replications']} reps)</th><th>W. tardiness (h)</th><th>CT (days)</th><th>On-time %</th><th>Q-time viol. %</th></tr>{rows_head}</table>
<p>The FabTwin policy (ATCS litho dispatching + Hungarian OHT + robust PM) changes weighted tardiness by <b>{delta('mean_weighted_tardiness_h', 'CR baseline')}</b> and cycle time by <b>{delta('mean_ct_days', 'CR baseline')}</b> versus critical-ratio dispatching (paired 95% CI). {rh_txt}</p>
<div class="fig">{img('headline.png')}</div>
<h2>Maintenance: robust vs nominal</h2>
<table><tr><th>Policy ({mnt['validation_reps']} fresh reps)</th><th>CT (days)</th><th>W. tard. (h)</th><th>Down</th><th>PM</th></tr>{rows_m}</table>
<p>Selected multipliers: litho {mnt['selected']['m_litho']}, other tools {mnt['selected']['m_other']}. Robust vs nominal: cycle time {mnt['deltas']['mean_ct_days vs Nominal PM (availability-optimal)']['mean']:+.1f}% ± {mnt['deltas']['mean_ct_days vs Nominal PM (availability-optimal)']['hw']:.1f}%, unplanned downtime {mnt['deltas']['down_frac vs Nominal PM (availability-optimal)']['mean']:+.1f}% ± {mnt['deltas']['down_frac vs Nominal PM (availability-optimal)']['hw']:.1f}%; versus run-to-failure, unplanned downtime {mnt['deltas']['down_frac vs Run-to-failure']['mean']:+.1f}% ± {mnt['deltas']['down_frac vs Run-to-failure']['hw']:.1f}%.</p>
<div class="fig">{img('oht.png')}<div class="cap">OHT: fleet size vs vehicle dispatching ({oht['replications']} CRN replications, ATCS dispatching).</div></div>
<h2>Limitations</h2>
<p>Synthetic fab (SMT2020 structure, not its data); no operator, reticle-availability or engineering-hold constraints; point vehicles at constant speed, stocker-to-tool hand-off instantaneous; failures on calendar time with preempt-resume; static exact models use 0.1 h discretisation; ALNS is limited by its schedule-generation scheme (reported gaps show it). The browser what-if mode is a simplified TypeScript port; all reported numbers come from the Python engine and are regenerated by <i>make bench</i>.</p>
</div></body></html>"""
    OUT_HTML.write_text(html, encoding="utf-8")
    exe = next((b for b in BROWSERS if Path(b).exists() or shutil.which(b)), None)
    if exe is None:
        print("no headless browser found; wrote", OUT_HTML)
        return
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={OUT_PDF.resolve()}", OUT_HTML.resolve().as_uri()],
                   check=True, timeout=120, capture_output=True)
    print("wrote", OUT_PDF)


if __name__ == "__main__":
    main()
