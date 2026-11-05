"""Download Binance USD-M perp 1h klines (monthly archives) for a few symbols into the lake."""

import io
import sys
import zipfile

import polars as pl

from mm.data.catalog import Catalog
from mm.data.http import PoliteClient

COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "tbv",
    "tbqv",
    "ignore",
]
syms = sys.argv[1:]
cat = Catalog()
with PoliteClient(min_interval_s=0.1) as c:
    for s in syms:
        frames = []
        y, m = 2019, 9
        while (y, m) <= (2026, 10):
            url = f"https://data.binance.vision/data/futures/um/monthly/klines/{s}/1h/{s}-1h-{y}-{m:02d}.zip"
            r = c.get(url)
            if r.status_code == 200:
                raw = zipfile.ZipFile(io.BytesIO(r.content)).read(
                    zipfile.ZipFile(io.BytesIO(r.content)).namelist()[0]
                )
                hdr = raw[:1].isalpha()
                df = pl.read_csv(
                    io.BytesIO(raw), has_header=hdr, new_columns=COLS, infer_schema_length=0
                )
                frames.append(
                    df.select(
                        pl.from_epoch(pl.col("open_time").cast(pl.Int64), time_unit="ms")
                        .dt.replace_time_zone("UTC")
                        .alias("ts"),
                        *[
                            pl.col(k).cast(pl.Float64)
                            for k in ("open", "high", "low", "close", "volume", "quote_volume")
                        ],
                    )
                )
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        df = pl.concat(frames).sort("ts").unique("ts", keep="last", maintain_order=True)
        p = cat.root / "bars_1h" / "binance_perp" / f"{s}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p)
        print(s, df.height, df["ts"].min(), df["ts"].max(), flush=True)
