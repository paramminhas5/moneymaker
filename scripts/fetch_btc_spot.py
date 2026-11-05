"""Fetch BTCUSDT spot daily bars (Binance public market data) for the dip-buy strategy."""

from datetime import date

from mm.data.catalog import Catalog
from mm.data.http import PoliteClient
from mm.data.sources.binance import fetch_spot_daily
from mm.data.sync import _ms

cat = Catalog()
with PoliteClient() as c:
    df = fetch_spot_daily(c, "BTCUSDT", _ms(date(2017, 8, 1)))
cat.write("bars_1d", "binance_spot", "BTCUSDT", df)
print(df.height, df["ts"].min(), df["ts"].max())
