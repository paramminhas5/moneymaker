"""S1: crypto trend ensemble. Long-or-flat, vol-targeted, point-in-time top-N universe.

Signal at close t uses only closes <= t. Universe membership for day t uses volume < t.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.data.catalog import Catalog
from mm.data.universe import top_n_by_liquidity
from mm.research.backtest import wide
from mm.strategies import Spec, register
from mm.strategies.common import (
    band_rebalance,
    donchian_score,
    ewm_vol,
    ma_cross_score,
    vol_target_weights,
)

CANDIDATES = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "TRXUSDT",
    "DOTUSDT", "MATICUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT", "UNIUSDT", "ATOMUSDT",
    "XLMUSDT", "ETCUSDT", "FILUSDT", "NEARUSDT", "ICPUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "SUIUSDT", "AAVEUSDT", "EOSUSDT", "ALGOUSDT", "VETUSDT", "THETAUSDT", "SHIBUSDT", "PEPEUSDT",
    "LUNAUSDT", "FTTUSDT", "XMRUSDT", "INJUSDT", "TIAUSDT", "SEIUSDT", "RUNEUSDT", "POLUSDT",
]  # fmt: skip


def load_data() -> dict[str, Any]:
    cat = Catalog()
    bars = {
        s: cat.read("bars_1d", "binance_spot", s)
        for s in CANDIDATES
        if cat.exists("bars_1d", "binance_spot", s)
    }
    return {"close": wide(bars), "bars": bars}


def signal(
    close: pl.DataFrame, params: dict[str, Any], *, bars: dict[str, pl.DataFrame]
) -> pl.DataFrame:
    syms = [c for c in close.columns if c != "ts"]
    uni = top_n_by_liquidity(bars, n=int(params["top_n"]), lookback_days=90, min_history_days=90)
    member = (
        uni.with_columns(pl.lit(1.0).alias("m"))
        .pivot(on="symbol", index="ts", values="m")
        .pipe(lambda d: close.select("ts").join(d, on="ts", how="left"))
    )
    for s in syms:
        if s not in member.columns:
            member = member.with_columns(pl.lit(0.0).alias(s))
    member = member.select("ts", *[pl.col(s).fill_null(0.0) for s in syms])

    don = donchian_score(close, list(params["donchian"]))
    mac = ma_cross_score(close, [tuple(p) for p in params["ma_pairs"]])
    w_don = float(params["donchian_weight"])
    thr = float(params["threshold"])
    exprs = []
    for s in syms:
        blended = (w_don * don[s] + (1 - w_don) * mac[s]) * member[s]
        exprs.append(pl.when(pl.lit(blended) >= thr).then(pl.lit(blended)).otherwise(0.0).alias(s))
    score = close.select("ts", *exprs)
    vol = ewm_vol(close, span=int(params["vol_span"]), periods_per_year=365)
    target = vol_target_weights(score, vol, float(params["target_vol"]), max_gross=1.0)
    return band_rebalance(target, float(params["band"]))


register(
    Spec(
        id="s1_crypto_trend",
        kind="directional",
        family="s1_v1",
        venue="binance",
        periods_per_year=365,
        signal=signal,
        load_data=load_data,
        base_params={
            "top_n": 10,
            "donchian": [20, 55, 100],
            "ma_pairs": [[10, 50], [20, 100], [50, 200]],
            "donchian_weight": 0.5,
            "threshold": 0.5,
            "vol_span": 30,
            "target_vol": 0.30,
            "band": 0.25,
        },
        sweep={
            "top_n": [5, 10],
            "threshold": [0.34, 0.5, 0.67],
            "target_vol": [0.20, 0.30, 0.40],
            "band": [0.15, 0.25, 0.40],
        },
        walkforward=(730, 182),
        cost_bps=12.0,  # 10bp taker + spread/slippage on Binance spot base tier
        notes=[
            "Universe is point-in-time top-N by trailing 90d median quote volume",
            "Includes delisted names (LUNA, FTT) in candidates: no survivorship bias",
        ],
    )
)
