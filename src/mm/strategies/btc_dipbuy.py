"""BTC dip-buy: the best rule from the one-trade-a-day study (buy after a -3% day), re-tested as
a proper daily strategy with exits, costs and the gate.

Entry: at the close of a day whose close-to-close return is <= -threshold, go long 1x.
Exit: after `hold` days (a new qualifying dip resets the clock), or optionally only while BTC is
above its 200-day average (trend filter). Long-or-flat, no leverage.

Trials are logged to family `one_trade_day_v1`, the family the rule was mined from, and the 126
scenarios of that study are back-filled into the experiment log first, so the Deflated Sharpe
pays for the whole search that found this rule, not just this sweep.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.data.catalog import Catalog
from mm.research.backtest import wide
from mm.strategies import Spec, register

SYMBOL = "BTCUSDT"


def load_data() -> dict[str, Any]:
    cat = Catalog()
    return {"close": wide({SYMBOL: cat.read("bars_1d", "binance_spot", SYMBOL)})}


def signal(close: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    thr = float(params["threshold"])
    hold = int(params["hold"])
    use_trend = bool(params["trend_filter"])
    px = close[SYMBOL]
    ret = (px / px.shift(1) - 1).to_list()
    ma = px.rolling_mean(200, min_samples=200).to_list()
    p = px.to_list()
    w: list[float] = []
    left = 0
    for i in range(close.height):
        r = ret[i]
        if r is not None and r <= -thr and (not use_trend or (ma[i] is not None and p[i] > ma[i])):
            left = hold
        elif left > 0:
            left -= 1
        w.append(1.0 if left > 0 else 0.0)
    return close.select("ts").with_columns(pl.Series(SYMBOL, w))


register(
    Spec(
        id="btc_dipbuy",
        kind="directional",
        family="one_trade_day_v1",
        venue="binance",
        periods_per_year=365,
        signal=signal,
        load_data=load_data,
        base_params={"threshold": 0.03, "hold": 1, "trend_filter": False},
        sweep={"threshold": [0.03, 0.05], "hold": [1, 3, 5], "trend_filter": [False, True]},
        walkforward=(730, 182),
        cost_bps=12.0,
        notes=[
            "Rule mined from reports/research/one_trade_day_v1.md (best of 126 scenarios)",
            "Family one_trade_day_v1: the 126 prior scenarios are back-filled before the sweep",
            "Spot, 1x, 12 bp one-way (taker 10 bp + spread/slippage)",
        ],
    )
)
