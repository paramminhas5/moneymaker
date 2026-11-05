"""Probability of Backtest Overfitting via Combinatorially Symmetric Cross-Validation.

Bailey, Borwein, Lopez de Prado, Zhu (2014). Input: a T x N matrix of per-period returns, one
column per strategy variant tried. PBO is the share of IS/OOS splits where the variant that was
best in-sample ranks at or below the median out-of-sample.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np

from mm.validation.metrics import FloatArray


@dataclass(frozen=True, slots=True)
class PBOResult:
    pbo: float
    logits: FloatArray
    n_splits: int
    perf_degradation_slope: float  # OOS SR regressed on IS SR of the chosen variant


def _sharpe_cols(m: FloatArray) -> FloatArray:
    sd = m.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = np.where(sd > 0, m.mean(axis=0) / sd, 0.0)
    return np.asarray(sr, dtype=np.float64)


def pbo_cscv(
    returns: FloatArray, n_blocks: int = 16, max_splits: int | None = None, seed: int = 0
) -> PBOResult:
    m = np.asarray(returns, dtype=np.float64)
    if m.ndim != 2 or m.shape[1] < 2:
        raise ValueError("need a T x N matrix with at least 2 variants")
    if n_blocks % 2 or n_blocks < 2:
        raise ValueError("n_blocks must be even")
    t = m.shape[0] - m.shape[0] % n_blocks
    blocks = np.array_split(m[:t], n_blocks)
    combos = list(itertools.combinations(range(n_blocks), n_blocks // 2))
    if max_splits and len(combos) > max_splits:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(combos), size=max_splits, replace=False)
        combos = [combos[i] for i in sorted(idx)]

    n = m.shape[1]
    logits: list[float] = []
    is_best: list[float] = []
    oos_of_best: list[float] = []
    for is_idx in combos:
        oos_idx = [i for i in range(n_blocks) if i not in is_idx]
        is_sr = _sharpe_cols(np.vstack([blocks[i] for i in is_idx]))
        oos_sr = _sharpe_cols(np.vstack([blocks[i] for i in oos_idx]))
        best = int(np.argmax(is_sr))
        rank = int((oos_sr < oos_sr[best]).sum()) + 1  # 1 = worst, n = best
        omega = rank / (n + 1)
        logits.append(math.log(omega / (1 - omega)))
        is_best.append(float(is_sr[best]))
        oos_of_best.append(float(oos_sr[best]))

    arr = np.asarray(logits, dtype=np.float64)
    slope = float(np.polyfit(is_best, oos_of_best, 1)[0]) if len(set(is_best)) > 1 else 0.0
    return PBOResult(
        pbo=float(np.mean(arr <= 0)), logits=arr, n_splits=len(combos), perf_degradation_slope=slope
    )
