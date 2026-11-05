"""Core filtered hold: world + Nasdaq + India equity ETFs and BTC/ETH, each held only while
above its long moving average (with a hysteresis band, like trend v2). Monthly rebalancing.

Every asset has a fixed slot weight. When its filter is off, the slot sits in cash (no
re-allocation to the others), so one asset's signal never depends on another asset's close.
That keeps the different market closes (NSE ~10:00 UTC, US ~21:00 UTC, crypto 00:00 UTC) from
leaking into each other. Before an asset's first price its slot is also cash.

Calendar: Mon-Fri. Crypto weekend moves roll into Monday's return; holidays carry the last close.
Proxies (long free daily history from Yahoo): ACWI for world equity, QQQ for Nasdaq-100,
NIFTYBEES.NS for India, BTC-USD and ETH-USD. The live sleeve would use UCITS equivalents
(e.g. SSAC/CNDX on IBKR) with the same filter.

Weights and the filter family are pre-committed; only the MA length, band and how often the
filter is checked are swept. Buy-and-hold (filter off) is one of the logged variants.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.data.catalog import Catalog
from mm.data.clean import drop_reversal_spikes, weekday_calendar
from mm.research.backtest import wide
from mm.strategies import Spec, register
from mm.strategies.common import hold_between_rebalances, hysteresis_gate

SLOTS: dict[str, float] = {
    "ACWI": 0.40,  # world equity
    "QQQ": 0.25,  # Nasdaq-100
    "NIFTYBEES.NS": 0.15,  # Nifty 50
    "BTC-USD": 0.12,
    "ETH-USD": 0.08,
}
# One-way cost per trade, bps: commission + half-spread + slippage at small size (VERIFY).
COST_BPS: dict[str, float] = {
    "ACWI": 5.0,  # IBKR / UCITS ETF
    "QQQ": 3.0,
    "NIFTYBEES.NS": 25.0,  # Indian delivery: brokerage, stamp, STT, DP charge at small size
    "BTC-USD": 15.0,  # spot taker 10 bp + spread/slippage
    "ETH-USD": 15.0,
}


def load_data() -> dict[str, Any]:
    cat = Catalog()
    frames = {
        s: drop_reversal_spikes(cat.read("bars_1d", "yahoo", s), "adj_close")
        for s in SLOTS
        if cat.exists("bars_1d", "yahoo", s)
    }
    close = weekday_calendar(wide(frames, column="adj_close"))
    return {"close": close.filter(pl.col("ts") >= pl.datetime(2008, 4, 1, time_zone="UTC"))}


def signal(close: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """Rebalance to slot targets at each month end; with `check: daily` also on any day an
    asset's filter flips. Between rebalances weights drift with prices (no trading)."""
    syms = [c for c in close.columns if c != "ts"]
    ma, band = int(params["ma"]), float(params["band"])
    filt = bool(params["filter"])
    daily = str(params["check"]) == "daily"
    # Month end from the calendar (is the next weekday in a new month?), not from the next row,
    # so the decision at t never depends on data after t.
    step = pl.duration(days=pl.when(pl.col("ts").dt.weekday() == 5).then(3).otherwise(1))
    rebalance = close.select(
        ((pl.col("ts") + step).dt.month() != pl.col("ts").dt.month()).alias("r")
    )["r"].to_list()
    gates = {s: hysteresis_gate(close[s], ma, band) if filt else [1.0] * close.height for s in syms}
    target: dict[str, list[float]] = {}
    for s in syms:
        px = close[s].to_list()
        target[s] = [
            SLOTS.get(s, 0.0) * g if p is not None else 0.0
            for p, g in zip(px, gates[s], strict=True)
        ]
        if daily and filt:
            for i in range(1, close.height):
                if gates[s][i] != gates[s][i - 1]:
                    rebalance[i] = True
    tgt = close.select("ts").with_columns([pl.Series(s, target[s]) for s in syms])
    return hold_between_rebalances(close, tgt, rebalance)


register(
    Spec(
        id="core_hold",
        kind="directional",
        family="core_hold_v1",
        venue="ibkr",
        periods_per_year=261,
        signal=signal,
        load_data=load_data,
        base_params={"filter": True, "ma": 200, "band": 0.02, "check": "monthly"},
        sweep={
            "filter": [True],
            "ma": [150, 200],
            "band": [0.0, 0.02],
            "check": ["monthly", "daily"],
        },
        walkforward=(522, 261),
        cost_bps=COST_BPS,
        notes=[
            "Slots: ACWI 40%, QQQ 25%, NIFTYBEES 15%, BTC 12%, ETH 8%; cash when filter is off",
            "Cash earns 0% in the backtest (conservative: T-bill yield ignored)",
            "Buy-and-hold benchmark logged separately in the same family "
            "(scripts/run_core_hold.py)",
        ],
    )
)
