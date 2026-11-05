"""Noise-area intraday momentum (synthetic data only) and the theme-call tracker."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from mm.research.intraday_noise import NoiseConfig, SyntheticMinuteSource, _sigma_table, backtest
from mm.research.theme_calls import ThemeCall, add_call, load_calls, score, summary


def _bars(momentum: float, seed: int = 0) -> pl.DataFrame:
    return SyntheticMinuteSource(seed=seed, momentum=momentum).bars(
        "SPY", date(2024, 1, 1), date(2024, 3, 31)
    )


def test_sigma_uses_only_previous_days() -> None:
    bars = _bars(0.0)
    full = _sigma_table(bars, 14)
    days = sorted(bars["day"].unique().to_list())
    cut = days[30]
    part = _sigma_table(bars.filter(pl.col("day") <= cut), 14)
    a = full.filter(pl.col("day") <= cut).sort("day", "tau")["sigma"]
    b = part.sort("day", "tau")["sigma"]
    assert a.equals(b)
    assert full.filter(pl.col("day") == days[5])["sigma"].null_count() > 0  # warm-up


def test_noise_area_profits_with_momentum_and_pays_costs_without() -> None:
    trend = backtest(_bars(0.00015, seed=1))
    noise = backtest(_bars(0.0, seed=1))
    assert trend.height > 30
    assert noise.height > 30
    assert trend["ret"].sum() > noise["ret"].sum()
    assert (noise["costs"] >= 0).all()
    assert int(trend["trades"].max()) <= 2 * 13 + 1  # type: ignore[arg-type]  # at most one change per decision + close


def test_noise_area_is_flat_overnight_and_respects_leverage_cap() -> None:
    res = backtest(_bars(0.0002, seed=2), NoiseConfig(max_leverage=1.0))
    assert (res["avg_exposure"] <= 1.0 + 1e-9).all()


# --- theme tracker -----------------------------------------------------------------------------


def _px(start: float, step: float, n: int = 40) -> pl.DataFrame:
    ts = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)]
    return pl.DataFrame({"ts": ts, "adj_close": [start + step * i for i in range(n)]})


def test_theme_ledger_roundtrip_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "calls.csv"
    add_call(ThemeCall(date(2026, 1, 5), "smh", "AI capex keeps going"), path)
    add_call(ThemeCall(date(2026, 1, 6), "URA", "nuclear restarts", 30), path)
    calls = load_calls(path)
    assert [c.ticker for c in calls] == ["SMH", "URA"]
    assert calls[1].horizon_days == 30
    with pytest.raises(ValueError):
        add_call(ThemeCall(date(2999, 1, 1), "X", "future"), path)


def test_theme_score_enters_after_call_date_and_compares_to_qqq() -> None:
    prices = {"QQQ": _px(100, 1), "SMH": _px(100, 2), "NEW": _px(10, 0, n=1)}
    calls = [ThemeCall(date(2026, 1, 5), "SMH", "t", 10),
             ThemeCall(date(2026, 2, 20), "NEW", "t")]  # fmt: skip
    out = score(calls, lambda s: prices[s], today=date(2026, 3, 1))
    smh = out.row(0, named=True)
    assert smh["entry"] == date(2026, 1, 6)
    assert smh["status"] == "closed"
    assert smh["exit"] == date(2026, 1, 15)
    assert smh["ret"] == pytest.approx((100 + 2 * 14) / (100 + 2 * 5) - 1)
    assert smh["qqq"] == pytest.approx((100 + 14) / (100 + 5) - 1)
    assert out.row(1, named=True)["status"] == "pending"
    s = summary(out)
    assert s["scored"] == 1
    assert s["hit_rate_vs_qqq"] == 1.0
