"""Theme-call sleeve tracker: Param's manual theme calls, scored against QQQ.

Calls live in `ledger/theme_calls.csv` (committed, append-only, human-authored through
`mm theme add`). A call is entered at the first close strictly AFTER the call date (so a call made
during the day never gets that day's close for free) and is compared with QQQ over exactly the
same dates. Nothing here trades; it is a scorecard that decides whether this sleeve earns capital.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

LEDGER = Path(__file__).resolve().parents[3] / "ledger" / "theme_calls.csv"
FIELDS = ["date", "ticker", "thesis", "horizon_days"]
BENCH = "QQQ"

PriceFn = Callable[[str], pl.DataFrame]  # symbol -> frame(ts, adj_close)


@dataclass(frozen=True, slots=True)
class ThemeCall:
    date: date
    ticker: str
    thesis: str
    horizon_days: int = 180


def load_calls(path: Path = LEDGER) -> list[ThemeCall]:
    if not path.exists():
        return []
    with path.open() as fh:
        return [
            ThemeCall(
                date.fromisoformat(r["date"]),
                r["ticker"].upper(),
                r["thesis"],
                int(r.get("horizon_days") or 180),
            )
            for r in csv.DictReader(fh)
        ]


def add_call(call: ThemeCall, path: Path = LEDGER) -> None:
    if not call.ticker.strip() or not call.thesis.strip():
        raise ValueError("ticker and thesis are required")
    if call.date > datetime.now(UTC).date():
        raise ValueError("a call cannot be dated in the future")
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        row = asdict(call)
        row["date"] = call.date.isoformat()
        row["ticker"] = call.ticker.upper()
        w.writerow(row)


def _ret(px: pl.DataFrame, start: date, end: date | None) -> tuple[date, date, float] | None:
    after = px.filter(pl.col("ts").dt.date() > start).sort("ts")
    if after.height < 2:
        return None
    entry_d, entry_p = after["ts"][0].date(), float(after["adj_close"][0])
    window = after if end is None else after.filter(pl.col("ts").dt.date() <= end)
    exit_d, exit_p = window["ts"][-1].date(), float(window["adj_close"][-1])
    return entry_d, exit_d, exit_p / entry_p - 1


def score(calls: list[ThemeCall], prices: PriceFn, today: date | None = None) -> pl.DataFrame:
    """One row per call: return since entry (capped at the horizon), QQQ over the same dates,
    and the excess. Calls with no price after the call date yet are reported as pending."""
    today = today or datetime.now(UTC).date()
    bench = prices(BENCH)
    rows: list[dict[str, object]] = []
    for c in calls:
        horizon_end = date.fromordinal(c.date.toordinal() + c.horizon_days)
        end = horizon_end if horizon_end < today else None
        r = _ret(prices(c.ticker), c.date, end)
        if r is None:
            rows.append(
                {
                    "date": c.date,
                    "ticker": c.ticker,
                    "thesis": c.thesis,
                    "status": "pending",
                    "entry": None,
                    "exit": None,
                    "ret": None,
                    "qqq": None,
                    "excess": None,
                }
            )
            continue
        entry_d, exit_d, ret = r
        b = _ret(bench, c.date, exit_d)
        q = b[2] if b else 0.0
        rows.append(
            {
                "date": c.date,
                "ticker": c.ticker,
                "thesis": c.thesis,
                "status": "closed" if end else "open",
                "entry": entry_d,
                "exit": exit_d,
                "ret": ret,
                "qqq": q,
                "excess": ret - q,
            }
        )
    return pl.DataFrame(rows)


def summary(scored: pl.DataFrame) -> dict[str, float]:
    live = scored.filter(pl.col("ret").is_not_null()) if scored.height else scored
    if live.height == 0:
        return {"calls": float(scored.height), "scored": 0.0}
    return {
        "calls": float(scored.height),
        "scored": float(live.height),
        "hit_rate_vs_qqq": float((live["excess"] > 0).mean()),  # type: ignore[arg-type]
        "mean_excess": float(live["excess"].mean()),  # type: ignore[arg-type]
        "median_excess": float(live["excess"].median()),  # type: ignore[arg-type]
        "mean_ret": float(live["ret"].mean()),  # type: ignore[arg-type]
    }


def yahoo_prices(symbol: str) -> pl.DataFrame:
    """Daily adjusted closes from the lake, refreshed from Yahoo when missing or stale."""
    from mm.data.catalog import Catalog
    from mm.data.http import PoliteClient
    from mm.data.sources.yahoo import fetch_daily

    cat = Catalog()
    path = cat.root / "bars_1d" / "yahoo" / f"{symbol}.parquet"
    if path.exists():
        df = pl.read_parquet(path)
        if (datetime.now(UTC).date() - df["ts"].max().date()).days <= 3:  # type: ignore[union-attr]
            return df.select("ts", "adj_close")
    with PoliteClient(min_interval_s=1.0) as client:
        df = fetch_daily(client, symbol)
    if df.is_empty():
        return pl.DataFrame(schema={"ts": pl.Datetime("ms", "UTC"), "adj_close": pl.Float64})
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return df.select("ts", "adj_close")
