"""Render README / write-up figures from results/*.json (no numbers are typed in)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RES = Path("results")
FIG = Path("docs/figures")
INK, MUTED, ACCENT, ACCENT2, GRID = "#1c2128", "#6b7280", "#d97706", "#0e7490", "#e5e7eb"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "figure.dpi": 150,
    "savefig.bbox": "tight",
})


def load(p: Path):  # type: ignore[no-untyped-def]
    return json.loads(p.read_text()) if p.exists() else None


def ci_bars(ax, labels, means, hws, highlight=None, xlabel=""):  # type: ignore[no-untyped-def]
    y = range(len(labels))
    colors = [ACCENT if (highlight and lab in highlight) else ACCENT2 for lab in labels]
    ax.barh(list(y), means, xerr=hws, color=colors, alpha=0.85, height=0.6,
            error_kw={"ecolor": INK, "elinewidth": 1, "capsize": 3})
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)


def fig_dispatch() -> None:
    d = load(RES / "dispatch" / "summary.json")
    if not d:
        return
    fig, axes = plt.subplots(1, 2, figsize=(8, 2.8))
    rules = list(d["rules"])
    for ax, k, lbl in zip(axes, ("mean_weighted_tardiness_h", "mean_ct_days"),
                          ("Weighted tardiness (h/lot)", "Cycle time (days)")):
        ci_bars(ax, rules, [d["rules"][r][k]["mean"] for r in rules],
                [d["rules"][r][k]["hw"] for r in rules], highlight={"ATCS", "ATC"}, xlabel=lbl)
    fig.suptitle(f"Dispatching rules, {d['replications']} CRN replications, mean ± 95% CI",
                 x=0.01, ha="left", fontsize=10, color=INK)
    fig.savefig(FIG / "dispatch_ci.png")
    plt.close(fig)


def fig_exact() -> None:
    small = load(RES / "exact" / "small.json")
    scaling = load(RES / "exact" / "scaling.json")
    if small:
        fig, ax = plt.subplots(figsize=(8, 2.8))
        names, rule_gap, sbh_gap, alns_gap = [], [], [], []
        for r in small:
            if r["cpsat_status"] != "OPTIMAL" or not r["cpsat_obj"]:
                continue
            opt = r["cpsat_obj"]
            names.append(r["instance"].replace("tiny-", ""))
            rule_gap.append(100 * (min(r["heuristics"].values()) - opt) / opt)
            sbh_gap.append(100 * (r["sbh"] - opt) / opt)
            alns_gap.append(100 * (r["alns"] - opt) / opt)
        x = range(len(names))
        w = 0.27
        ax.bar([i - w for i in x], rule_gap, w, color=MUTED, label="best dispatch rule")
        ax.bar(list(x), sbh_gap, w, color=ACCENT2, label="bottleneck-first (SBH)")
        ax.bar([i + w for i in x], alns_gap, w, color=ACCENT, label="ALNS")
        ax.set_xticks(list(x), names, rotation=30, ha="right")
        ax.set_ylabel("gap to CP-SAT optimum (%)")
        ax.legend(frameon=False, ncols=3, loc="lower left", bbox_to_anchor=(0, 1.0))
        ax.set_title("Small instances with proven optima (non-zero optimum only)", loc="left", fontsize=10, pad=22)
        fig.savefig(FIG / "exact_gaps.png")
        plt.close(fig)
    if scaling:
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        by: dict[int, list] = {}
        for r in scaling:
            by.setdefault(r["ops"], []).append(r)
        ops = sorted(by)
        for key, lbl, c in (("best_rule", "best rule", MUTED), ("sbh", "SBH", ACCENT2),
                            ("alns", "ALNS (30 s)", ACCENT), ("cpsat_obj", "CP-SAT (60 s)", INK)):
            xs = [o for o in ops if all(x[key] is not None for x in by[o])]
            ys = [sum(x[key] for x in by[o]) / len(by[o]) for o in xs]
            ax.plot(xs, ys, marker="o", color=c, label=lbl, lw=1.4, ms=3)
        miss = [o for o in ops if any(x["cpsat_obj"] is None for x in by[o])]
        for o in miss:
            ax.annotate("CP-SAT: no solution in 60 s\n(at least one seed)", (o, ax.get_ylim()[0]),
                        fontsize=6.5, color=MUTED,
                        ha="center", va="bottom", xytext=(0, 4), textcoords="offset points")
        lb = [sum(x["cpsat_bound"] for x in by[o]) / len(by[o]) for o in ops]
        ax.plot(ops, lb, ls="--", color=INK, lw=1, label="CP-SAT lower bound")
        ax.set_xlabel("operations")
        ax.set_ylabel("weighted tardiness (units)")
        ax.set_yscale("log")
        ax.legend(frameon=False, fontsize=7)
        ax.set_title("Scaling (CP-SAT line ends where a seed found\nno solution within 60 s)",
                     loc="left", fontsize=9)
        fig.savefig(FIG / "scaling.png")
        plt.close(fig)


def fig_pareto_conv() -> None:
    par = load(RES / "exact" / "pareto.json")
    conv = load(RES / "exact" / "convergence.json")
    if par:
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        fr = sorted(par["front"], key=lambda p: p["flow_h"])
        ax.plot([p["flow_h"] for p in fr], [p["wt"] for p in fr], "-o", color=INK, ms=3, lw=1.2,
                label="exact front (CP-SAT ε-constraint)")
        groups: dict[tuple[float, float], list[str]] = {}
        for m in par["methods"]:
            groups.setdefault((round(m["flow_h"], 4), m["wt"]), []).append(m["method"])
        for i, ((fx, wy), names) in enumerate(sorted(groups.items())):
            ax.scatter(fx, wy, color=ACCENT if "ALNS" in names else ACCENT2, s=18, zorder=3)
            ax.annotate(", ".join(names), (fx, wy), fontsize=7, color=MUTED,
                        xytext=(4, 4 + 9 * (i % 2)), textcoords="offset points")
        ax.set_xlabel("mean flow time (h/lot)")
        ax.set_ylabel("weighted tardiness")
        ax.legend(frameon=False, fontsize=7)
        ax.set_title(f"Pareto front ({par['instance']})", loc="left", fontsize=10)
        fig.savefig(FIG / "pareto.png")
        plt.close(fig)
    if conv:
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        for i, s in enumerate(conv["series"]):
            ax.plot(s["time"], s["best"], color=[ACCENT, ACCENT2, INK][i % 3], lw=1.3, label=s["name"])
            ax.plot(s["time"], s["current"], color=[ACCENT, ACCENT2, INK][i % 3], lw=0.5, alpha=0.35)
        ax.set_xlabel("seconds")
        ax.set_ylabel("objective (best / current)")
        ax.legend(frameon=False, fontsize=7)
        ax.set_title(f"ALNS convergence ({conv['instance']})", loc="left", fontsize=10)
        fig.savefig(FIG / "convergence.png")
        plt.close(fig)


def fig_ops() -> None:
    oht = load(RES / "oht" / "summary.json")
    mnt = load(RES / "maintenance" / "summary.json")
    head = load(RES / "headline" / "summary.json")
    if oht:
        fig, axes = plt.subplots(1, 2, figsize=(8, 2.6))
        for ax, k, lbl in zip(axes, ("oht_mean_wait_min", "qtime_viol_pct"),
                              ("wait for vehicle (min)", "Q-time violations (%)")):
            for pol, c in (("nearest", MUTED), ("hungarian", ACCENT)):
                rows = [r for r in oht["rows"] if r["policy"] == pol]
                ax.errorbar([r["vehicles"] for r in rows], [r[k]["mean"] for r in rows],
                            yerr=[r[k]["hw"] for r in rows], marker="o", ms=3, color=c, label=pol, capsize=3)
            ax.set_xlabel("OHT vehicles")
            ax.set_ylabel(lbl)
            ax.legend(frameon=False)
        fig.suptitle("OHT fleet size and dispatching", x=0.01, ha="left", fontsize=10)
        fig.savefig(FIG / "oht.png")
        plt.close(fig)
    if mnt:
        fig, axes = plt.subplots(1, 2, figsize=(8, 2.4))
        labels = [r["policy"].split(" (")[0] for r in mnt["rows"]]
        for ax, k, lbl, scale in zip(axes, ("mean_ct_days", "down_frac"),
                                     ("cycle time (days)", "unplanned down (%)"), (1, 100)):
            ci_bars(ax, labels, [scale * r[k]["mean"] for r in mnt["rows"]],
                    [scale * r[k]["hw"] for r in mnt["rows"]], highlight={"Robust PM"}, xlabel=lbl)
            if ax is not axes[0]:
                ax.set_yticks([])
        fig.suptitle(f"Maintenance policies, {mnt['validation_reps']} fresh replications",
                     x=0.01, ha="left", fontsize=10)
        fig.savefig(FIG / "maintenance.png")
        plt.close(fig)
    if head:
        fig, axes = plt.subplots(1, 3, figsize=(9, 2.4))
        labels = [r["policy"] for r in head["rows"]]
        for ax, k, lbl in zip(axes, ("mean_weighted_tardiness_h", "mean_ct_days", "on_time_pct"),
                              ("weighted tardiness (h/lot)", "cycle time (days)", "on-time (%)")):
            ci_bars(ax, labels, [r["values"][k]["mean"] for r in head["rows"]],
                    [r["values"][k]["hw"] for r in head["rows"]], highlight={"FabTwin"}, xlabel=lbl)
            if ax is not axes[0]:
                ax.set_yticks([])
        fig.suptitle(f"Coupled fab, {head['replications']} CRN replications, mean ± 95% CI",
                     x=0.01, ha="left", fontsize=10)
        fig.savefig(FIG / "headline.png")
        plt.close(fig)


def fig_warmup() -> None:
    d = load(RES / "dispatch" / "summary.json")
    if not d:
        return
    w = d["warmup"]
    fig, ax = plt.subplots(figsize=(4.2, 2.4))
    ax.plot(range(len(w["mean_daily_wip"])), w["mean_daily_wip"], color=ACCENT2, lw=1.3)
    ax.axvline(w["mser5_truncation_day"], color=ACCENT, ls="--", lw=1)
    ax.axvline(d["instance"]["warmup_days"], color=INK, ls=":", lw=1)
    ax.set_xlabel("day")
    ax.set_ylabel("mean WIP (lots)")
    ax.set_title(f"Warm-up: MSER-5 = day {w['mser5_truncation_day']}, used {d['instance']['warmup_days']:.0f}",
                 loc="left", fontsize=10)
    fig.savefig(FIG / "warmup.png")
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig_dispatch()
    fig_exact()
    fig_pareto_conv()
    fig_ops()
    fig_warmup()
    print(sorted(p.name for p in FIG.glob("*.png")))


if __name__ == "__main__":
    main()
