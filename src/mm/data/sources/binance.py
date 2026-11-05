"""Binance official public market data.

- Spot daily klines: data-api.binance.vision (Binance's public market-data mirror), paginated.
- USD-M perp daily klines and funding history: data.binance.vision monthly archives.
  Archives keep delisted symbols, which keeps backtests free of survivorship bias.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl

from mm.data.http import PoliteClient

SPOT_API = "https://data-api.binance.vision/api/v3/klines"
ARCHIVE = "https://data.binance.vision/data/futures/um/monthly"
DAY_MS = 86_400_000

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]  # fmt: skip


def _klines_to_frame(rows: Sequence[Sequence[object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame(rows, schema=KLINE_COLS, orient="row")
    return df.select(
        pl.from_epoch(pl.col("open_time").cast(pl.Int64), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .alias("ts"),
        *[pl.col(c).cast(pl.Float64) for c in ("open", "high", "low", "close", "volume")],
        pl.col("quote_volume").cast(pl.Float64),
    )


def fetch_spot_daily(
    client: PoliteClient, symbol: str, start_ms: int, end_ms: int | None = None
) -> pl.DataFrame:
    """Daily spot candles from start_ms (inclusive). Only fully closed candles are returned."""
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    end_ms = end_ms or now_ms
    frames: list[pl.DataFrame] = []
    cursor = start_ms
    while cursor < end_ms:
        resp = client.get(
            SPOT_API,
            params={"symbol": symbol, "interval": "1d", "startTime": cursor, "limit": 1000},
        )
        if resp.status_code == 400:  # unknown symbol
            break
        resp.raise_for_status()
        rows: list[list[object]] = resp.json()
        rows = [r for r in rows if int(str(r[6])) < now_ms and int(str(r[0])) < end_ms]
        if not rows:
            break
        frames.append(_klines_to_frame(rows))
        cursor = int(str(rows[-1][0])) + DAY_MS
    return pl.concat(frames) if frames else pl.DataFrame()


def _months(start: date, end: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _read_archive_csv(client: PoliteClient, url: str) -> pl.DataFrame | None:
    resp = client.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        raw = zf.read(zf.namelist()[0])
    first = raw.split(b"\n", 1)[0]
    has_header = any(ch.isalpha() for ch in first.decode(errors="ignore"))
    return pl.read_csv(io.BytesIO(raw), has_header=has_header, infer_schema_length=0)


def _last_full_month(today: date) -> date:
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def fetch_perp_daily(client: PoliteClient, symbol: str, start: date) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for y, m in _months(start, _last_full_month(datetime.now(UTC).date())):
        url = f"{ARCHIVE}/klines/{symbol}/1d/{symbol}-1d-{y}-{m:02d}.zip"
        df = _read_archive_csv(client, url)
        if df is None:
            continue
        df.columns = KLINE_COLS[: len(df.columns)]
        frames.append(_klines_to_frame(df.rows()))
    return pl.concat(frames) if frames else pl.DataFrame()


def fetch_perp_funding(client: PoliteClient, symbol: str, start: date) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for y, m in _months(start, _last_full_month(datetime.now(UTC).date())):
        url = f"{ARCHIVE}/fundingRate/{symbol}/{symbol}-fundingRate-{y}-{m:02d}.zip"
        df = _read_archive_csv(client, url)
        if df is None:
            continue
        if df.columns[0] != "calc_time":
            df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
        frames.append(
            df.select(
                pl.from_epoch(pl.col("calc_time").cast(pl.Int64), time_unit="ms")
                .dt.replace_time_zone("UTC")
                .dt.truncate("1m")
                .alias("ts"),
                pl.col("last_funding_rate").cast(pl.Float64).alias("rate"),
                pl.col("funding_interval_hours").cast(pl.Float64).alias("interval_hours"),
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame()


S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
_KEY_RE = r"<Key>([^<]+)</Key>"
_PREFIX_RE = r"<Prefix>([^<]+)</Prefix>"


def _s3_list(client: PoliteClient, prefix: str) -> tuple[list[str], list[str]]:
    """All keys and common prefixes under `prefix` in the public archive bucket (paginated)."""
    import re

    keys: list[str] = []
    prefixes: list[str] = []
    marker = ""
    while True:
        resp = client.get(S3_LIST, params={"delimiter": "/", "prefix": prefix, "marker": marker})
        resp.raise_for_status()
        body = resp.text
        page_keys = re.findall(_KEY_RE, body)
        page_prefixes = [p for p in re.findall(_PREFIX_RE, body) if p != prefix]
        keys += page_keys
        prefixes += page_prefixes
        if "<IsTruncated>true</IsTruncated>" not in body:
            break
        nxt = re.search(r"<NextMarker>([^<]+)</NextMarker>", body)
        marker = nxt.group(1) if nxt else (page_keys or page_prefixes)[-1]
    return keys, prefixes


def list_perp_symbols(client: PoliteClient) -> list[str]:
    """Every USD-M perp symbol that has ever had a monthly kline archive, delisted ones included."""
    _, prefixes = _s3_list(client, "data/futures/um/monthly/klines/")
    return sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes)


def perp_archive_months(client: PoliteClient, symbol: str) -> list[tuple[int, int]]:
    """(year, month) of every daily-kline monthly archive for a perp, oldest first."""
    import re

    keys, _ = _s3_list(client, f"data/futures/um/monthly/klines/{symbol}/1d/")
    out: list[tuple[int, int]] = []
    for k in keys:
        m = re.search(r"-1d-(\d{4})-(\d{2})\.zip$", k)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return sorted(out)


def fetch_perp_window(
    client: PoliteClient, symbol: str, months: list[tuple[int, int]]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Daily klines and funding for an explicit list of archive months."""
    bars: list[pl.DataFrame] = []
    funds: list[pl.DataFrame] = []
    for y, m in months:
        kl = _read_archive_csv(client, f"{ARCHIVE}/klines/{symbol}/1d/{symbol}-1d-{y}-{m:02d}.zip")
        if kl is not None:
            kl.columns = KLINE_COLS[: len(kl.columns)]
            bars.append(_klines_to_frame(kl.rows()))
        fr = _read_archive_csv(
            client, f"{ARCHIVE}/fundingRate/{symbol}/{symbol}-fundingRate-{y}-{m:02d}.zip"
        )
        if fr is not None:
            if fr.columns[0] != "calc_time":
                fr.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
            funds.append(
                fr.select(
                    pl.from_epoch(pl.col("calc_time").cast(pl.Int64), time_unit="ms")
                    .dt.replace_time_zone("UTC")
                    .dt.truncate("1m")
                    .alias("ts"),
                    pl.col("last_funding_rate").cast(pl.Float64).alias("rate"),
                    pl.col("funding_interval_hours").cast(pl.Float64).alias("interval_hours"),
                )
            )
    return (
        pl.concat(bars) if bars else pl.DataFrame(),
        pl.concat(funds) if funds else pl.DataFrame(),
    )
