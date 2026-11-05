"""Walk-forward selection. Each fold picks the best variant on its training window only and is
scored on the following test window. The concatenated test windows form the OOS track record.

Variant return series must be computed causally (verified by the no-lookahead harness), so
slicing a full-history series by date is equivalent to re-running the strategy on that window.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mm.validation.metrics import FloatArray, sharpe


@dataclass(frozen=True, slots=True)
class Fold:
    train_start: int
    train_end: int  # exclusive
    test_start: int
    test_end: int  # exclusive


def make_folds(
    n: int, train: int, test: int, *, anchored: bool = False, embargo: int = 0
) -> list[Fold]:
    """Rolling (or anchored) folds with an optional embargo gap between train and test."""
    if train <= 0 or test <= 0:
        raise ValueError("train and test must be positive")
    folds: list[Fold] = []
    start = 0
    while True:
        tr_end = start + train
        te_start = tr_end + embargo
        te_end = te_start + test
        if te_end > n:
            break
        folds.append(Fold(0 if anchored else start, tr_end, te_start, te_end))
        start += test
    return folds


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    oos_returns: FloatArray
    chosen: list[int]  # variant index chosen per fold
    folds: list[Fold]
    oos_start: int

    @property
    def stability(self) -> float:
        """Share of folds that chose the most common variant (1.0 = always the same)."""
        if not self.chosen:
            return 0.0
        _, counts = np.unique(self.chosen, return_counts=True)
        return float(counts.max() / len(self.chosen))


def walk_forward_select(
    variant_returns: FloatArray,
    folds: list[Fold],
    periods_per_year: float = 365.0,
) -> WalkForwardResult:
    """variant_returns: T x N matrix of per-period net returns, one column per variant."""
    m = np.asarray(variant_returns, dtype=np.float64)
    if m.ndim != 2:
        raise ValueError("expected a T x N matrix")
    pieces: list[FloatArray] = []
    chosen: list[int] = []
    for f in folds:
        train = m[f.train_start : f.train_end]
        scores = [sharpe(train[:, j], periods_per_year) for j in range(m.shape[1])]
        best = int(np.argmax(scores))
        chosen.append(best)
        pieces.append(m[f.test_start : f.test_end, best])
    oos = np.concatenate(pieces) if pieces else np.array([], dtype=np.float64)
    return WalkForwardResult(oos, chosen, folds, folds[0].test_start if folds else 0)
