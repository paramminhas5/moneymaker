from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from mm.config import RiskConfig, Settings, load_settings
from mm.core.types import Product

from .conftest import CONFIG_DIR


def test_real_config_loads(base_settings: Settings) -> None:
    assert base_settings.jurisdiction.active in base_settings.jurisdictions
    assert {"uae", "singapore", "thailand", "india"} <= set(base_settings.jurisdictions)
    assert "hyperliquid" in base_settings.venues


def test_full_kelly_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RiskConfig.model_validate({"kelly_fraction_cap": 1.0})


def test_unknown_keys_fail_loudly() -> None:
    with pytest.raises(ValidationError):
        RiskConfig.model_validate({"acount": {}})  # typo


def test_active_jurisdiction_must_exist(tmp_path: Path) -> None:
    root = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, root)
    (root / "base.yaml").write_text("jurisdiction:\n  active: atlantis\n")
    with pytest.raises(ValidationError, match="atlantis"):
        load_settings(root)


def test_profile_name_must_match_file(tmp_path: Path) -> None:
    root = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, root)
    (root / "jurisdictions" / "uae.yaml").write_text("name: dubai\n")
    with pytest.raises(ValueError, match="must match file name"):
        load_settings(root)


def test_known_facts_encoded_in_profiles(base_settings: Settings) -> None:
    j = base_settings.jurisdictions
    # Polymarket close-only for SG and TH, blocked in India: no profile trades it yet.
    for name in ("uae", "singapore", "thailand", "india"):
        assert not j[name].can_trade("polymarket", Product.PREDICTION)
    assert not j["india"].can_read("polymarket")
    # Binance.com does not serve Singapore.
    assert not j["singapore"].can_trade("binance", Product.SPOT)
    assert j["uae"].can_trade("binance", Product.SPOT)
    # Thai SEC blocked Bybit and OKX.
    assert not j["thailand"].can_read("bybit")
    # NRI profiles have no intraday equity.
    for name in ("uae", "singapore", "thailand"):
        assert j[name].permission("upstox").intraday_equity is False
    # Leverage stays at 1x everywhere in v1.
    assert all(p.max_leverage == Decimal("1.0") for p in j.values())
