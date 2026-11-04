"""Hyperliquid official info API: daily candles and hourly funding history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import polars as pl

from mm.data.http import PoliteClient

INFO = "https://api.hyperliquid.xyz/info"
DAY_MS = 86_400_000


def fetch_daily(client: PoliteClient, coin: str, start_ms: int) -> pl.DataFrame:
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    frames: list[pl.DataFrame] = []
    cursor = start_ms
    while cursor < now_ms:
        resp = client.post(
            INFO,
            json={
                "type": "candleSnapshot",
                "req": {"coin": coin, "interval": "1d", "startTime": cursor, "endTime": now_ms},
            },
        )
        resp.raise_for_status()
        rows: list[dict[str, Any]] = [r for r in resp.json() if int(r["T"]) < now_ms]
        if not rows:
            break
        frames.append(
            pl.DataFrame(rows).select(
                pl.from_epoch(pl.col("t").cast(pl.Int64), time_unit="ms")
                .dt.replace_time_zone("UTC")
                .alias("ts"),
                pl.col("o").cast(pl.Float64).alias("open"),
                pl.col("h").cast(pl.Float64).alias("high"),
                pl.col("l").cast(pl.Float64).alias("low"),
                pl.col("c").cast(pl.Float64).alias("close"),
                pl.col("v").cast(pl.Float64).alias("volume"),
            )
        )
        nxt = int(rows[-1]["t"]) + DAY_MS
        if nxt <= cursor:
            break
        cursor = nxt
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames).with_columns(
        (pl.col("close") * pl.col("volume")).alias("quote_volume")
    )


def fetch_funding(client: PoliteClient, coin: str, start_ms: int) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    cursor = start_ms
    while True:
        resp = client.post(INFO, json={"type": "fundingHistory", "coin": coin, "startTime": cursor})
        resp.raise_for_status()
        rows: list[dict[str, Any]] = resp.json()
        if not rows:
            break
        frames.append(
            pl.DataFrame(rows).select(
                pl.from_epoch(pl.col("time").cast(pl.Int64), time_unit="ms")
                .dt.replace_time_zone("UTC")
                .dt.truncate("1m")
                .alias("ts"),
                pl.col("fundingRate").cast(pl.Float64).alias("rate"),
                pl.lit(1.0).alias("interval_hours"),
            )
        )
        nxt = int(rows[-1]["time"]) + 1
        if nxt <= cursor or len(rows) < 2:
            break
        cursor = nxt
    return pl.concat(frames) if frames else pl.DataFrame()
