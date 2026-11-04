"""Shared signal building blocks. All causal: rolling windows ending at t, shifted where needed."""

from __future__ import annotations

import polars as pl


def ewm_vol(close: pl.DataFrame, span: int, periods_per_year: float) -> pl.DataFrame:
    """Annualised EWM volatility of daily log returns per column."""
    syms = [c for c in close.columns if c != "ts"]
    return close.select(
        "ts",
        *[
            (pl.col(s) / pl.col(s).shift(1))
            .log()
            .ewm_std(span=span, min_samples=span // 2)
            .mul(periods_per_year**0.5)
            .alias(s)
            for s in syms
        ],
    )


def donchian_score(close: pl.DataFrame, lookbacks: list[int]) -> pl.DataFrame:
    """Share of lookbacks where close is at/above its trailing N-day high (long-only, 0..1).

    Uses the high over the N bars ending at t-1 so the breakout day itself counts.
    """
    syms = [c for c in close.columns if c != "ts"]
    exprs = []
    for s in syms:
        votes = [
            (pl.col(s) >= pl.col(s).shift(1).rolling_max(n, min_samples=n)).cast(pl.Float64)
            for n in lookbacks
        ]
        exprs.append(pl.sum_horizontal(votes).truediv(len(lookbacks)).alias(s))
    return close.select("ts", *exprs)


def ma_cross_score(close: pl.DataFrame, pairs: list[tuple[int, int]]) -> pl.DataFrame:
    syms = [c for c in close.columns if c != "ts"]
    exprs = []
    for s in syms:
        votes = [
            (
                pl.col(s).rolling_mean(f, min_samples=f)
                > pl.col(s).rolling_mean(sl, min_samples=sl)
            ).cast(pl.Float64)
            for f, sl in pairs
        ]
        exprs.append(pl.sum_horizontal(votes).truediv(len(pairs)).alias(s))
    return close.select("ts", *exprs)


def band_rebalance(target: pl.DataFrame, band: float) -> pl.DataFrame:
    """Only move to a new target when it differs from the held weight by more than `band`
    (relative to the larger of the two). Cuts turnover. Causal: depends on past targets only."""
    syms = [c for c in target.columns if c != "ts"]
    out = target.select("ts")
    for s in syms:
        vals = target[s].fill_null(0.0).to_list()
        held: list[float] = []
        cur = 0.0
        for v in vals:
            ref = max(abs(v), abs(cur), 1e-12)
            if abs(v - cur) / ref > band or (v == 0.0 and cur != 0.0):
                cur = v
            held.append(cur)
        out = out.with_columns(pl.Series(s, held))
    return out


def vol_target_weights(
    score: pl.DataFrame, vol: pl.DataFrame, target_vol: float, max_gross: float = 1.0
) -> pl.DataFrame:
    """Weight_i = score_i * (target_vol / vol_i) / n_active, capped so gross <= max_gross."""
    syms = [c for c in score.columns if c != "ts"]
    raw = score.select(
        "ts",
        *[(pl.col(s) * (target_vol / vol[s])).fill_nan(0.0).fill_null(0.0).alias(s) for s in syms],
    )
    active = raw.select(pl.sum_horizontal([(pl.col(s) > 0).cast(pl.Int32) for s in syms]))
    n_active = active.to_series().clip(lower_bound=1)
    scaled = raw.with_columns([(pl.col(s) / n_active).alias(s) for s in syms])
    gross = scaled.select(pl.sum_horizontal([pl.col(s).abs() for s in syms])).to_series()
    scale = (max_gross / gross.clip(lower_bound=max_gross)).fill_nan(1.0)
    return scaled.with_columns([(pl.col(s) * scale).alias(s) for s in syms])
