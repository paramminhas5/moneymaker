"""Bonding backtest: buy whichever side of a market first trades inside [lo, hi] within
`max_days` of close, hold to resolution, get the final price (1, 0, or 0.5 on a 50-50).

The trigger is outcome-blind: both tokens are scanned and the first one to enter the band is
bought, so losing sides that briefly traded at 95c+ are included. That is the tail risk.
Fills are assumed at the observed price as a resting maker bid (zero fee); `fill_haircut`
adds a price penalty to stay conservative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import polars as pl

FOOTBALL = {
    "fifwc",
    "fif",
    "epl",
    "ucl",
    "uel",
    "lal",
    "sea",
    "bun",
    "fl1",
    "mls",
    "efl",
    "unl",
    "spl",
    "bra",
    "arg",
    "mex",
    "por",
    "ned",
    "tur",
    "sco",
}
SPORTS = {
    "mlb",
    "atp",
    "wta",
    "nba",
    "nfl",
    "cfb",
    "wnba",
    "ufc",
    "nhl",
    "crint",
    "cricipl",
    "cbb",
    "ncaab",
    "f1",
    "pga",
    "boxing",
}
ESPORTS = {"lol", "cs2", "dota2", "val", "r6", "rl"}
CRYPTO = {"bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "crypto", "doge"}
MENTIONS = {"elon", "what", "trump-say", "say"}


def category(event_slug: str) -> str:
    pre = event_slug.split("-", 1)[0] if event_slug else ""
    if pre in FOOTBALL:
        return "football"
    if pre in SPORTS:
        return "sports"
    if pre in ESPORTS:
        return "esports"
    if pre in CRYPTO or "-above-" in event_slug or "up-or-down" in event_slug:
        return "crypto"
    if pre in MENTIONS or "tweets" in event_slug:
        return "mentions"
    return "politics_other"


@dataclass(frozen=True, slots=True)
class BondParams:
    lo: float = 0.95
    hi: float = 0.985
    max_days: float = 7.0
    min_days: float = 0.0  # skip entries this close to close (in-play last minutes)
    fill_haircut: float = 0.002  # 0.2c worse than observed
    settle_lag_days: float = 0.1  # capital locked a little after close (UMA liveness)
    categories: tuple[str, ...] = ()  # empty = all
    one_per_event: bool = True  # correlated legs of one event count once
    stable_hours: float = 0.0  # require price >= lo for this long before entering
    min_lifetime_days: float = 1.0  # skip 5/15-minute markets


def find_trades(markets: pl.DataFrame, prices: pl.DataFrame, p: BondParams) -> pl.DataFrame:
    """prices: market_id, side (0/1), t (epoch s), price."""
    rows: list[dict[str, object]] = []
    by_mkt = {k[0]: v for k, v in prices.partition_by("market_id", as_dict=True).items()}
    for m in markets.iter_rows(named=True):
        cat = category(str(m["event_slug"]))
        if p.categories and cat not in p.categories:
            continue
        start, closed = m["start"], m["closed"]
        if start is not None and (closed - start).total_seconds() < p.min_lifetime_days * 86_400:
            continue
        px = by_mkt.get(m["market_id"])
        if px is None or px.is_empty():
            continue
        close_ts = closed.timestamp()
        if p.stable_hours > 0:
            px = (
                px.sort("side", "t")
                .with_columns(pl.from_epoch("t").alias("dt"))
                .with_columns(
                    pl.col("price")
                    .rolling_min_by("dt", window_size=f"{int(p.stable_hours * 60)}m")
                    .over("side")
                    .alias("floor"),
                    (pl.col("t") - pl.col("t").min().over("side")).alias("age"),
                )
                .filter((pl.col("floor") >= p.lo) & (pl.col("age") >= p.stable_hours * 3600))
            )
        cand = px.filter(
            (pl.col("price") >= p.lo)
            & (pl.col("price") <= p.hi)
            & ((close_ts - pl.col("t")) <= p.max_days * 86_400)
            & ((close_ts - pl.col("t")) >= p.min_days * 86_400)
        ).sort("t")
        if cand.is_empty():
            continue
        first = cand.row(0, named=True)
        side = int(first["side"])
        entry = min(float(first["price"]) + p.fill_haircut, 0.999)
        payout = float(m["final0"] if side == 0 else m["final1"])
        hold = (close_ts - first["t"]) / 86_400 + p.settle_lag_days
        rows.append(
            {
                "market_id": m["market_id"],
                "question": m["question"],
                "event": m["event_slug"],
                "category": cat,
                "entry_t": datetime.fromtimestamp(first["t"], tz=UTC),
                "exit_t": datetime.fromtimestamp(close_ts + p.settle_lag_days * 86_400, tz=UTC),
                "entry": entry,
                "payout": payout,
                "ret": payout / entry - 1,
                "hold_days": hold,
            }
        )
    if not rows:
        return pl.DataFrame()
    out = pl.DataFrame(rows).sort("entry_t")
    if p.one_per_event:
        out = out.unique(subset="event", keep="first", maintain_order=True)
    return out


@dataclass(frozen=True, slots=True)
class BookResult:
    trades: int
    taken: int
    win_rate: float
    mean_ret: float
    median_hold: float
    total_return: float
    annualised: float
    max_drawdown: float
    worst: list[tuple[str, float]]


def simulate_book(
    trades: pl.DataFrame, *, capital: float = 1000.0, stake_frac: float = 0.03
) -> BookResult:
    """Time-ordered: each trade takes stake_frac of current equity if cash allows."""
    if trades.is_empty():
        return BookResult(0, 0, 0, 0, 0, 0, 0, 0, [])
    events: list[tuple[datetime, int, int]] = []  # (time, kind 0=exit first, idx)
    tr = trades.sort("entry_t")
    for i, r in enumerate(tr.iter_rows(named=True)):
        events.append((r["entry_t"], 1, i))
        events.append((r["exit_t"], 0, i))
    events.sort()
    cash, open_pos = capital, {}
    eq_curve: list[float] = []
    taken = 0
    rows = tr.to_dicts()
    for _, kind, i in events:
        if kind == 1:
            equity = cash + sum(open_pos.values())
            stake = equity * stake_frac
            if cash >= stake > 0:
                cash -= stake
                open_pos[i] = stake
                taken += 1
        elif i in open_pos:
            stake = open_pos.pop(i)
            cash += stake * (1 + rows[i]["ret"])
        eq_curve.append(cash + sum(open_pos.values()))
    eq = np.array(eq_curve)
    peaks = np.maximum.accumulate(eq)
    span = tr.select((pl.col("exit_t").max() - pl.col("entry_t").min()).dt.total_seconds()).item()
    days = max(float(span) / 86_400, 1.0)
    total = eq[-1] / capital - 1
    worst = tr.sort("ret").head(5).select("question", "ret").rows()
    return BookResult(
        trades=tr.height,
        taken=taken,
        win_rate=float(tr.select((pl.col("ret") > 0).mean()).item()),
        mean_ret=float(tr.select(pl.col("ret").mean()).item()),
        median_hold=float(tr.select(pl.col("hold_days").median()).item()),
        total_return=float(total),
        annualised=float((1 + total) ** (365 / days) - 1),
        max_drawdown=float(np.max(1 - eq / peaks)),
        worst=[(str(q)[:70], float(r)) for q, r in worst],
    )
