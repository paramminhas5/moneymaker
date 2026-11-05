"""Account and sleeve drawdown monitors, plus a per-venue order rate limiter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from mm.config.models import AccountLimits


class LimitAction(StrEnum):
    NONE = "none"
    HALT_ENTRIES = "halt_entries"  # daily loss limit: no new risk until next UTC day
    FLATTEN_ALL = "flatten_all"  # max drawdown: close everything, human restart only


@dataclass(slots=True)
class DrawdownMonitor:
    """Feed it equity marks; it says what the account must do."""

    limits: AccountLimits
    peak: Decimal = Decimal("0")
    day: date | None = None
    day_open: Decimal = Decimal("0")

    def update(self, equity: Decimal, ts: datetime) -> LimitAction:
        if equity <= 0:
            return LimitAction.FLATTEN_ALL
        if self.day != ts.date():
            self.day = ts.date()
            self.day_open = equity
        self.peak = max(self.peak, equity)

        drawdown_pct = (self.peak - equity) / self.peak * 100
        if drawdown_pct >= self.limits.max_drawdown_pct:
            return LimitAction.FLATTEN_ALL
        daily_loss_pct = (self.day_open - equity) / self.day_open * 100
        if daily_loss_pct >= self.limits.max_daily_loss_pct:
            return LimitAction.HALT_ENTRIES
        return LimitAction.NONE


@dataclass(slots=True)
class TokenBucket:
    """Order rate limiter. `clock` returns seconds; inject a fake one in tests."""

    rate_per_second: float
    capacity: float
    clock: Callable[[], float]
    tokens: float = field(init=False)
    last: float = field(init=False)

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0 or self.capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self.tokens = self.capacity
        self.last = self.clock()

    def try_acquire(self, n: float = 1.0) -> bool:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate_per_second)
        self.last = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False
