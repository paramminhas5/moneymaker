"""Stationary block bootstrap (Politis and Romano 1994) for confidence intervals on metrics."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from mm.validation.metrics import FloatArray


def stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=np.int64)
    idx[0] = rng.integers(n)
    jumps = rng.random(n) < p
    starts = rng.integers(n, size=n)
    for i in range(1, n):
        idx[i] = starts[i] if jumps[i] else (idx[i - 1] + 1) % n
    return idx


def bootstrap_ci(
    r: FloatArray,
    stat: Callable[[FloatArray], float],
    *,
    n_boot: int = 1000,
    mean_block: float = 20.0,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """(point estimate, lower, upper) for `stat` with a (1 - alpha) percentile interval."""
    r = np.asarray(r, dtype=np.float64)
    r = r[np.isfinite(r)]
    rng = np.random.default_rng(seed)
    draws = np.array(
        [stat(r[stationary_bootstrap_indices(r.size, mean_block, rng)]) for _ in range(n_boot)]
    )
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return stat(r), float(lo), float(hi)
