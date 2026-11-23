"""Output analysis: confidence intervals, paired comparisons, warm-up detection."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scipy import stats as _st


@dataclass(frozen=True)
class CI:
    """Two-sided Student-t confidence interval of a mean."""

    mean: float
    half_width: float
    n: int
    level: float = 0.95

    @property
    def lo(self) -> float:
        return self.mean - self.half_width

    @property
    def hi(self) -> float:
        return self.mean + self.half_width

    def __str__(self) -> str:
        return f"{self.mean:.3f} ± {self.half_width:.3f}"


def mean_ci(xs: Sequence[float], level: float = 0.95) -> CI:
    """t-interval over independent replications (NaNs dropped)."""
    v = [x for x in xs if not math.isnan(x)]
    n = len(v)
    if n == 0:
        return CI(math.nan, math.nan, 0, level)
    m = sum(v) / n
    if n == 1:
        return CI(m, math.inf, 1, level)
    s = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    t = float(_st.t.ppf(0.5 + level / 2, n - 1))
    return CI(m, t * s / math.sqrt(n), n, level)


def paired_diff_ci(a: Sequence[float], b: Sequence[float], level: float = 0.95) -> CI:
    """CI of mean(a - b) over replications run with common random numbers."""
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    return mean_ci([x - y for x, y in zip(a, b)], level)


def relative_change_ci(new: Sequence[float], base: Sequence[float], level: float = 0.95) -> CI:
    """Paired CI of (new - base), expressed in % of mean(base)."""
    d = paired_diff_ci(new, base, level)
    mb = sum(base) / len(base)
    return CI(100 * d.mean / mb, 100 * d.half_width / abs(mb), d.n, level)


def mser(series: Sequence[float], batch: int = 5) -> int:
    """MSER-m truncation point (White, 1997) in units of observations.

    Batches the series in means of ``batch`` observations and returns the
    truncation index d minimising the standard error of the remaining mean;
    only the first half is searched, as recommended.
    """
    nb = len(series) // batch
    if nb < 4:
        return 0
    y = [sum(series[i * batch:(i + 1) * batch]) / batch for i in range(nb)]
    best_d, best = 0, math.inf
    for d in range(nb // 2):
        rest = y[d:]
        k = len(rest)
        m = sum(rest) / k
        val = sum((x - m) ** 2 for x in rest) / k**2
        if val < best:
            best_d, best = d, val
    return best_d * batch
