"""'One trade a day' tester: one entry per UTC day, take-profit / stop / end-of-day exit.

Built to test the owner's idea (one trade a day for a 5-6% return) honestly:
- hourly bars; if a bar touches both TP and SL, the stop is assumed to hit first
- taker fees and slippage both sides (Hyperliquid base tier), extra slippage on stops
- funding charged for the hours held; gaps through a stop fill at the bar open
- account return = leverage x price return; a loss can never exceed the whole account
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import polars as pl

FEE_SIDE = 0.00045 + 0.0001  # taker 4.5bp + 1bp slippage per side
STOP_SLIP = 0.0005


@dataclass(frozen=True, slots=True)
class Day:
    date: object
    o: np.ndarray  # 24 hourly opens
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    prev_close: float
    prev_range: float
    prev_ret: float
    sma20: float
    funding_day: float  # sum of the day's funding rates (longs pay if positive)


def build_days(bars: pl.DataFrame, funding: pl.DataFrame | None) -> list[Day]:
    b = bars.with_columns(pl.col("ts").dt.date().alias("d")).sort("ts")
    full = b.group_by("d").len().filter(pl.col("len") == 24).select("d")
    b = b.join(full, on="d").sort("ts")
    daily = (
        b.group_by("d", maintain_order=True)
        .agg(
            pl.col("open").first().alias("do"),
            pl.col("high").max().alias("dh"),
            pl.col("low").min().alias("dl"),
            pl.col("close").last().alias("dc"),
        )
        .sort("d")
        .with_columns(
            pl.col("dc").shift(1).alias("prev_close"),
            (pl.col("dh") - pl.col("dl")).shift(1).alias("prev_range"),
            (pl.col("dc") / pl.col("dc").shift(1) - 1).shift(1).alias("prev_ret"),
            pl.col("dc").rolling_mean(20).shift(1).alias("sma20"),
        )
    )
    fmap: dict[object, float] = {}
    if funding is not None:
        f = (
            funding.with_columns(pl.col("ts").dt.date().alias("d"))
            .group_by("d")
            .agg(pl.col("rate").sum())
        )
        fmap = dict(zip(f["d"].to_list(), f["rate"].to_list(), strict=True))
    arr = b.select("open", "high", "low", "close").to_numpy().reshape(-1, 24, 4)
    out: list[Day] = []
    for i, row in enumerate(daily.iter_rows(named=True)):
        if row["sma20"] is None or row["prev_ret"] is None:
            continue
        a = arr[i]
        out.append(
            Day(
                row["d"],
                a[:, 0],
                a[:, 1],
                a[:, 2],
                a[:, 3],
                row["prev_close"],
                row["prev_range"],
                row["prev_ret"],
                row["sma20"],
                fmap.get(row["d"], 0.0),
            )
        )
    return out


# An entry rule returns (direction, entry_hour, entry_price) or None. direction +1 long, -1 short.
Entry = Callable[[Day], tuple[int, int, float] | None]


def always_long(d: Day) -> tuple[int, int, float] | None:
    return 1, 0, float(d.o[0])


def trend(d: Day) -> tuple[int, int, float] | None:
    return (1 if d.prev_close > d.sma20 else -1), 0, float(d.o[0])


def dip_buy(d: Day) -> tuple[int, int, float] | None:
    return (1, 0, float(d.o[0])) if d.prev_ret <= -0.03 else None


def chase(d: Day) -> tuple[int, int, float] | None:
    return (1, 0, float(d.o[0])) if d.prev_ret >= 0.03 else None


def _breakout(d: Day, both: bool) -> tuple[int, int, float] | None:
    up = d.o[0] + 0.5 * d.prev_range
    dn = d.o[0] - 0.5 * d.prev_range
    for k in range(24):
        hit_up = d.h[k] >= up
        hit_dn = both and d.lo[k] <= dn
        if hit_up and hit_dn:
            return None  # ambiguous within the hour: skip the day
        if hit_up:
            return 1, k, float(max(up, d.o[k]))
        if hit_dn:
            return -1, k, float(min(dn, d.o[k]))
    return None


def breakout_long(d: Day) -> tuple[int, int, float] | None:
    return _breakout(d, both=False)


def breakout_both(d: Day) -> tuple[int, int, float] | None:
    return _breakout(d, both=True)


ENTRIES: dict[str, Entry] = {
    "always_long_00utc": always_long,
    "trend_follow_20d": trend,
    "buy_dip_after_-3pct_day": dip_buy,
    "chase_after_+3pct_day": chase,
    "breakout_long": breakout_long,
    "breakout_long_or_short": breakout_both,
}


@dataclass(frozen=True, slots=True)
class Exits:
    acct_tp: float | None  # e.g. 0.05 = take profit at +5% on the account
    acct_sl: float | None
    leverage: float


def trade(d: Day, entry: tuple[int, int, float], ex: Exits) -> tuple[float, str]:
    """Account return for one trade and how it exited (tp / sl / eod)."""
    side, k0, px = entry
    lev = ex.leverage
    tp = px * (1 + side * ex.acct_tp / lev) if ex.acct_tp else None
    sl = px * (1 - side * ex.acct_sl / lev) if ex.acct_sl else None
    start = k0 if k0 == 0 else k0 + 1  # open entries see their own bar; stop entries don't
    exit_px, how, hours = float(d.c[-1]), "eod", 24 - k0
    for k in range(start, 24):
        hi, lo, op = d.h[k], d.lo[k], d.o[k]
        sl_hit = sl is not None and ((side > 0 and lo <= sl) or (side < 0 and hi >= sl))
        tp_hit = tp is not None and ((side > 0 and hi >= tp) or (side < 0 and lo <= tp))
        if sl_hit and sl is not None:  # stop first on ties (conservative); gaps fill at open
            gap = (side > 0 and op < sl) or (side < 0 and op > sl)
            exit_px, how, hours = float(op if gap else sl), "sl", k + 1 - k0
            break
        if tp_hit and tp is not None:
            exit_px, how, hours = float(tp), "tp", k + 1 - k0
            break
    price_ret = side * (exit_px / px - 1)
    cost = 2 * FEE_SIDE + (STOP_SLIP if how == "sl" else 0.0)
    funding = side * d.funding_day * hours / 24
    acct = lev * (price_ret - cost - funding)
    return max(acct, -1.0), how


@dataclass(frozen=True, slots=True)
class Result:
    trades: int
    tp_rate: float
    sl_rate: float
    mean: float
    median: float
    share_ge_5pct: float
    cagr: float
    max_dd: float
    worst_streak: int
    pos_months: float
    final_multiple: float
    yearly: dict[int, float]


def run(days: list[Day], entry: Entry, ex: Exits) -> Result:
    rets, hows, dates = [], [], []
    for d in days:
        e = entry(d)
        if e is None:
            continue
        r, how = trade(d, e, ex)
        rets.append(r)
        hows.append(how)
        dates.append(d.date)
    if not rets:
        return Result(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, {})
    r = np.array(rets)
    eq = np.cumprod(1 + r)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    years = (days[-1].date - days[0].date).days / 365.25  # type: ignore[operator]
    streak = best = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    df = pl.DataFrame({"d": dates, "r": r}).with_columns(pl.col("d").cast(pl.Date))
    monthly = df.group_by(pl.col("d").dt.truncate("1mo")).agg((pl.col("r") + 1).product() - 1)
    yearly = (
        df.group_by(pl.col("d").dt.year().alias("y"))
        .agg(((pl.col("r") + 1).product() - 1).alias("ret"))
        .sort("y")
    )
    final = float(eq[-1])
    return Result(
        trades=len(r),
        tp_rate=hows.count("tp") / len(r),
        sl_rate=hows.count("sl") / len(r),
        mean=float(r.mean()),
        median=float(np.median(r)),
        share_ge_5pct=float((r >= 0.05).mean()),
        cagr=float(final ** (1 / years) - 1) if final > 0 else -1.0,
        max_dd=float(np.max(1 - eq / peaks)),
        worst_streak=best,
        pos_months=float(monthly.select((pl.col("r") > 0).mean()).item()),
        final_multiple=final,
        yearly=dict(zip(yearly["y"].to_list(), yearly["ret"].to_list(), strict=True)),
    )
