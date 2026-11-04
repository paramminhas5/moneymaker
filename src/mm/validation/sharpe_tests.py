"""Probabilistic and Deflated Sharpe Ratios (Bailey and Lopez de Prado, 2012 and 2014).

All Sharpe ratios here are per-period (not annualised), matching the papers.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

from mm.validation.metrics import FloatArray, sharpe, skew_kurt

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def probabilistic_sharpe(
    sr_hat: float, sr_benchmark: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0
) -> float:
    """P(true SR > benchmark) given an observed per-period SR, sample size and higher moments."""
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat**2
    if denom <= 0:
        return 0.0
    z = (sr_hat - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _N.cdf(z)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum per-period SR among n_trials skill-less strategies (False Strategy Thm)."""
    if n_trials <= 1 or sr_variance <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(
    returns: FloatArray, n_trials: int, trial_sharpes: FloatArray | None = None
) -> float:
    """DSR: PSR against the SR a skill-less search over n_trials would be expected to find.

    `trial_sharpes` are the per-period SRs of every variant tried (from the experiment log).
    Without them, the variance of SR under the null is approximated as 1/(T-1).
    """
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    sr = sharpe(r, annualize=False)
    s, k = skew_kurt(r)
    if trial_sharpes is not None and len(trial_sharpes) > 1:
        var = float(np.var(np.asarray(trial_sharpes, dtype=np.float64), ddof=1))
    else:
        var = 1.0 / max(r.size - 1, 1)
    sr0 = expected_max_sharpe(max(n_trials, 1), var)
    return probabilistic_sharpe(sr, sr0, r.size, s, k)


def min_track_record_length(
    sr_hat: float, sr_benchmark: float, skew: float = 0.0, kurt: float = 3.0, prob: float = 0.95
) -> float:
    """Observations needed for PSR to reach `prob` (per-period SRs)."""
    if sr_hat <= sr_benchmark:
        return math.inf
    z = _N.inv_cdf(prob)
    return (
        1.0
        + (1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat**2)
        * (z / (sr_hat - sr_benchmark)) ** 2
    )
