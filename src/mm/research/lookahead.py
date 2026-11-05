"""No-lookahead harness: a signal computed on data up to t must equal the full-history signal at t.

If any value at or before a cut point changes when future rows are removed, the signal peeked.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import polars as pl


class LookaheadError(AssertionError):
    pass


def assert_no_lookahead(
    signal_fn: Callable[[pl.DataFrame], pl.DataFrame],
    data: pl.DataFrame,
    *,
    n_cuts: int = 8,
    seed: int = 0,
    min_rows: int = 50,
    atol: float = 1e-12,
) -> None:
    """`signal_fn(data) -> frame with ts + numeric columns`. Raises LookaheadError on a mismatch."""
    data = data.sort("ts")
    full = signal_fn(data)
    rng = np.random.default_rng(seed)
    if data.height <= min_rows + 1:
        raise ValueError("not enough rows to test")
    cuts = sorted(set(rng.integers(min_rows, data.height - 1, size=n_cuts).tolist()))
    cols = [c for c in full.columns if c != "ts"]
    for k in cuts:
        t_cut = data["ts"][k]
        part = signal_fn(data.filter(pl.col("ts") <= t_cut))
        a = full.filter(pl.col("ts") <= t_cut).select(cols).to_numpy().astype(np.float64)
        b = part.filter(pl.col("ts") <= t_cut).select(cols).to_numpy().astype(np.float64)
        if a.shape != b.shape:
            raise LookaheadError(f"shape changed at cut {t_cut}: {a.shape} vs {b.shape}")
        same = np.isclose(a, b, atol=atol, rtol=0, equal_nan=True)
        if not same.all():
            row, col = np.argwhere(~same)[0]
            raise LookaheadError(
                f"signal '{cols[col]}' at row {row} changed when data after {t_cut} was removed "
                f"({a[row, col]} vs {b[row, col]})"
            )
