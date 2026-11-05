from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from sqlalchemy import Engine, select

from mm.config import Settings
from mm.core.types import BookTop
from mm.db.schema import FillRecord, OrderRecord
from mm.db.state import StateStore
from mm.execution import paper
from mm.execution.hyperliquid_md import CoinMeta
from mm.strategies import Spec

from .conftest import settings_for


class FakeMD:
    def __init__(self, px: dict[str, str]) -> None:
        self.px = {k: Decimal(v) for k, v in px.items()}

    def meta(self) -> dict[str, CoinMeta]:
        return {k: CoinMeta(k, 4) for k in self.px}

    def mids(self) -> dict[str, Decimal]:
        return dict(self.px)

    def book(self, coin: str, band: float = 0.005) -> BookTop:
        m = self.px[coin]
        return BookTop(
            bid=m * Decimal("0.9999"),
            ask=m * Decimal("1.0001"),
            bid_depth_qty=Decimal(1000),
            ask_depth_qty=Decimal(1000),
        )

    def funding_since(self, coin: str, start_ms: int) -> Decimal:
        return Decimal("0.0001")


def make_spec(weights: dict[str, float]) -> Spec:
    ts = [datetime(2026, 11, 1, tzinfo=UTC) + timedelta(days=i) for i in range(3)]
    close = pl.DataFrame({"ts": ts, **{s: [100.0] * 3 for s in weights}})

    def signal(c: pl.DataFrame, p: dict[str, object]) -> pl.DataFrame:
        return c.select("ts", *[pl.lit(w).alias(s) for s, w in weights.items()])

    return Spec(
        id="t_paper",
        kind="directional",
        family="t",
        venue="hyperliquid",
        periods_per_year=365,
        signal=signal,
        load_data=lambda: {"close": close},
        base_params={},
        sweep={},
    )


@pytest.fixture
def paper_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "strategies").mkdir()
    (tmp_path / "strategies" / "t_paper.yaml").write_text("stage: paper\n")
    monkeypatch.setattr(paper, "config_dir", lambda: tmp_path)


def test_research_stage_cannot_paper_trade(
    base_settings: Settings, engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paper, "config_dir", lambda: tmp_path)
    with pytest.raises(PermissionError):
        paper.run_paper(
            make_spec({"BTCUSDT": 0.1}),
            base_settings,
            engine,
            FakeMD({"BTC": "100000"}),
            capital=Decimal(1000),
        )


def test_paper_fills_fees_funding_and_rejections(
    base_settings: Settings, engine: Engine, paper_cfg: None
) -> None:
    sg = settings_for(base_settings, "singapore")
    md = FakeMD({"BTC": "100000", "ETH": "2500"})
    # 0.04 x $1000 = $40 BTC fills; 0.5 x $1000 = $500 ETH breaches the $60 order cap.
    spec = make_spec({"BTCUSDT": 0.04, "ETHUSDT": 0.5, "LUNAUSDT": 0.1})
    t0 = datetime(2026, 11, 5, tzinfo=UTC)
    rep = paper.run_paper(spec, sg, engine, md, capital=Decimal(1000), now=t0)
    assert len(rep.fills) == 1
    assert "BTC" in rep.fills[0]
    assert any("ETH" in r and "exceeds max" in r for r in rep.rejections)
    assert any("LUNA" in k for k in rep.skipped)
    assert rep.equity < Decimal(1000)  # paid spread + taker fee
    assert rep.equity > Decimal("999.9")
    with __import__("mm.db.session", fromlist=["session_scope"]).session_scope(engine) as s:
        assert len(s.scalars(select(FillRecord)).all()) == 1
        assert {o.status for o in s.scalars(select(OrderRecord)).all()} == {"filled", "rejected"}
    # Second run charges funding on the open BTC position.
    rep2 = paper.run_paper(
        spec,
        sg,
        engine,
        md,
        capital=Decimal(1000),
        now=t0 + timedelta(days=1),
    )
    assert rep2.funding_paid > 0


def test_kill_switch_blocks_paper_entries(
    base_settings: Settings, engine: Engine, paper_cfg: None
) -> None:
    StateStore(engine).engage_kill("drill", actor="human")
    rep = paper.run_paper(
        make_spec({"BTCUSDT": 0.04}),
        settings_for(base_settings, "singapore"),
        engine,
        FakeMD({"BTC": "100000"}),
        capital=Decimal(1000),
    )
    assert not rep.fills
    assert any("kill switch" in r for r in rep.rejections)
