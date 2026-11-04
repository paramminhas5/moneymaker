"""Cost models. All return cost in the trade's currency for one fill.

Numbers marked VERIFY are best public estimates as of Nov 2026 and must be checked against the
venue's current schedule before live trading (they live in config, not code, once confirmed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mm.core.types import Side


class CostModel(Protocol):
    def cost(
        self, notional: float, side: Side, *, maker: bool = False, shares: float = 0.0
    ) -> float: ...

    def round_trip_bps(self, notional: float) -> float: ...


def _rt_bps(model: CostModel, notional: float) -> float:
    if notional <= 0:
        return 0.0
    total = model.cost(notional, Side.BUY) + model.cost(notional, Side.SELL)
    return total / notional * 10_000


@dataclass(frozen=True, slots=True)
class BpsCost:
    """Crypto venues: fee in bps plus half-spread and slippage in bps (taker by default)."""

    maker_bps: float
    taker_bps: float
    half_spread_bps: float = 1.0
    slippage_bps: float = 1.0

    def cost(
        self, notional: float, side: Side, *, maker: bool = False, shares: float = 0.0
    ) -> float:
        fee = self.maker_bps if maker else self.taker_bps
        crossing = 0.0 if maker else self.half_spread_bps + self.slippage_bps
        return abs(notional) * (fee + crossing) / 10_000

    def round_trip_bps(self, notional: float) -> float:
        return _rt_bps(self, notional)


@dataclass(frozen=True, slots=True)
class IbkrPerShareCost:
    """IBKR fixed pricing: $0.005/share, $1 minimum, max 1% of trade value (VERIFY)."""

    per_share: float = 0.005
    minimum: float = 1.0
    max_pct: float = 0.01
    half_spread_bps: float = 1.0

    def cost(
        self, notional: float, side: Side, *, maker: bool = False, shares: float = 0.0
    ) -> float:
        notional = abs(notional)
        commission = min(max(shares * self.per_share, self.minimum), notional * self.max_pct)
        return commission + notional * self.half_spread_bps / 10_000

    def round_trip_bps(self, notional: float) -> float:
        return _rt_bps(self, notional)


@dataclass(frozen=True, slots=True)
class IndiaDeliveryCost:
    """NSE delivery trade in INR. Defaults are for equity ETFs via a discount broker (VERIFY).

    The DP (depository) charge is a flat fee per scrip per sell day. At small sizes it dominates:
    Rs 15.93 on a Rs 2,000 sale is 0.8%, which is why S4 rebalances monthly at most.
    """

    brokerage_flat: float = 20.0  # per executed order, capped at brokerage_pct (VERIFY)
    brokerage_pct: float = 0.025
    stt_sell: float = 0.00001  # equity ETF units: 0.001% on sale (VERIFY)
    stt_buy: float = 0.0
    stamp_buy: float = 0.00015
    exchange_txn: float = 0.0000297  # NSE
    sebi_fee: float = 0.000001
    gst: float = 0.18  # on brokerage + exchange + SEBI fees
    dp_charge_sell: float = 15.93  # incl. GST, per scrip per day (VERIFY with broker)
    half_spread_bps: float = 5.0

    def cost(
        self, notional: float, side: Side, *, maker: bool = False, shares: float = 0.0
    ) -> float:
        n = abs(notional)
        if n == 0:
            return 0.0
        brokerage = min(self.brokerage_flat, n * self.brokerage_pct)
        exch = n * self.exchange_txn
        sebi = n * self.sebi_fee
        gst = (brokerage + exch + sebi) * self.gst
        if side is Side.BUY:
            taxes = n * (self.stt_buy + self.stamp_buy)
            dp = 0.0
        else:
            taxes = n * self.stt_sell
            dp = self.dp_charge_sell
        spread = n * self.half_spread_bps / 10_000
        return brokerage + exch + sebi + gst + taxes + dp + spread

    def round_trip_bps(self, notional: float) -> float:
        return _rt_bps(self, notional)


def cost_model_for(venue: str) -> CostModel:
    """Default model per venue. Fees from config/venues/*.yaml base tiers."""
    match venue:
        case "binance":
            return BpsCost(maker_bps=10, taker_bps=10, half_spread_bps=0.5, slippage_bps=1.0)
        case "binance_perp":
            return BpsCost(maker_bps=2, taker_bps=5, half_spread_bps=0.5, slippage_bps=1.0)
        case "hyperliquid":
            return BpsCost(maker_bps=1.5, taker_bps=4.5, half_spread_bps=1.0, slippage_bps=1.5)
        case "delta_india":
            # 18% GST on fees
            return BpsCost(
                maker_bps=2 * 1.18, taker_bps=5 * 1.18, half_spread_bps=2, slippage_bps=2
            )
        case "ibkr":
            return IbkrPerShareCost()
        case "upstox":
            return IndiaDeliveryCost()
        case _:
            raise KeyError(f"no cost model for venue '{venue}'")
