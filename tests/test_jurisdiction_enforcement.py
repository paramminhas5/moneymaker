"""SPEC requirement: pre-trade risk rejects any venue or instrument the active profile disallows."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mm.config import Settings
from mm.core.types import BookTop, Instrument, OrderIntent, Product, Side
from mm.risk.pretrade import check_order

from .conftest import make_ctx, settings_for

VENUES = [
    "binance",
    "hyperliquid",
    "delta_india",
    "ibkr",
    "alpaca",
    "upstox",
    "polymarket",
    "bybit",
    "okx",
    "unknown_dex",
]
BOOK = BookTop(
    bid=Decimal("99.9"),
    ask=Decimal("100.1"),
    bid_depth_qty=Decimal("1000"),
    ask_depth_qty=Decimal("1000"),
)


@pytest.mark.parametrize("jurisdiction", ["uae", "singapore", "thailand", "india"])
@pytest.mark.parametrize("venue", VENUES)
@pytest.mark.parametrize("product", list(Product))
def test_every_disallowed_combination_is_rejected(
    base_settings: Settings, jurisdiction: str, venue: str, product: Product
) -> None:
    settings = settings_for(base_settings, jurisdiction)
    profile = settings.active_jurisdiction
    inst = Instrument(venue=venue, symbol="X", product=product, base="X", quote="USD")
    intent = OrderIntent(
        strategy_id="t",
        instrument=inst,
        side=Side.BUY,
        quantity=Decimal("0.2"),
        limit_price=Decimal("100"),
    )
    decision = check_order(intent, make_ctx(settings, book=BOOK))
    jurisdiction_reasons = [r for r in decision.reasons if "jurisdiction" in r]
    if profile.can_trade(venue, product):
        assert not jurisdiction_reasons
    else:
        assert not decision.approved
        assert jurisdiction_reasons, f"{jurisdiction}/{venue}/{product} slipped through"


def test_allowed_combination_passes_end_to_end(uae: Settings, btc_hl: Instrument) -> None:
    book = BookTop(
        bid=Decimal("100000"),
        ask=Decimal("100010"),
        bid_depth_qty=Decimal("50"),
        ask_depth_qty=Decimal("50"),
    )
    intent = OrderIntent(
        strategy_id="s1",
        instrument=btc_hl,
        side=Side.BUY,
        quantity=Decimal("0.0005"),
        limit_price=Decimal("100005"),
    )
    decision = check_order(intent, make_ctx(uae, book=book))
    assert decision.approved, decision.reasons
