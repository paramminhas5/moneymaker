"""Yahoo Finance chart endpoint: daily OHLC + split/dividend-adjusted close for ETFs and stocks.

Unofficial but public. Used politely (one request per symbol, >=1s apart). The adjusted close
is used for returns so dividends and splits are included.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.data.http import PoliteClient

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"


def fetch_daily(client: PoliteClient, symbol: str, start_epoch: int = 946_684_800) -> pl.DataFrame:
    resp = client.get(
        CHART.format(sym=symbol),
        params={
            "period1": start_epoch,
            "period2": 4_102_444_800,
            "interval": "1d",
            "events": "div,splits",
        },
    )
    if resp.status_code == 404:
        return pl.DataFrame()
    resp.raise_for_status()
    res: dict[str, Any] = resp.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    if not ts:
        return pl.DataFrame()
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
    df = pl.DataFrame(
        {
            "ts": ts,
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"],
            "volume": q["volume"],
            "adj_close": adj,
        },
        strict=False,
    )
    return (
        df.with_columns(
            pl.from_epoch("ts", time_unit="s")
            .dt.replace_time_zone("UTC")
            .dt.truncate("1d")
            .dt.cast_time_unit("ms")
            .alias("ts"),
            *[
                pl.col(c).cast(pl.Float64)
                for c in ("open", "high", "low", "close", "volume", "adj_close")
            ],
        )
        .drop_nulls("adj_close")
        .with_columns((pl.col("close") * pl.col("volume")).alias("quote_volume"))
        .unique("ts", keep="last")
        .sort("ts")
    )
