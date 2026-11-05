"""Fetch daily adjusted prices for the core filtered-hold sleeve into the lake (yahoo)."""

from mm.data.catalog import Catalog
from mm.data.http import PoliteClient
from mm.data.sources.yahoo import fetch_daily

SYMBOLS = ["ACWI", "VT", "QQQ", "SPY", "NIFTYBEES.NS", "BTC-USD", "ETH-USD"]
cat = Catalog()
with PoliteClient(min_interval_s=2.0) as c:
    for s in SYMBOLS:
        df = fetch_daily(c, s)
        if df.is_empty():
            print("empty", s)
            continue
        p = cat.root / "bars_1d" / "yahoo" / f"{s}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p)
        print(
            f"{s:13} {df.height:5} {df['ts'].min():%Y-%m-%d} -> {df['ts'].max():%Y-%m-%d}",
            flush=True,
        )
