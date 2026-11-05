"""Cleaning helpers for free daily data (Yahoo in particular).

`drop_reversal_spikes` removes isolated bad prints: a bar that jumps by more than `threshold`
from the previous close and jumps back by more than `threshold` on the next bar. Real moves of
that size almost never fully reverse the next day; bad ticks (e.g. a split applied to one row)
do. This peeks one bar ahead, so it is a data-repair step on stored history, never a signal.
In live trading a print like that is caught by the data-quality checks before any order.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl


def drop_reversal_spikes(df: pl.DataFrame, column: str, threshold: float = 0.25) -> pl.DataFrame:
    r_in = pl.col(column) / pl.col(column).shift(1) - 1
    r_out = pl.col(column).shift(-1) / pl.col(column) - 1
    spike = (r_in.abs() > threshold) & (r_out.abs() > threshold) & (r_in.sign() != r_out.sign())
    return df.filter(~spike.fill_null(False))


def weekday_calendar(close: pl.DataFrame) -> pl.DataFrame:
    """Re-index a wide close frame onto Mon-Fri and forward-fill each column after its first
    price (holidays carry the last close; weekends of 7-day assets roll into Monday's return).
    Columns stay null before their first price, so nothing is held before it exists."""
    close = close.sort("ts")
    start, end = close["ts"].min(), close["ts"].max()
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ValueError("close frame needs a datetime ts column")
    days = pl.DataFrame({"ts": pl.datetime_range(start, end, "1d", time_zone="UTC", eager=True)})
    days = days.with_columns(pl.col("ts").dt.cast_time_unit("ms")).filter(
        pl.col("ts").dt.weekday() <= 5
    )
    syms = [c for c in close.columns if c != "ts"]
    out = days.join(close, on="ts", how="left").with_columns(
        [pl.col(s).forward_fill() for s in syms]
    )
    return out
