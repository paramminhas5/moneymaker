"""Polymarket Gamma API: read-only snapshots of open markets, used as signal features only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import polars as pl

from mm.data.http import PoliteClient

GAMMA = "https://gamma-api.polymarket.com/markets"


def _yes_price(raw: Any) -> float | None:
    try:
        prices = json.loads(raw) if isinstance(raw, str) else raw
        return float(prices[0])
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        return None


def fetch_open_markets(
    client: PoliteClient, *, min_liquidity: float = 10_000, page: int = 500, max_pages: int = 40
) -> pl.DataFrame:
    snap_ts = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for i in range(max_pages):
        resp = client.get(
            GAMMA,
            params={
                "active": "true",
                "closed": "false",
                "limit": page,
                "offset": i * page,
                "liquidity_num_min": min_liquidity,
            },
        )
        resp.raise_for_status()
        batch: list[dict[str, Any]] = resp.json()
        if not batch:
            break
        for m in batch:
            rows.append(
                {
                    "snapshot_ts": snap_ts,
                    "market_id": str(m.get("id")),
                    "slug": m.get("slug"),
                    "question": m.get("question"),
                    "end_date": m.get("endDate"),
                    "yes_price": _yes_price(m.get("outcomePrices")),
                    "volume": float(m.get("volume") or 0),
                    "liquidity": float(m.get("liquidity") or 0),
                }
            )
        if len(batch) < page:
            break
    return pl.DataFrame(rows) if rows else pl.DataFrame()
