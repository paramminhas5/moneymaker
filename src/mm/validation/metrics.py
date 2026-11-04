"""Performance metrics on periodic simple returns (numpy arrays, NaN-free)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def _clean(r: FloatArray) -> FloatArray:
    r = np.asarray(r, dtype=np.float64)
    return r[np.isfinite(r)]


def sharpe(r: FloatArray, periods_per_year: float = 365.0, *, annualize: bool = True) -> float:
    r = _clean(r)
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    sr = float(r.mean() / sd)
    return sr * math.sqrt(periods_per_year) if annualize else sr


def sortino(r: FloatArray, periods_per_year: float = 365.0) -> float:
    r = _clean(r)
    downside = r[r < 0]
    if r.size < 2 or downside.size < 2:
        return 0.0
    dd = math.sqrt(float(np.mean(downside**2)))
    return float(r.mean() / dd * math.sqrt(periods_per_year)) if dd else 0.0


def equity_curve(r: FloatArray) -> FloatArray:
    return np.cumprod(1.0 + _clean(r))


def max_drawdown(r: FloatArray) -> float:
    """Largest peak-to-trough loss as a positive fraction (0.25 = -25%)."""
    eq = equity_curve(r)
    if eq.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float(np.max(1.0 - eq / peaks))


def cagr(r: FloatArray, periods_per_year: float = 365.0) -> float:
    eq = equity_curve(r)
    if eq.size == 0 or eq[-1] <= 0:
        return -1.0 if eq.size else 0.0
    years = eq.size / periods_per_year
    return float(eq[-1] ** (1 / years) - 1)


def skew_kurt(r: FloatArray) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis, as used in the PSR/DSR formulas."""
    r = _clean(r)
    if r.size < 4:
        return 0.0, 3.0
    d = r - r.mean()
    m2 = float(np.mean(d**2))
    if m2 == 0:
        return 0.0, 3.0
    return float(np.mean(d**3) / m2**1.5), float(np.mean(d**4) / m2**2)


@dataclass(frozen=True, slots=True)
class Summary:
    n: int
    total_return: float
    cagr: float
    vol: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    skew: float
    kurtosis: float
    hit_rate: float

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}


def summarize(r: FloatArray, periods_per_year: float = 365.0) -> Summary:
    r = _clean(r)
    eq = equity_curve(r)
    mdd = max_drawdown(r)
    g = cagr(r, periods_per_year)
    s, k = skew_kurt(r)
    return Summary(
        n=int(r.size),
        total_return=float(eq[-1] - 1) if eq.size else 0.0,
        cagr=g,
        vol=float(r.std(ddof=1) * math.sqrt(periods_per_year)) if r.size > 1 else 0.0,
        sharpe=sharpe(r, periods_per_year),
        sortino=sortino(r, periods_per_year),
        max_drawdown=mdd,
        calmar=g / mdd if mdd > 0 else 0.0,
        skew=s,
        kurtosis=k,
        hit_rate=float(np.mean(r[r != 0] > 0)) if np.any(r != 0) else 0.0,
    )
