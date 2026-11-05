"""Theme / sector momentum with a fast trend exit ("buy what is buzzing, sell at first downtrend").

Weekly: rank ETFs that are above their 200-day average by a blend of 3/6/12-month returns and
hold the top N equally. Daily: any holding that closes below its exit average is sold and the
slot sits in cash until the next weekly rebalance. Decisions use closes up to t and earn from t+1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass(frozen=True, slots=True)
class ThemeParams:
    top_n: int = 3
    exit_ma: int = 50  # daily exit when close < this MA; 0 = no daily exit (200d weekly only)
    trend_ma: int = 200
    lookbacks: tuple[int, ...] = (63, 126, 252)


def weights(close: pl.DataFrame, p: ThemeParams) -> pl.DataFrame:
    syms = [c for c in close.columns if c != "ts"]
    px = close.select(syms).to_numpy().astype(np.float64)
    t, n = px.shape

    def sma(k: int) -> np.ndarray:
        out = np.full_like(px, np.nan)
        csum = np.nancumsum(np.nan_to_num(px), axis=0)
        cnt = np.cumsum(~np.isnan(px), axis=0)
        for i in range(k, t):
            valid = (cnt[i] - cnt[i - k]) == k
            out[i] = np.where(valid, (csum[i] - csum[i - k]) / k, np.nan)
        return out

    trend = sma(p.trend_ma)
    exit_ma = sma(p.exit_ma) if p.exit_ma else None
    mom = np.nanmean(np.stack([px / np.roll(px, k, axis=0) - 1 for k in p.lookbacks]), axis=0)
    mom[: max(p.lookbacks)] = np.nan
    week = close["ts"].dt.week().to_numpy()
    rebalance = np.r_[week[1:] != week[:-1], True]  # last trading day of each week
    w = np.zeros((t, n))
    held = np.zeros(n, dtype=bool)
    for i in range(t):
        if rebalance[i]:
            ok = (px[i] > trend[i]) & np.isfinite(mom[i])
            score = np.where(ok, mom[i], -np.inf)
            order = np.argsort(-score)
            held = np.zeros(n, dtype=bool)
            for j in order[: p.top_n]:
                if np.isfinite(score[j]):
                    held[j] = True
        elif exit_ma is not None:
            held &= ~(px[i] < exit_ma[i])  # first downtrend: sell, stay out until rebalance
        if held.any():
            w[i, held] = 1.0 / p.top_n
    return close.select("ts").with_columns([pl.Series(s, w[:, j]) for j, s in enumerate(syms)])
