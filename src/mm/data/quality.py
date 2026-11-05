"""Data-quality checks. Errors block a dataset from use; warnings are reported for review."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import polars as pl


@dataclass(slots=True)
class QualityReport:
    name: str
    rows: int
    errors: list[str] = field(default_factory=list[str])
    warnings: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.errors


def check_bars(
    df: pl.DataFrame,
    name: str,
    *,
    expected_step: timedelta = timedelta(days=1),
    max_gap_steps: int = 5,
    outlier_abs_return: float = 0.6,
) -> QualityReport:
    rep = QualityReport(name=name, rows=df.height)
    if df.is_empty():
        rep.errors.append("no rows")
        return rep
    if not df["ts"].is_sorted():
        rep.errors.append("timestamps not sorted")
    if df["ts"].is_duplicated().any():
        rep.errors.append("duplicate timestamps")
    price_cols = ["open", "high", "low", "close"]
    nulls = df.select(pl.col(price_cols).null_count()).row(0)
    if any(nulls):
        rep.errors.append(f"null prices: {dict(zip(price_cols, nulls, strict=True))}")
    if df.filter(pl.any_horizontal(pl.col(price_cols) <= 0)).height:
        rep.errors.append("non-positive prices")
    bad_ohlc = df.filter(
        (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.col("low"))
    ).height
    if bad_ohlc:
        rep.errors.append(f"{bad_ohlc} bars violate low <= open,close <= high")
    if (df["volume"] < 0).any():
        rep.errors.append("negative volume")

    gaps = df.select((pl.col("ts").diff() / expected_step).alias("steps")).filter(
        pl.col("steps") > max_gap_steps
    )
    if gaps.height:
        rep.warnings.append(f"{gaps.height} gaps longer than {max_gap_steps} bars")
    rets = df.select((pl.col("close") / pl.col("close").shift(1) - 1).abs().alias("r"))
    outliers = rets.filter(pl.col("r") > outlier_abs_return).height
    if outliers:
        rep.warnings.append(
            f"{outliers} one-bar moves above {outlier_abs_return:.0%} "
            "(check for splits, delistings or bad ticks)"
        )
    zero_vol = df.filter(pl.col("volume") == 0).height
    if zero_vol > df.height * 0.05:
        rep.warnings.append(f"{zero_vol} zero-volume bars")
    return rep


def check_funding(df: pl.DataFrame, name: str, *, max_abs_rate: float = 0.05) -> QualityReport:
    rep = QualityReport(name=name, rows=df.height)
    if df.is_empty():
        rep.errors.append("no rows")
        return rep
    if not df["ts"].is_sorted():
        rep.errors.append("timestamps not sorted")
    if df["ts"].is_duplicated().any():
        rep.errors.append("duplicate timestamps")
    if df["rate"].null_count():
        rep.errors.append("null funding rates")
    extreme = df.filter(pl.col("rate").abs() > max_abs_rate).height
    if extreme:
        rep.warnings.append(f"{extreme} funding prints above {max_abs_rate:.0%} per interval")
    if (df["interval_hours"] <= 0).any():
        rep.errors.append("non-positive funding interval")
    return rep
