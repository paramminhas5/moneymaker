"""Listing fade: short newly listed USD-M perps for their first weeks, at most 3 names at once.

Rationale (doc 12): most 2025 token launches traded below their listing valuation within weeks;
the sleeve is ring-fenced and capped because squeezes on new coins are violent.

Universe: every Binance USD-M USDT perp whose first monthly archive is after the archive start
(Jan 2020), delisted names included, so there is no survivorship bias. Listing day = first
daily bar, which is known on that day (point in time).

Rules: on day `delay` after listing, at the close, short 1/max_names of equity if fewer than
`max_names` positions are open (first come, first served). Cover after `hold` days, or at the
close of any day the price is `stop` above the entry close (then stay out of that coin).
A coin that stops printing (delisted) is treated as covered at its last close.
Costs: 20 bp one-way (new-listing spreads are wide) plus actual funding paid or received.
Perps need no borrow; shorting spot instead would need borrow that new coins rarely have.
"""

from __future__ import annotations

import csv
from typing import Any

import numpy as np
import polars as pl

from mm.data.catalog import Catalog
from mm.research.backtest import wide
from mm.strategies import Spec, register

ARCHIVE_START = "2020-01"


def listed_symbols(cat: Catalog) -> list[str]:
    path = cat.root / "listings.csv"
    if not path.exists():
        return []
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    return sorted(
        r["symbol"]
        for r in rows
        if r["first_month"] > ARCHIVE_START
        and cat.exists("bars_1d", "binance_perp_new", r["symbol"])
    )


def load_data() -> dict[str, Any]:
    cat = Catalog()
    syms = listed_symbols(cat)
    bars = {s: cat.read("bars_1d", "binance_perp_new", s) for s in syms}
    bars = {s: b for s, b in bars.items() if b.height > 0}
    close = wide(bars)
    fund: dict[str, pl.DataFrame] = {}
    for s in bars:
        if cat.exists("funding", "binance_perp_new", s):
            f = cat.read("funding", "binance_perp_new", s)
            fund[s] = (
                f.with_columns(pl.col("ts").dt.truncate("1d"))
                .group_by("ts")
                .agg(pl.col("rate").sum())
                .sort("ts")
            )
    fw = close.select("ts")
    for s in [c for c in close.columns if c != "ts"]:
        if s in fund:
            fw = fw.join(fund[s].rename({"rate": s}), on="ts", how="left")
        else:
            fw = fw.with_columns(pl.lit(0.0).alias(s))
    fw = fw.with_columns([pl.col(c).fill_null(0.0) for c in fw.columns if c != "ts"])
    return {"close": close, "funding": fw}


def signal(close: pl.DataFrame, params: dict[str, Any], **_: Any) -> pl.DataFrame:
    delay, hold = int(params["delay"]), int(params["hold"])
    stop, k = float(params["stop"]), int(params["max_names"])
    syms = [c for c in close.columns if c != "ts"]
    px = close.select(syms).to_numpy().astype(np.float64)
    t, n = px.shape
    has = np.isfinite(px)
    first = np.where(has.any(axis=0), has.argmax(axis=0), t + 10**6)
    entries_on: dict[int, list[int]] = {}
    for j in range(n):
        entries_on.setdefault(int(first[j]) + delay, []).append(j)
    w = np.zeros((t, n))
    active: dict[int, tuple[int, float]] = {}  # col -> (entry row, entry price)
    for i in range(t):
        for j in list(active):
            e_row, e_px = active[j]
            p = px[i, j]
            if not np.isfinite(p) or i >= e_row + hold or p >= e_px * (1 + stop):
                del active[j]
        for j in entries_on.get(i, []):
            if len(active) < k and np.isfinite(px[i, j]):
                active[j] = (i, float(px[i, j]))
        for j in active:
            w[i, j] = -1.0 / k
    return close.select("ts").with_columns([pl.Series(s, w[:, j]) for j, s in enumerate(syms)])


register(
    Spec(
        id="listing_fade",
        kind="directional",
        family="listing_fade_v1",
        venue="binance_perp",
        periods_per_year=365,
        signal=signal,
        load_data=load_data,
        base_params={"delay": 1, "hold": 28, "stop": 0.5, "max_names": 3},
        sweep={"delay": [1, 3], "hold": [14, 28], "stop": [0.5, 10.0], "max_names": [3]},
        walkforward=(730, 182),
        cost_bps=20.0,
        notes=[
            "Binance USD-M archive incl. delisted symbols; live venue would be Hyperliquid perps",
            "Funding charged/received daily; stop 10.0 means effectively no stop",
            "Max 3 names, 1/3 each: gross 1x, never levered",
        ],
    )
)
