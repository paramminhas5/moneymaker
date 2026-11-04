from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from mm.config import Settings, load_settings
from mm.core.types import BookTop, Instrument, Mode, Product, Stage
from mm.db.session import init_db, make_engine
from mm.risk.pretrade import PreTradeContext

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="session")
def base_settings() -> Settings:
    return load_settings(CONFIG_DIR)


def settings_for(base: Settings, jurisdiction: str) -> Settings:
    return base.model_copy(
        update={"jurisdiction": base.jurisdiction.model_copy(update={"active": jurisdiction})}
    )


@pytest.fixture
def uae(base_settings: Settings) -> Settings:
    return settings_for(base_settings, "uae")


@pytest.fixture
def btc_hl() -> Instrument:
    return Instrument(
        venue="hyperliquid", symbol="BTC-PERP", product=Product.PERP, base="BTC", quote="USD"
    )


@pytest.fixture
def book() -> BookTop:
    return BookTop(
        bid=Decimal("100000"),
        ask=Decimal("100010"),
        bid_depth_qty=Decimal("50"),
        ask_depth_qty=Decimal("50"),
    )


def make_ctx(settings: Settings, **overrides: object) -> PreTradeContext:
    defaults: dict[str, object] = {
        "settings": settings,
        "mode": Mode.PAPER,
        "strategy_stage": Stage.PAPER,
        "equity_usd": Decimal("115"),
        "gross_exposure_usd": Decimal("0"),
    }
    defaults.update(overrides)
    return PreTradeContext(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(eng)
    return eng
