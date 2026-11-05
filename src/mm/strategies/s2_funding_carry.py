"""S2: delta-neutral funding carry. Long spot, short perp, equal notional, on BTC/ETH.

Enter when trailing funding (annualised) exceeds `enter`, exit below `exit`, minimum hold.
The return stream is funding received minus costs; price exposure nets to ~0 (basis drift is
the residual and is included via spot-vs-perp close difference).
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.data.catalog import Catalog
from mm.research.backtest import wide
from mm.strategies import Spec, register
from mm.strategies.common import band_rebalance

COINS = ["BTCUSDT", "ETHUSDT"]


def load_data() -> dict[str, Any]:
    cat = Catalog()
    spot = {c: cat.read("bars_1d", "binance_spot", c) for c in COINS}
    perp = {c: cat.read("bars_1d", "binance_perp", c) for c in COINS}
    funding = {c: cat.read("funding", "binance_perp", c) for c in COINS}
    daily_fund = {
        c: f.with_columns(pl.col("ts").dt.truncate("1d"))
        .group_by("ts")
        .agg(pl.col("rate").sum())
        .sort("ts")
        for c, f in funding.items()
    }
    # Wide frames: spot closes (what we hold long), perp closes (short), daily funding sums.
    spot_w = wide(spot)
    perp_w = wide(perp).rename({c: f"{c}_PERP" for c in COINS})
    fund_w = wide(daily_fund, column="rate")
    close = spot_w.join(perp_w, on="ts", how="inner").sort("ts")
    fund_w = (
        close.select("ts")
        .join(fund_w, on="ts", how="left")
        .with_columns([pl.col(c).fill_null(0.0).alias(f"{c}_PERP") for c in COINS])
        .select("ts", *[f"{c}_PERP" for c in COINS])
        .with_columns([pl.lit(0.0).alias(c) for c in COINS])
        .select("ts", *COINS, *[f"{c}_PERP" for c in COINS])
    )
    return {"close": close, "funding": fund_w}


def signal(close: pl.DataFrame, params: dict[str, Any], *, funding: pl.DataFrame) -> pl.DataFrame:
    enter = float(params["enter_apr"]) / 365
    exit_ = float(params["exit_apr"]) / 365
    lb = int(params["lookback"])
    min_hold = int(params["min_hold"])
    gross = float(params["gross"]) / len(COINS)
    out = close.select("ts")
    for c in COINS:
        trailing = funding[f"{c}_PERP"].rolling_mean(lb, min_samples=lb).fill_null(0.0).to_list()
        on = 0.0
        held = 0
        flags: list[float] = []
        for f in trailing:
            if on == 0.0 and f >= enter:
                on, held = 1.0, 0
            elif on == 1.0:
                held += 1
                if held >= min_hold and f < exit_:
                    on = 0.0
            flags.append(on)
        s = pl.Series(flags)
        out = out.with_columns((s * gross).alias(c), (s * -gross).alias(f"{c}_PERP"))
    return band_rebalance(out.select("ts", *[c for c in close.columns if c != "ts"]), 0.0)


register(
    Spec(
        id="s2_funding_carry",
        kind="carry",
        family="s2_v1",
        venue="binance_perp",
        periods_per_year=365,
        signal=signal,
        load_data=load_data,
        base_params={
            "enter_apr": 0.15,
            "exit_apr": 0.05,
            "lookback": 3,
            "min_hold": 7,
            "gross": 1.0,
        },
        sweep={
            "enter_apr": [0.10, 0.15, 0.25],
            "exit_apr": [0.0, 0.05],
            "lookback": [3, 7],
            "min_hold": [7, 14],
        },
        walkforward=(730, 182),
        cost_bps=9.0,  # both legs: spot 10bp + perp 5bp taker, plus spread, averaged per leg
        notes=[
            "Margin buffer, ADL and depeg monitors are live-only concerns (phase 5)",
            "Backtest assumes perp short is fully collateralised (1x), no liquidation risk",
        ],
    )
)
