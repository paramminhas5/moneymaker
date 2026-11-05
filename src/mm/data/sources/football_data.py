"""football-data.co.uk: free historical results and bookmaker odds for European leagues.

One CSV per league per season. Pinnacle closing odds (PSCH/PSCD/PSCA) exist from 2012/13 and
are the sharpest public benchmark for a match-outcome model.
"""

from __future__ import annotations

import io

import polars as pl

from mm.data.http import PoliteClient

URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
LEAGUES = {
    "E0": "Premier League",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "SP1": "La Liga",
    "F1": "Ligue 1",
}
KEEP = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
        "PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA", "AvgH", "AvgD", "AvgA",
        "AvgCH", "AvgCD", "AvgCA"]  # fmt: skip


def season_code(start_year: int) -> str:
    """2023 -> '2324'."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def parse_csv(raw: bytes, season_start: int, div: str) -> pl.DataFrame:
    """Normalise one season file: typed columns, parsed dates, played matches only."""
    text = raw.decode("latin-1").removeprefix("\ufeff").removeprefix("ï»¿")
    df = pl.read_csv(io.StringIO(text), infer_schema_length=0, truncate_ragged_lines=True)
    df = df.rename({c: c.strip() for c in df.columns}).with_columns(pl.lit(div).alias("Div"))
    cols = [c for c in KEEP if c in df.columns]
    df = df.select(cols).filter(pl.col("HomeTeam").is_not_null() & (pl.col("HomeTeam") != ""))
    for c in KEEP:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(c))
    date = (
        pl.when(pl.col("Date").str.len_chars() == 10)
        .then(pl.col("Date").str.strptime(pl.Date, "%d/%m/%Y", strict=False))
        .otherwise(pl.col("Date").str.strptime(pl.Date, "%d/%m/%y", strict=False))
    )
    num = [c for c in KEEP if c not in ("Div", "Date", "HomeTeam", "AwayTeam", "FTR")]
    return (
        df.with_columns(
            date.alias("date"),
            pl.lit(season_start).alias("season"),
            *[pl.col(c).cast(pl.Float64, strict=False) for c in num],
        )
        .drop("Date")
        .rename(
            {
                "Div": "div",
                "HomeTeam": "home",
                "AwayTeam": "away",
                "FTHG": "hg",
                "FTAG": "ag",
                "FTR": "result",
            }
        )
        .drop_nulls(["date", "hg", "ag"])
        .sort("date")
    )


def fetch_season(client: PoliteClient, div: str, season_start: int) -> pl.DataFrame:
    resp = client.get(URL.format(season=season_code(season_start), div=div))
    if resp.status_code == 404:
        return pl.DataFrame()
    resp.raise_for_status()
    return parse_csv(resp.content, season_start, div)
