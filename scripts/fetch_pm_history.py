"""Fetch a time-spread sample of resolved Polymarket markets and their last-7-day prices."""

from __future__ import annotations

import sys
from datetime import date, timedelta

import polars as pl

from mm.data.catalog import lake_root
from mm.data.http import PoliteClient
from mm.data.sources.polymarket_history import fetch_history, sample_closed_markets

START, END, STEP = (
    date.fromisoformat(sys.argv[1]),
    date.fromisoformat(sys.argv[2]),
    int(sys.argv[3]),
)
DAYS = [(START + timedelta(days=i)).isoformat() for i in range(0, (END - START).days + 1, STEP)]
out = lake_root() / "pm_history"
out.mkdir(parents=True, exist_ok=True)

with PoliteClient(min_interval_s=0.2) as c:
    mk = sample_closed_markets(c, days=DAYS)
    mk = mk.filter((pl.col("closed") - pl.col("start")).dt.total_hours().fill_null(999) >= 24)
    mk.write_parquet(out / "markets.parquet")
    print(f"markets: {mk.height}  {mk['closed'].min()} -> {mk['closed'].max()}", flush=True)
    rows = []
    for i, m in enumerate(mk.iter_rows(named=True)):
        for side, tok in ((0, m["token0"]), (1, m["token1"])):
            for t, p in fetch_history(c, tok, m["closed"]):
                rows.append((m["market_id"], side, t, p))
        if i % 200 == 0:
            print(f"  {i}/{mk.height}", flush=True)
            pl.DataFrame(
                rows, schema=["market_id", "side", "t", "price"], orient="row"
            ).write_parquet(out / "prices.parquet")
pl.DataFrame(rows, schema=["market_id", "side", "t", "price"], orient="row").write_parquet(
    out / "prices.parquet"
)
print("done", len(rows), flush=True)
