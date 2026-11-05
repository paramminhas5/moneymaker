"""Polymarket resolved-market history for the bonding backtest (public Gamma + CLOB, read-only).

Sampling: Gamma lists ~500 resolved markets a day above $25k volume, so we take every k-th page
of the closed-time-ordered listing. That spreads the sample evenly over time without bias
toward any category. Price history is the CLOB `prices-history` endpoint, 10-minute fidelity
over the last `window_days` before close.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import polars as pl

from mm.data.http import PoliteClient

GAMMA = "https://gamma-api.polymarket.com/markets"
HISTORY = "https://clob.polymarket.com/prices-history"


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = raw.replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _row(m: dict[str, Any]) -> dict[str, Any] | None:
    try:
        tokens = json.loads(m.get("clobTokenIds") or "[]")
        prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    closed = _parse_ts(m.get("closedTime"))
    if len(tokens) != 2 or len(prices) != 2 or closed is None:
        return None
    ev = (m.get("events") or [{}])[0]
    tags = [t.get("slug", "") for t in (ev.get("tags") or [])]
    return {
        "market_id": str(m.get("id")),
        "question": m.get("question") or "",
        "slug": m.get("slug") or "",
        "event_slug": ev.get("slug") or "",
        "tags": ",".join(t for t in tags if t),
        "start": _parse_ts(m.get("startDate")),
        "closed": closed,
        "neg_risk": bool(m.get("negRisk")),
        "volume": float(m.get("volumeNum") or m.get("volume") or 0),
        "uma_status": m.get("umaResolutionStatus") or "",
        "description": (m.get("description") or "")[:2000],
        "token0": str(tokens[0]),
        "token1": str(tokens[1]),
        "final0": prices[0],
        "final1": prices[1],
    }


def sample_closed_markets(
    client: PoliteClient,
    *,
    days: list[str],
    per_day: int = 100,
    min_volume: float = 25_000,
) -> pl.DataFrame:
    """For each ISO day, the `per_day` highest-volume markets whose end date falls on it.

    Gamma caps list offsets near 2,000, so time-spread sampling is done by end-date window.
    Biased toward liquid markets by construction, which is what a bonding sleeve can trade.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for day in days:
        resp = client.get(
            GAMMA,
            params={
                "closed": "true",
                "limit": per_day,
                "end_date_min": f"{day}T00:00:00Z",
                "end_date_max": f"{day}T23:59:59Z",
                "volume_num_min": min_volume,
                "order": "volumeNum",
                "ascending": "false",
                "include_tag": "true",
            },
        )
        resp.raise_for_status()
        for m in resp.json():
            r = _row(m)
            if r is not None and r["market_id"] not in seen:
                seen.add(r["market_id"])
                rows.append(r)
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def fetch_history(
    client: PoliteClient, token: str, end: datetime, *, window_days: int = 7, fidelity: int = 10
) -> list[tuple[int, float]]:
    end_ts = int(end.timestamp())
    resp = client.get(
        HISTORY,
        params={
            "market": token,
            "startTs": end_ts - window_days * 86_400,
            "endTs": end_ts,
            "fidelity": fidelity,
        },
    )
    if resp.status_code != 200:
        return []
    return [(int(h["t"]), float(h["p"])) for h in resp.json().get("history", [])]
