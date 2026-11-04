"""Upstox documented public historical-candle API for NSE instruments (no login needed)."""

from __future__ import annotations

import gzip
import json
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import polars as pl

from mm.data.http import PoliteClient

INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
CANDLES = "https://api.upstox.com/v2/historical-candle/{key}/day/{to}/{frm}"


def instrument_keys(client: PoliteClient, symbols: list[str]) -> dict[str, str]:
    """Map NSE trading symbols to Upstox instrument keys (e.g. NSE_EQ|INF204KB14I2)."""
    resp = client.get(INSTRUMENTS)
    resp.raise_for_status()
    rows: list[dict[str, Any]] = json.loads(gzip.decompress(resp.content))
    wanted = set(symbols)
    out: dict[str, str] = {}
    for r in rows:
        sym = r.get("trading_symbol")
        if sym in wanted and r.get("segment") == "NSE_EQ":
            out[str(sym)] = str(r["instrument_key"])
    return out


def _candles_to_frame(candles: list[list[Any]]) -> pl.DataFrame:
    if not candles:
        return pl.DataFrame()
    df = pl.DataFrame(
        candles, schema=["ts", "open", "high", "low", "close", "volume", "oi"], orient="row"
    )
    return df.select(
        pl.col("ts")
        .str.to_datetime("%Y-%m-%dT%H:%M:%S%z")
        .dt.convert_time_zone("UTC")
        .dt.cast_time_unit("ms"),
        *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")],
    ).with_columns((pl.col("close") * pl.col("volume")).alias("quote_volume"))


def fetch_daily(
    client: PoliteClient, instrument_key: str, start: date, end: date | None = None
) -> pl.DataFrame:
    """Walk backwards in one-year windows until the API returns nothing or `start` is reached."""
    end = end or date.today()
    frames: list[pl.DataFrame] = []
    to = end
    while to >= start:
        frm = max(start, to - timedelta(days=365))
        url = CANDLES.format(
            key=quote(instrument_key, safe=""), to=to.isoformat(), frm=frm.isoformat()
        )
        resp = client.get(url)
        if resp.status_code == 400:
            break
        resp.raise_for_status()
        candles: list[list[Any]] = resp.json().get("data", {}).get("candles", [])
        if not candles:
            break
        frames.append(_candles_to_frame(candles))
        to = frm - timedelta(days=1)
    return pl.concat(frames) if frames else pl.DataFrame()
