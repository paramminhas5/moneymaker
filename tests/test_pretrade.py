from __future__ import annotations

from decimal import Decimal

from mm.config import Settings
from mm.core.types import BookTop, Instrument, Mode, OrderIntent, OrderType, Side, Stage
from mm.risk.pretrade import check_order

from .conftest import make_ctx


def buy(
    inst: Instrument,
    qty: str = "0.0005",
    price: str | None = "100005",
    *,
    reduce_only: bool = False,
) -> OrderIntent:
    order_type = OrderType.LIMIT if price is not None else OrderType.MARKET
    return OrderIntent(
        strategy_id="s1",
        instrument=inst,
        side=Side.BUY,
        quantity=Decimal(qty),
        order_type=order_type,
        limit_price=Decimal(price) if price else None,
        reduce_only=reduce_only,
    )


def reasons(intent: OrderIntent, uae: Settings, **ctx: object) -> str:
    return " | ".join(check_order(intent, make_ctx(uae, **ctx)).reasons)


def test_kill_switch_blocks_new_risk_but_allows_exits(
    uae: Settings, btc_hl: Instrument, book: BookTop
) -> None:
    assert "kill switch" in reasons(buy(btc_hl), uae, book=book, halted=True)
    exit_order = OrderIntent(
        strategy_id="s1",
        instrument=btc_hl,
        side=Side.SELL,
        quantity=Decimal("0.0005"),
        limit_price=Decimal("100000"),
        reduce_only=True,
    )
    ctx = make_ctx(uae, book=book, halted=True, positions={btc_hl.key: Decimal("0.0005")})
    assert check_order(exit_order, ctx).approved


def test_paused_strategy(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    assert "paused" in reasons(buy(btc_hl), uae, book=book, paused_strategies=frozenset({"s1"}))


def test_research_stage_never_trades_live_or_paper(
    uae: Settings, btc_hl: Instrument, book: BookTop
) -> None:
    r = reasons(buy(btc_hl), uae, book=book, mode=Mode.LIVE, strategy_stage=Stage.PAPER)
    assert "promotion needs human approval" in r
    r = reasons(buy(btc_hl), uae, book=book, mode=Mode.PAPER, strategy_stage=Stage.RESEARCH)
    assert "backtest mode" in r
    assert check_order(
        buy(btc_hl), make_ctx(uae, book=book, mode=Mode.BACKTEST, strategy_stage=Stage.RESEARCH)
    ).approved


def test_fat_finger_price_band(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    assert "fat-finger" in reasons(buy(btc_hl, price="110000"), uae, book=book)


def test_max_order_notional(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    # 0.001 BTC at ~100k = $100 > $60 cap
    assert "exceeds max $60" in reasons(
        buy(btc_hl, qty="0.001"), uae, book=book, equity_usd=Decimal("10000")
    )


def test_venue_minimum(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    # Hyperliquid minimum is $10; 0.00005 BTC is ~$5
    assert "below venue minimum" in reasons(buy(btc_hl, qty="0.00005"), uae, book=book)


def test_leverage_cap(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    r = reasons(
        buy(btc_hl), uae, book=book, equity_usd=Decimal("100"), gross_exposure_usd=Decimal("80")
    )
    assert "gross leverage" in r


def test_position_cap(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    r = reasons(
        buy(btc_hl),
        uae,
        book=book,
        equity_usd=Decimal("10000"),
        positions={btc_hl.key: Decimal("0.001")},
    )
    assert "resulting position" in r


def test_exit_feasibility(uae: Settings, btc_hl: Instrument) -> None:
    thin = BookTop(
        bid=Decimal("100000"),
        ask=Decimal("100010"),
        bid_depth_qty=Decimal("0.005"),
        ask_depth_qty=Decimal("50"),
    )
    assert "exit-feasibility" in reasons(buy(btc_hl), uae, book=thin)


def test_no_book_outside_backtest_is_rejected(uae: Settings, btc_hl: Instrument) -> None:
    assert "cannot confirm the position can be exited" in reasons(buy(btc_hl), uae)


def test_market_order_without_snapshot(uae: Settings, btc_hl: Instrument) -> None:
    assert "cannot size-check" in reasons(buy(btc_hl, price=None), uae)


def test_reduce_only_must_reduce(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    intent = buy(btc_hl, reduce_only=True)
    assert "would not reduce" in reasons(intent, uae, book=book)


def test_all_reasons_reported_together(uae: Settings, btc_hl: Instrument, book: BookTop) -> None:
    decision = check_order(
        buy(btc_hl, qty="0.01", price="120000"), make_ctx(uae, book=book, halted=True)
    )
    assert len(decision.reasons) >= 3
