"""Domain types. Money and quantities are Decimal; time is timezone-aware UTC."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


class Product(StrEnum):
    """What kind of instrument this is. Jurisdiction profiles grant permissions per product."""

    SPOT = "spot"
    PERP = "perps"
    STOCK = "stocks"
    ETF = "etfs"
    OPTION = "options"
    FUTURE = "futures"
    PREDICTION = "prediction"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    POST_ONLY = "post_only"
    DAY = "day"


class Stage(StrEnum):
    """Promotion stages from SPEC.md section 6. Order matters."""

    RESEARCH = "research"
    PAPER = "paper"
    MICRO = "micro"
    LIVE = "live"

    @property
    def rank(self) -> int:
        return list(Stage).index(self)

    @property
    def moves_real_money(self) -> bool:
        return self in (Stage.MICRO, Stage.LIVE)


class Mode(StrEnum):
    """What the running process is allowed to touch."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Instrument:
    venue: str
    symbol: str
    product: Product
    base: str
    quote: str
    min_notional: Decimal = Decimal("0")
    lot_size: Decimal = Decimal("0")
    tick_size: Decimal = Decimal("0")

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.symbol}"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """What a strategy wants to do. Becomes an order only after pre-trade risk approves it."""

    strategy_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    order_type: OrderType = OrderType.LIMIT
    limit_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive; use side for direction")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders need a limit_price")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive")

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.side is Side.BUY else -self.quantity


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: str
    strategy_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    ts: datetime


@dataclass(frozen=True, slots=True)
class Position:
    instrument: Instrument
    quantity: Decimal  # signed: + long, - short
    avg_price: Decimal

    def notional(self, mark: Decimal) -> Decimal:
        return abs(self.quantity) * mark


@dataclass(frozen=True, slots=True)
class BookTop:
    """Minimal market snapshot pre-trade checks need."""

    bid: Decimal
    ask: Decimal
    bid_depth_qty: Decimal  # quantity resting within the check band on the bid side
    ask_depth_qty: Decimal
    ts: datetime = field(default_factory=utcnow)

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2
