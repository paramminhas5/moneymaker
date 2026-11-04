"""S4: India factor ETF rotation. Monthly. Low-vol + momentum ETFs, trend filter to liquid ETF.

NRI-compatible: delivery trades only, at most a handful of orders a month.
Costs use the capital-aware India delivery model, since DP charges dominate at Rs 10k.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.data.catalog import Catalog
from mm.research.backtest import wide
from mm.strategies import Spec, register

RISK = ["LOWVOLIETF", "MOM30IETF"]
BENCH = "NIFTYBEES"
SAFE = "LIQUIDBEES"
ALL = [*RISK, BENCH, SAFE]


def load_data() -> dict[str, Any]:
    cat = Catalog()
    bars = {s: cat.read("bars_1d", "nse", s) for s in ALL if cat.exists("bars_1d", "nse", s)}
    return {"close": wide(bars)}


def signal(close: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    syms = [c for c in close.columns if c != "ts"]
    ma = int(params["trend_ma"])
    lb = int(params["mom_lookback"])
    risk_on = (close[BENCH] > close[BENCH].rolling_mean(ma, min_samples=ma)).fill_null(False)
    # Rank risk ETFs by trailing momentum, hold top-k equal weight.
    mom = {s: (close[s] / close[s].shift(lb) - 1) for s in RISK if s in syms}
    month_end = (close["ts"].dt.month() != close["ts"].dt.month().shift(-1)).fill_null(True)
    out: dict[str, list[float]] = {s: [] for s in syms}
    cur = dict.fromkeys(syms, 0.0)
    k = int(params["top_k"])
    for i in range(close.height):
        if month_end[i]:
            new = dict.fromkeys(syms, 0.0)
            if risk_on[i]:
                scored = [(s, mom[s][i]) for s in mom if mom[s][i] is not None]
                scored = [x for x in scored if x[1] == x[1]]  # drop NaN
                for s, _ in sorted(scored, key=lambda x: -x[1])[:k]:
                    new[s] = 1.0 / k
                if not scored and BENCH in syms:
                    new[BENCH] = 1.0
            elif SAFE in syms:
                new[SAFE] = 1.0
            cur = new
        for s in syms:
            out[s].append(cur[s])
    return close.select("ts").with_columns([pl.Series(s, out[s]) for s in syms])


register(
    Spec(
        id="s4_india_etf",
        kind="directional",
        family="s4_v1",
        venue="upstox",
        periods_per_year=252,
        signal=signal,
        load_data=load_data,
        base_params={"trend_ma": 200, "mom_lookback": 126, "top_k": 1},
        sweep={"trend_ma": [100, 200], "mom_lookback": [63, 126, 252], "top_k": [1, 2]},
        walkforward=(504, 126),
        costs="model",
        capital=10_000.0,  # INR
        notes=[
            "Monthly rebalance; delivery only (NRI rules)",
            "MOM30IETF listed mid-2024, so the momentum leg has a short history",
        ],
    )
)
