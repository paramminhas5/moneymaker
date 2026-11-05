"""Fetch football-data.co.uk seasons 2012/13 onward for the top five leagues into the lake."""

import polars as pl

from mm.data.catalog import Catalog
from mm.data.http import PoliteClient
from mm.data.sources.football_data import LEAGUES, fetch_season

cat = Catalog()
frames = []
with PoliteClient(min_interval_s=1.0) as c:
    for div in LEAGUES:
        for start in range(2012, 2027):
            df = fetch_season(c, div, start)
            print(div, start, df.height, flush=True)
            if not df.is_empty():
                frames.append(df)
out = pl.concat(frames, how="diagonal_relaxed").sort("date", "div")
path = cat.root / "football" / "matches.parquet"
path.parent.mkdir(parents=True, exist_ok=True)
out.write_parquet(path)
print("matches", out.height, out["date"].min(), out["date"].max())
