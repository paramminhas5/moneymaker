"""Fetch the first months of daily klines + funding for every Binance USD-M perp listing.

Uses the public archive (data.binance.vision), which keeps delisted symbols, so the sample is
free of survivorship bias. Writes bars_1d/binance_perp_new/<SYM>.parquet and
funding/binance_perp_new/<SYM>.parquet plus data/lake/listings.csv (symbol, first archive month).
Respects the active jurisdiction profile: skipped unless Binance is readable.
"""

import csv
import sys

from mm.config import load_settings
from mm.data.catalog import Catalog
from mm.data.http import PoliteClient
from mm.data.sources.binance import fetch_perp_window, list_perp_symbols, perp_archive_months

WINDOW_MONTHS = 3  # listing month + 2: covers entry delay + a 28-day hold
FIRST_ARCHIVE = (2020, 1)  # archive start: symbols first seen here may be older listings

settings = load_settings()
perm = settings.active_jurisdiction.venues.get("binance")
if perm is None or not perm.read:
    sys.exit("binance not readable under the active jurisdiction profile")

cat = Catalog()
listing_path = cat.root / "listings.csv"
listing_path.parent.mkdir(parents=True, exist_ok=True)
done: dict[str, str] = {}
if listing_path.exists():
    with listing_path.open() as fh:
        done = {r["symbol"]: r["first_month"] for r in csv.DictReader(fh)}

with PoliteClient(min_interval_s=0.15) as c:
    syms = [s for s in list_perp_symbols(c) if s.endswith("USDT") and "_" not in s]
    print(f"{len(syms)} USDT perps in archive", flush=True)
    for i, s in enumerate(syms):
        if s in done:
            continue
        months = perp_archive_months(c, s)
        if not months:
            done[s] = ""
            continue
        first = months[0]
        done[s] = f"{first[0]}-{first[1]:02d}"
        if first > FIRST_ARCHIVE:
            bars, fund = fetch_perp_window(c, s, months[:WINDOW_MONTHS])
            if not bars.is_empty():
                cat.write("bars_1d", "binance_perp_new", s, bars, merge=False)
            if not fund.is_empty():
                cat.write("funding", "binance_perp_new", s, fund, merge=False)
        if i % 25 == 0:
            print(f"{i}/{len(syms)} {s} {done[s]}", flush=True)
            with listing_path.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["symbol", "first_month"])
                w.writerows(sorted(done.items()))

with listing_path.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["symbol", "first_month"])
    w.writerows(sorted(done.items()))
print("done", len(done))
