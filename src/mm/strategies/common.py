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


def atr(bars: dict[str, pl.DataFrame], index: pl.DataFrame, span: int) -> pl.DataFrame:
    """EWM average true range per symbol, aligned to `index` ts. Uses bars up to and including t."""
    out = index.select("ts")
    for s, df in bars.items():
        tr = df.sort("ts").select(
            "ts",
            pl.max_horizontal(
                pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("close").shift(1)).abs(),
                (pl.col("low") - pl.col("close").shift(1)).abs(),
            )
            .ewm_mean(span=span, min_samples=span // 2)
            .alias(s),
        )
        out = out.join(tr, on="ts", how="left")
    return out


def hysteresis_gate(price: pl.Series, ma_len: int, band: float) -> list[float]:
    """1.0 when price is above its MA by more than `band`, 0.0 when below by more than `band`,
    otherwise keep the previous state. Causal. Starts off until the MA exists."""
    ma = price.rolling_mean(ma_len, min_samples=ma_len).to_list()
    px = price.to_list()
    state, out = 0.0, []
    for p, m in zip(px, ma, strict=True):
        if p is not None and m is not None:
            if p > m * (1 + band):
                state = 1.0
            elif p < m * (1 - band):
                state = 0.0
        out.append(state)
    return out


def trailing_stop(
    target: pl.DataFrame, close: pl.DataFrame, atr_frame: pl.DataFrame, mult: float
) -> pl.DataFrame:
    """Chandelier exit on long positions: once in, stop = highest close since entry - mult * ATR.
    After a stop the symbol stays flat until its target goes to zero (signal resets) and
    then turns positive again. Causal: uses close_t and ATR_t to decide the weight held after t."""
    syms = [c for c in target.columns if c != "ts"]
    out = target.select("ts")
    for s in syms:
        w = target[s].fill_null(0.0).to_list()
        px = close[s].to_list()
        a = atr_frame[s].to_list() if s in atr_frame.columns else [None] * len(w)
        peak: float | None = None
        stopped = False
        held: list[float] = []
        for wt, p, at in zip(w, px, a, strict=True):
            if wt <= 0:
                stopped, peak = False, None
                held.append(0.0)
                continue
            if stopped or p is None:
                held.append(0.0 if stopped else wt)
                continue
            peak = p if peak is None else max(peak, p)
            if at is not None and p < peak - mult * at:
                stopped, peak = True, None
                held.append(0.0)
            else:
                held.append(wt)
        out = out.with_columns(pl.Series(s, held))
    return out


def hold_between_rebalances(
    close: pl.DataFrame, target: pl.DataFrame, rebalance: list[bool]
) -> pl.DataFrame:
    """Weights that move to `target` only on rebalance days and drift with prices in between
    (cash, the unallocated remainder, earns 0). Matches the backtester's drift formula, so
    non-rebalance days trade nothing. Causal: day t uses closes up to t."""
    syms = [c for c in close.columns if c != "ts"]
    px = [close[s].to_list() for s in syms]
    tg = [target[s].fill_null(0.0).to_list() for s in syms]
    n = close.height
    cur = [0.0] * len(syms)
    out: list[list[float]] = [[] for _ in syms]
    for i in range(n):
        if i > 0:
            rets = []
            for j in range(len(syms)):
                a, b = px[j][i - 1], px[j][i]
                rets.append(b / a - 1 if a is not None and b is not None and a > 0 else 0.0)
            port = sum(w * r for w, r in zip(cur, rets, strict=True))
            if 1 + port > 0:
                cur = [w * (1 + r) / (1 + port) for w, r in zip(cur, rets, strict=True)]
        if rebalance[i]:
            cur = [tg[j][i] for j in range(len(syms))]
        for j in range(len(syms)):
            out[j].append(cur[j])
    return close.select("ts").with_columns([pl.Series(s, out[j]) for j, s in enumerate(syms)])
