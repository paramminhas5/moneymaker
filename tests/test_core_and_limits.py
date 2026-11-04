from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mm.config.models import AccountLimits
from mm.core.types import Instrument, OrderIntent, OrderType, Product, Side, Stage
from mm.risk.limits import DrawdownMonitor, LimitAction, TokenBucket

INST = Instrument(venue="hyperliquid", symbol="ETH", product=Product.PERP, base="ETH", quote="USD")


def test_order_intent_validation() -> None:
    with pytest.raises(ValueError, match="positive"):
        OrderIntent(
            strategy_id="s",
            instrument=INST,
            side=Side.BUY,
            quantity=Decimal("0"),
            limit_price=Decimal("1"),
        )
    with pytest.raises(ValueError, match="limit_price"):
        OrderIntent(strategy_id="s", instrument=INST, side=Side.BUY, quantity=Decimal("1"))
    o = OrderIntent(
        strategy_id="s",
        instrument=INST,
        side=Side.SELL,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
    )
    assert o.signed_quantity == Decimal("-2")


def test_stage_ordering() -> None:
    assert Stage.RESEARCH.rank < Stage.PAPER.rank < Stage.MICRO.rank < Stage.LIVE.rank
    assert not Stage.PAPER.moves_real_money
    assert Stage.MICRO.moves_real_money


T0 = datetime(2026, 11, 5, tzinfo=UTC)


def test_drawdown_monitor_daily_and_peak() -> None:
    m = DrawdownMonitor(AccountLimits())
    assert m.update(Decimal("100"), T0) is LimitAction.NONE
    assert m.update(Decimal("96.9"), T0 + timedelta(hours=1)) is LimitAction.HALT_ENTRIES
    # new day resets the daily baseline
    assert m.update(Decimal("96"), T0 + timedelta(days=1)) is LimitAction.NONE
    assert m.update(Decimal("80"), T0 + timedelta(days=2)) is LimitAction.FLATTEN_ALL
    assert m.update(Decimal("0"), T0 + timedelta(days=3)) is LimitAction.FLATTEN_ALL


@given(st.lists(st.decimals(min_value=1, max_value=10_000, places=2), min_size=1, max_size=50))
def test_drawdown_never_flattens_while_at_peak(values: list[Decimal]) -> None:
    m = DrawdownMonitor(AccountLimits())
    running_max = Decimal("0")
    for i, v in enumerate(values):
        action = m.update(v, T0 + timedelta(days=i))
        running_max = max(running_max, v)
        if v == running_max:
            assert action is LimitAction.NONE


def test_token_bucket() -> None:
    now = [0.0]
    bucket = TokenBucket(rate_per_second=2, capacity=2, clock=lambda: now[0])
    assert bucket.try_acquire()
    assert bucket.try_acquire()
    assert not bucket.try_acquire()
    now[0] = 0.5
    assert bucket.try_acquire()
    assert not bucket.try_acquire()
