"""Vectorised daily backtester for target-weight strategies.

Timing convention (no lookahead by construction): weights decided with data up to the close of
day t are held over (t, t+1]. Day t+1's return uses w_t. Rebalancing cost is charged on day t+1
against the drifted weights. Funding on perps is charged on the weights held.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import polars as pl

from mm.core.types import Side
from mm.costs.models import CostModel
from mm.validation.metrics import FloatArray


@dataclass(frozen=True, slots=True)
class BacktestResult:
    ts: pl.Series
    gross: FloatArray
    net: FloatArray
    costs: FloatArray
    funding: FloatArray
    turnover: FloatArray  # sum |traded weight| per period (one-way)
    weights: FloatArray  # held weights, T x N
    symbols: list[str]

    def frame(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "ts": self.ts,
                "gross": self.gross,
                "net": self.net,
                "costs": self.costs,
                "funding": self.funding,
                "turnover": self.turnover,
            }
        )

    @property
    def annual_turnover(self) -> float:
        return float(self.turnover.mean() * 365) if self.turnover.size else 0.0

    @property
    def annual_cost_drag(self) -> float:
        return float(self.costs.mean() * 365) if self.costs.size else 0.0


def wide(frames: Mapping[str, pl.DataFrame], column: str = "close") -> pl.DataFrame:
    """Align per-symbol frames on a common daily ts index (outer join, sorted)."""
    out: pl.DataFrame | None = None
    for sym, df in frames.items():
        part = df.select("ts", pl.col(column).alias(sym))
        out = part if out is None else out.join(part, on="ts", how="full", coalesce=True)
    if out is None:
        raise ValueError("no frames")
    return out.sort("ts")


def run_weights(
    close: pl.DataFrame,
    weights: pl.DataFrame,
    *,
    cost_bps: float | Mapping[str, float] = 10.0,
    cost_model: CostModel | None = None,
    capital: float | None = None,
    funding: pl.DataFrame | None = None,
) -> BacktestResult:
    """close, weights (and optional daily funding): wide frames with `ts` + one column per symbol.

    Costs: either a flat one-way `cost_bps` (scalar or per symbol), or a capital-aware
    `cost_model` with `capital` (needed when fees have fixed parts, e.g. India DP charges).
    Funding: per-day rate as a fraction; positive means longs pay shorts.
    """
    symbols = [c for c in close.columns if c != "ts"]
    if [c for c in weights.columns if c != "ts"] != symbols:
        raise ValueError("weights columns must match close columns in the same order")
    if not close["ts"].equals(weights["ts"]):
        raise ValueError("weights must share the close ts index")

    px = close.select(symbols).to_numpy().astype(np.float64)
    w = weights.select(symbols).to_numpy().astype(np.float64)
    w = np.nan_to_num(w, nan=0.0)
    t, n = px.shape
    # A symbol with no price today cannot be traded today: keep whatever was held (no phantom
    # exits and re-entries on data gaps). Before a symbol's first price, nothing can be held.
    tradable = np.isfinite(px)
    seen = np.cumsum(tradable, axis=0) > 0
    for i in range(t):
        for j in range(n):
            if not tradable[i, j]:
                w[i, j] = w[i - 1, j] if i > 0 and seen[i, j] else 0.0

    with np.errstate(divide="ignore", invalid="ignore"):
        rets = px[1:] / px[:-1] - 1.0
    rets = np.vstack([np.zeros((1, n)), np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)])

    fund = np.zeros((t, n))
    if funding is not None:
        f = close.select("ts").join(funding, on="ts", how="left").select(symbols).to_numpy()
        fund = np.nan_to_num(f.astype(np.float64), nan=0.0)

    if isinstance(cost_bps, Mapping):
        bps = np.array([cost_bps.get(s, 0.0) for s in symbols], dtype=np.float64)
    else:
        bps = np.full(n, float(cost_bps))

    held = np.vstack([np.zeros((1, n)), w[:-1]])  # weights held over (t-1, t]
    gross = (held * rets).sum(axis=1)
    fund_pnl = -(held * fund).sum(axis=1)
    # Drifted weights just before rebalancing at the close of t
    with np.errstate(divide="ignore", invalid="ignore"):
        drifted = held * (1.0 + rets) / (1.0 + gross)[:, None]
    drifted = np.nan_to_num(drifted)
    trades = w - drifted
    turnover = np.abs(trades).sum(axis=1)

    costs = np.zeros(t)
    if cost_model is not None:
        if capital is None:
            raise ValueError("cost_model needs capital to price fixed fees")
        equity = capital
        net = np.zeros(t)
        for i in range(t):
            pre = gross[i] + fund_pnl[i]
            eq_pre = equity * (1 + pre)
            c = 0.0
            for j in range(n):
                notional = abs(trades[i, j]) * eq_pre
                if notional > 1e-9:
                    side = Side.BUY if trades[i, j] > 0 else Side.SELL
                    c += cost_model.cost(notional, side)
            costs[i] = c / eq_pre if eq_pre > 0 else 0.0
            net[i] = pre - costs[i]
            equity *= 1 + net[i]
    else:
        costs = (np.abs(trades) * bps).sum(axis=1) / 10_000
        net = gross + fund_pnl - costs

    return BacktestResult(close["ts"], gross, net, costs, fund_pnl, turnover, w, symbols)
