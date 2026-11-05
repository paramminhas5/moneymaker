"""Point-in-time universes. Membership on day D uses only data strictly before D (no lookahead)."""

from __future__ import annotations

import polars as pl


def liquidity_panel(bars: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Long frame: ts, symbol, quote_volume (falls back to close*volume)."""
    frames = [
        df.select(
            "ts",
            pl.lit(sym).alias("symbol"),
            pl.coalesce("quote_volume", pl.col("close") * pl.col("volume")).alias("qv"),
        )
        for sym, df in bars.items()
    ]
    return pl.concat(frames).sort("symbol", "ts")


def top_n_by_liquidity(
    bars: dict[str, pl.DataFrame],
    n: int,
    *,
    lookback_days: int = 90,
    min_history_days: int = 90,
) -> pl.DataFrame:
    """For each date, the n symbols with the highest trailing median quote volume.

    The trailing window is shifted by one bar, so day D's ranking only uses days < D.
    A symbol needs `min_history_days` of history before it can enter.
    """
    panel = liquidity_panel(bars).with_columns(
        pl.col("qv")
        .shift(1)
        .rolling_median(window_size=lookback_days, min_samples=min_history_days)
        .over("symbol")
        .alias("liq")
    )
    ranked = panel.drop_nulls("liq").with_columns(
        pl.col("liq").rank(method="ordinal", descending=True).over("ts").alias("rank")
    )
    return (
        ranked.filter(pl.col("rank") <= n).select("ts", "symbol", "rank", "liq").sort("ts", "rank")
    )
