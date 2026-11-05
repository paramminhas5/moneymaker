"""Listing fade with intraday stop orders: trade-level daily simulation using daily highs.

The `listing_fade` Spec checks its stop on daily closes, which cannot model a resting stop order:
a coin that rips +500% intraday is covered at the close, far above the stop. Here each short has
a stop-market order at entry * (1 + stop). On a day whose high reaches it, the short is covered
at max(stop price, open) * (1 + slippage) (a gap through the stop fills at the open). Same entry,
hold, cap and funding rules as the Spec; 1/max_names of equity per name, re-marked daily.
Costs: `cost_bps` one-way on entry and exit. Returns one net return per day.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from mm.validation.metrics import FloatArray


@dataclass(frozen=True, slots=True)
class StopParams:
    delay: int = 1
    hold: int = 28
    stop: float = 0.5
    max_names: int = 3
    slippage: float = 0.10  # fill this much beyond the stop (squeezes are illiquid)
    cost_bps: float = 20.0


def simulate(
    close: pl.DataFrame,
    high: pl.DataFrame,
    open_: pl.DataFrame,
    funding: pl.DataFrame,
    p: StopParams,
) -> tuple[FloatArray, int, int]:
    """Daily net returns, number of trades and number of stop-outs."""
    syms = [c for c in close.columns if c != "ts"]
    c = close.select(syms).to_numpy().astype(np.float64)
    h = high.select(syms).to_numpy().astype(np.float64)
    o = open_.select(syms).to_numpy().astype(np.float64)
    f = funding.select(syms).to_numpy().astype(np.float64)
    t, n = c.shape
    has = np.isfinite(c)
    first = np.where(has.any(axis=0), has.argmax(axis=0), t + 10**6)
    entries_on: dict[int, list[int]] = {}
    for j in range(n):
        entries_on.setdefault(int(first[j]) + p.delay, []).append(j)
    w = 1.0 / p.max_names
    cost = p.cost_bps / 10_000
    active: dict[int, tuple[int, float]] = {}  # col -> (entry row, entry price)
    out = np.zeros(t)
    trades = stops = 0
    for i in range(t):
        r = 0.0
        for j in list(active):
            e_row, e_px = active[j]
            if i == e_row:
                continue
            prev, px = c[i - 1, j], c[i, j]
            if not np.isfinite(px) or not np.isfinite(prev):
                del active[j]  # delisted: covered at the last close
                r -= w * cost
                continue
            stop_px = e_px * (1 + p.stop)
            if np.isfinite(h[i, j]) and h[i, j] >= stop_px:
                fill = max(stop_px, o[i, j] if np.isfinite(o[i, j]) else stop_px) * (1 + p.slippage)
                r += w * (-(fill / prev - 1) - cost)
                stops += 1
                del active[j]
                continue
            r += w * (-(px / prev - 1) + (f[i, j] if np.isfinite(f[i, j]) else 0.0))
            if i >= e_row + p.hold:
                r -= w * cost
                del active[j]
        for j in entries_on.get(i, []):
            if len(active) < p.max_names and np.isfinite(c[i, j]):
                active[j] = (i, float(c[i, j]))
                r -= w * cost
                trades += 1
        out[i] = r
    return out, trades, stops
