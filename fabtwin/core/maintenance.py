"""Preventive-maintenance (PM) policy optimisation.

Policy class: age-based PM per tool group -- a machine is maintained when its
age (calendar time since the last repair or PM) reaches tau_g; PM and repair
both renew the machine. PM waits for the current job to finish.

Nominal plan (analytical)
    Classic age-replacement renewal-reward model per tool kind, minimising the
    long-run fraction of time down:

        D(tau) = [F(tau) MTTR + R(tau) T_PM] / [int_0^tau R(t) dt + F(tau) MTTR + R(tau) T_PM]

    with Weibull F, R = 1 - F. It ignores queueing: a down hour on the
    bottleneck costs the same as one on an idle tool, and it ignores repair
    variability.

Robust plan (simulation-based)
    Candidate policies scale the nominal intervals: tau_g = m_litho * tau*_g on
    litho and m_other * tau*_g elsewhere. Candidates are compared in the full
    stochastic simulator with common random numbers using a two-stage
    screen-and-select procedure (Nelson et al., 2001 style): stage 1 runs n0
    replications of every candidate and keeps those not significantly worse
    than the best (paired t-test); stage 2 adds n1 replications for survivors
    and selects the best mean. The selected policy is then validated on fresh
    seeds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import integrate
from scipy import stats as st

from fabtwin.core.instance import FailureModel, Instance


def downtime_fraction(f: FailureModel, tau: float | None) -> float:
    """Long-run down fraction (repairs + PMs) under age-based PM at ``tau``."""
    k, lam = f.weibull_shape, f.weibull_scale
    if tau is None or math.isinf(tau):
        return f.mttr_h / (f.mtbf_h + f.mttr_h)

    def R(t: float) -> float:
        return float(math.exp(-((t / lam) ** k)))

    up = float(integrate.quad(R, 0.0, tau)[0])
    F = 1.0 - R(tau)
    down = F * f.mttr_h + (1.0 - F) * f.pm_h
    return down / (up + down)


def nominal_tau(f: FailureModel, lo: float = 0.1, hi: float = 4.0, n: int = 400) -> float | None:
    """Availability-optimal PM interval, or None if PM never pays off."""
    best_t, best_d = None, downtime_fraction(f, None)
    for i in range(n + 1):
        t = f.mtbf_h * (lo + (hi - lo) * i / n)
        d = downtime_fraction(f, t)
        if d < best_d - 1e-12:
            best_t, best_d = t, d
    return best_t


def nominal_plan(inst: Instance) -> tuple[float | None, ...]:
    return tuple(nominal_tau(g.failure) if g.failure is not None else None for g in inst.groups)


def scaled_plan(inst: Instance, base: tuple[float | None, ...], m_litho: float | None,
                m_other: float | None) -> tuple[float | None, ...]:
    """tau_g = multiplier * nominal tau_g (None multiplier or None nominal = no PM)."""
    out = []
    for g, tau in zip(inst.groups, base):
        m = m_litho if g.kind == "litho" else m_other
        out.append(None if (m is None or tau is None) else round(m * tau, 2))
    return tuple(out)


@dataclass
class Screen:
    survivors: list[int]
    best: int


def screen(samples: list[list[float]], alpha: float = 0.05) -> Screen:
    """Keep candidates whose mean is not significantly worse than the best
    (paired t on CRN replications, Bonferroni over candidates; minimisation)."""
    k = len(samples)
    n = len(samples[0])
    means = [sum(s) / n for s in samples]
    best = min(range(k), key=lambda i: means[i])
    t = float(st.t.ppf(1 - alpha / max(1, k - 1), n - 1))
    keep = []
    for i in range(k):
        if i == best:
            keep.append(i)
            continue
        d = [a - b for a, b in zip(samples[i], samples[best])]
        md = sum(d) / n
        sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1)) if n > 1 else math.inf
        if md <= t * sd / math.sqrt(n):
            keep.append(i)
    return Screen(keep, best)
