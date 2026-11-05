"""Pre-trade risk checks. Every order intent passes through `check_order` before execution.

Each check returns a reason string when it rejects. All failing reasons are collected so the
log shows everything wrong with an order, not just the first problem.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from mm.config.models import Settings
from mm.core.types import BookTop, Mode, OrderIntent, Side, Stage


@dataclass(frozen=True, slots=True)
class PreTradeContext:
    settings: Settings
    mode: Mode
    strategy_stage: Stage
    equity_usd: Decimal
    gross_exposure_usd: Decimal
    positions: Mapping[str, Decimal] = field(default_factory=dict[str, Decimal])  # signed qty
    book: BookTop | None = None
    halted: bool = False
    paused_strategies: frozenset[str] = frozenset()
    quote_to_usd: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.approved


Check = Callable[[OrderIntent, PreTradeContext], str | None]


def _reference_price(intent: OrderIntent, ctx: PreTradeContext) -> Decimal | None:
    if intent.limit_price is not None:
        return intent.limit_price
    if ctx.book is not None:
        return ctx.book.ask if intent.side is Side.BUY else ctx.book.bid
    return None


def _notional_usd(intent: OrderIntent, ctx: PreTradeContext) -> Decimal | None:
    price = _reference_price(intent, ctx)
    if price is None:
        return None
    return intent.quantity * price * ctx.quote_to_usd


def _current_qty(intent: OrderIntent, ctx: PreTradeContext) -> Decimal:
    return ctx.positions.get(intent.instrument.key, Decimal("0"))


def _reduces_position(intent: OrderIntent, ctx: PreTradeContext) -> bool:
    current = _current_qty(intent, ctx)
    after = current + intent.signed_quantity
    return (
        current != 0 and abs(after) <= abs(current) and (after == 0 or (after > 0) == (current > 0))
    )


def check_kill_switch(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if ctx.halted and not _reduces_position(intent, ctx):
        return "kill switch is engaged: only position-reducing orders are allowed"
    return None


def check_paused(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if intent.strategy_id in ctx.paused_strategies and not _reduces_position(intent, ctx):
        return f"strategy '{intent.strategy_id}' is paused"
    return None


def check_stage_vs_mode(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if ctx.mode is Mode.LIVE and not ctx.strategy_stage.moves_real_money:
        return (
            f"strategy stage '{ctx.strategy_stage}' cannot trade live; "
            "promotion needs human approval via `mm promote`"
        )
    if ctx.mode is Mode.PAPER and ctx.strategy_stage.rank < Stage.PAPER.rank:
        return "research-stage strategies may only run in backtest mode"
    return None


def check_jurisdiction(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    profile = ctx.settings.active_jurisdiction
    inst = intent.instrument
    if not profile.can_trade(inst.venue, inst.product):
        return f"jurisdiction '{profile.name}' does not allow {inst.product} on {inst.venue}"
    return None


def check_venue_known(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if intent.instrument.venue not in ctx.settings.venues:
        return f"venue '{intent.instrument.venue}' has no config in config/venues/"
    return None


def check_price_available(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if _reference_price(intent, ctx) is None:
        return "no limit price and no market snapshot: cannot size-check the order"
    return None


def check_price_band(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if intent.limit_price is None or ctx.book is None:
        return None
    mid = ctx.book.mid
    if mid <= 0:
        return "market snapshot has a non-positive mid price"
    band = ctx.settings.risk.orders.price_band_pct / Decimal("100")
    if abs(intent.limit_price - mid) / mid > band:
        return (
            f"limit {intent.limit_price} is more than {band:.2%} from mid {mid} (fat-finger guard)"
        )
    return None


def check_min_notional(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    notional = _notional_usd(intent, ctx)
    venue = ctx.settings.venues.get(intent.instrument.venue)
    if notional is None or venue is None:
        return None
    floor = max(venue.min_notional_usd, intent.instrument.min_notional * ctx.quote_to_usd)
    if notional < floor and not intent.reduce_only:
        return f"order notional ${notional:.2f} is below venue minimum ${floor:.2f}"
    return None


def check_max_order(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    notional = _notional_usd(intent, ctx)
    cap = ctx.settings.risk.orders.max_order_notional_usd
    if notional is not None and notional > cap:
        return f"order notional ${notional:.2f} exceeds max ${cap}"
    return None


def check_max_position(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    price = _reference_price(intent, ctx)
    if price is None or _reduces_position(intent, ctx):
        return None
    after = abs(_current_qty(intent, ctx) + intent.signed_quantity) * price * ctx.quote_to_usd
    cap = ctx.settings.risk.orders.max_position_notional_usd
    if after > cap:
        return f"resulting position ${after:.2f} exceeds max ${cap}"
    return None


def check_leverage(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    notional = _notional_usd(intent, ctx)
    if notional is None or _reduces_position(intent, ctx):
        return None
    if ctx.equity_usd <= 0:
        return "equity is zero or negative"
    limit = min(
        ctx.settings.active_jurisdiction.max_leverage,
        ctx.settings.risk.account.max_gross_leverage,
    )
    after = (ctx.gross_exposure_usd + notional) / ctx.equity_usd
    if after > limit:
        return f"gross leverage would be {after:.2f}x, limit is {limit}x"
    return None


def check_exit_feasibility(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if _reduces_position(intent, ctx):
        return None
    if ctx.book is None:
        if ctx.mode is Mode.BACKTEST:
            return None
        return "no order book snapshot: cannot confirm the position can be exited"
    # To exit a long we sell into bids; to exit a short we buy from asks.
    exit_depth = ctx.book.bid_depth_qty if intent.side is Side.BUY else ctx.book.ask_depth_qty
    need = intent.quantity * ctx.settings.risk.orders.exit_depth_multiple
    if exit_depth < need:
        return f"exit side depth {exit_depth} is under {need} (exit-feasibility guard)"
    return None


def check_reduce_only(intent: OrderIntent, ctx: PreTradeContext) -> str | None:
    if intent.reduce_only and not _reduces_position(intent, ctx):
        return "reduce_only order would not reduce the current position"
    return None


DEFAULT_CHECKS: tuple[Check, ...] = (
    check_kill_switch,
    check_paused,
    check_stage_vs_mode,
    check_jurisdiction,
    check_venue_known,
    check_price_available,
    check_price_band,
    check_min_notional,
    check_max_order,
    check_max_position,
    check_leverage,
    check_exit_feasibility,
    check_reduce_only,
)


def check_order(
    intent: OrderIntent,
    ctx: PreTradeContext,
    checks: tuple[Check, ...] = DEFAULT_CHECKS,
) -> RiskDecision:
    reasons = tuple(r for check in checks if (r := check(intent, ctx)) is not None)
    return RiskDecision(approved=not reasons, reasons=reasons)
