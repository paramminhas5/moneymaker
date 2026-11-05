"""Fetch daily adjusted prices for sector, theme and commodity ETFs into the lake (yahoo)."""

from mm.data.catalog import Catalog
from mm.data.http import PoliteClient
from mm.data.sources.yahoo import fetch_daily

SECTORS = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"]  # SPDRs, 1998+
THEMES = [
    "SMH",
    "SOXX",
    "IGV",
    "SKYY",
    "CIBR",
    "BOTZ",
    "FDN",
    "OIH",
    "XOP",
    "GLD",
    "SLV",
    "GDX",
    "COPX",
    "XME",
    "URA",
    "LIT",
    "TAN",
    "ICLN",
    "ITA",
    "XBI",
    "IBB",
    "KRE",
    "XHB",
    "ITB",
    "IYT",
    "JETS",
    "KWEB",
    "INDA",
    "EWZ",
    "EWJ",
    "EWT",
    "DBA",
    "PAVE",
    "XRT",
    "VNQ",
]
BENCH = ["SPY", "QQQ", "ACWI"]
cat = Catalog()
with PoliteClient(min_interval_s=1.0) as c:
    for s in SECTORS + THEMES + BENCH:
        df = fetch_daily(c, s)
        if df.is_empty():
            print("empty", s)
            continue
        p = cat.root / "bars_1d" / "yahoo" / f"{s}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p)
        print(
            f"{s:5} {df.height:5} {df['ts'].min():%Y-%m-%d} -> {df['ts'].max():%Y-%m-%d}",
            flush=True,
        )
