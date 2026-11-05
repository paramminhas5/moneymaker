"""Core hold, BTC dip-buy and listing fade: rules, no-lookahead and cost wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from mm.data.clean import drop_reversal_spikes, weekday_calendar
from mm.research.backtest import run_weights
from mm.research.lookahead import assert_no_lookahead
from mm.strategies import btc_dipbuy, core_hold, get, listing_fade
from mm.strategies.common import hold_between_rebalances


def _days(n: int, start: datetime | None = None, weekdays: bool = False) -> list[datetime]:
    d = start or datetime(2020, 1, 1, tzinfo=UTC)
    out: list[datetime] = []
    while len(out) < n:
        if not weekdays or d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _walk(n: int, seed: int, drift: float = 0.0004, vol: float = 0.02) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(drift, vol, n))))


# --- data helpers ------------------------------------------------------------------------------


def test_drop_reversal_spikes_removes_single_bad_print_only() -> None:
    df = pl.DataFrame({"ts": _days(6), "adj_close": [100.0, 101, 10.1, 102, 140, 141]})
    out = drop_reversal_spikes(df, "adj_close", 0.25)
    assert out["adj_close"].to_list() == [100.0, 101, 102, 140, 141]  # real +37% jump kept


def test_weekday_calendar_rolls_weekend_into_monday() -> None:
    ts = _days(10, datetime(2024, 1, 1, tzinfo=UTC))  # Mon 1 Jan .. Wed 10 Jan
    close = pl.DataFrame({"ts": ts, "C": [float(i) for i in range(10)]}).with_columns(
        pl.col("ts").dt.cast_time_unit("ms")
    )
    out = weekday_calendar(close)
    assert out.height == 8
    assert out.filter(pl.col("ts").dt.day() == 8)["C"][0] == 7.0  # Monday's own close


def test_hold_between_rebalances_trades_only_on_rebalance_days() -> None:
    n = 30
    close = pl.DataFrame({"ts": _days(n), "A": _walk(n, 1), "B": _walk(n, 2)})
    target = close.select("ts").with_columns(pl.lit(0.5).alias("A"), pl.lit(0.3).alias("B"))
    reb = [i % 10 == 0 for i in range(n)]
    w = hold_between_rebalances(close, target, reb)
    res = run_weights(close, w, cost_bps=10.0)
    traded = np.flatnonzero(res.turnover > 1e-12)
    assert set(traded.tolist()) <= {i for i in range(n) if reb[i]}


# --- core hold ---------------------------------------------------------------------------------


def _core_close(n: int = 700) -> pl.DataFrame:
    ts = _days(n, datetime(2019, 1, 1, tzinfo=UTC), weekdays=True)
    cols: dict[str, list[float | None]] = {
        s: list(_walk(n, i, drift=0.0005)) for i, s in enumerate(core_hold.SLOTS)
    }
    cols["ETH-USD"] = [None] * 300 + cols["ETH-USD"][300:]  # listed later
    return pl.DataFrame({"ts": ts, **cols}).with_columns(pl.col("ts").dt.cast_time_unit("ms"))


def test_core_hold_slots_and_cash_before_listing() -> None:
    close = _core_close()
    w = core_hold.signal(close, dict(get("core_hold").base_params))
    assert (w["ETH-USD"][:300] == 0).all()
    gross = w.select(pl.sum_horizontal([c for c in w.columns if c != "ts"])).to_series()
    assert gross.max() <= 1.0 + 1e-9  # type: ignore[operator]
    month_end_rows = w.filter(pl.col("ACWI") > 0)
    assert month_end_rows.height > 0


def test_core_hold_filter_goes_to_cash_in_downtrend() -> None:
    n = 600
    ts = _days(n, datetime(2019, 1, 1, tzinfo=UTC), weekdays=True)
    down = list(np.linspace(200, 50, n))
    close = pl.DataFrame({"ts": ts, **{s: down for s in core_hold.SLOTS}}).with_columns(
        pl.col("ts").dt.cast_time_unit("ms")
    )
    w = core_hold.signal(close, dict(get("core_hold").base_params))
    assert w.drop("ts").to_numpy()[250:].sum() == 0.0


@pytest.mark.parametrize("check", ["monthly", "daily"])
def test_core_hold_no_lookahead(check: str) -> None:
    close = _core_close(500)
    params = dict(get("core_hold").base_params) | {"check": check}
    assert_no_lookahead(lambda d: core_hold.signal(d, params), close, n_cuts=6, min_rows=220)


def test_core_hold_buy_and_hold_variant_never_goes_to_cash() -> None:
    close = _core_close(400)
    params = dict(get("core_hold").base_params) | {"filter": False}
    w = core_hold.signal(close, params)
    assert float(w["QQQ"][-1]) > 0


# --- BTC dip-buy -------------------------------------------------------------------------------


def test_dipbuy_enters_after_dip_and_holds_n_days() -> None:
    px = [100.0, 100, 96, 97, 98, 99, 100, 100]  # -4% on day 2
    close = pl.DataFrame({"ts": _days(len(px)), "BTCUSDT": px})
    w = btc_dipbuy.signal(close, {"threshold": 0.03, "hold": 3, "trend_filter": False})
    assert w["BTCUSDT"].to_list() == [0, 0, 1, 1, 1, 0, 0, 0]


def test_dipbuy_trend_filter_blocks_dips_below_ma() -> None:
    px = [*np.linspace(200, 100, 260).tolist(), 95.0, 95.0]
    close = pl.DataFrame({"ts": _days(len(px)), "BTCUSDT": px})
    w = btc_dipbuy.signal(close, {"threshold": 0.03, "hold": 1, "trend_filter": True})
    assert w["BTCUSDT"].sum() == 0


def test_dipbuy_no_lookahead() -> None:
    close = pl.DataFrame({"ts": _days(400), "BTCUSDT": _walk(400, 3, vol=0.04)})
    for p in [
        {"threshold": 0.03, "hold": 3, "trend_filter": True},
        {"threshold": 0.05, "hold": 1, "trend_filter": False},
    ]:
        assert_no_lookahead(lambda d, p=p: btc_dipbuy.signal(d, p), close, n_cuts=6)


# --- listing fade ------------------------------------------------------------------------------


def _listing_close() -> pl.DataFrame:
    n = 80
    ts = _days(n)
    cols: dict[str, list[float | None]] = {}
    for k, start in enumerate([5, 6, 7, 8, 40]):  # 4 listings in a row, then one later
        path = _walk(n - start, 10 + k, drift=-0.01, vol=0.03)
        cols[f"C{k}USDT"] = [None] * start + path
    return pl.DataFrame({"ts": ts, **cols})


def test_listing_fade_caps_names_and_holds() -> None:
    close = _listing_close()
    p = {"delay": 1, "hold": 10, "stop": 10.0, "max_names": 3}
    w = listing_fade.signal(close, p)
    m = w.drop("ts").to_numpy()
    assert (m <= 0).all()
    assert (np.count_nonzero(m, axis=1) <= 3).all()
    assert m[:, 3].sum() == 0  # 4th simultaneous listing skipped
    assert np.count_nonzero(m[:, 0]) == 10  # held exactly `hold` days
    assert m[6, 0] == pytest.approx(-1 / 3)  # listed day 5, entered day 6
    assert m[41, 4] < 0  # later listing gets a slot


def test_listing_fade_stop_covers_on_squeeze() -> None:
    n = 30
    px: list[float | None] = [None, None] + [10.0, 10, 12, 16, 30, 31] + [31.0] * (n - 8)
    close = pl.DataFrame({"ts": _days(n), "SQZUSDT": px})
    w = listing_fade.signal(close, {"delay": 1, "hold": 20, "stop": 0.5, "max_names": 3})
    held = w["SQZUSDT"].to_list()
    assert held[3] < 0
    assert held[4] < 0
    assert held[5] == 0
    assert all(x == 0 for x in held[5:])


def test_listing_fade_no_lookahead_and_funding_sign() -> None:
    close = _listing_close()
    p = {"delay": 3, "hold": 14, "stop": 0.5, "max_names": 3}
    assert_no_lookahead(lambda d: listing_fade.signal(d, p), close, n_cuts=6, min_rows=10)
    w = listing_fade.signal(close, p)
    # Positive funding: longs pay, so a short earns it.
    fund = close.select("ts").with_columns([pl.lit(0.001).alias(c) for c in w.columns[1:]])
    flat = close.with_columns([pl.lit(1.0).alias(c) for c in w.columns[1:]])
    res = run_weights(flat, w, cost_bps=0.0, funding=fund)
    assert res.funding.sum() > 0


def test_new_strategies_are_registered_with_costs() -> None:
    for sid in ("core_hold", "btc_dipbuy", "listing_fade"):
        spec = get(sid)
        assert spec.cost_bps
        assert len(list(spec.sweep)) > 0


def test_listing_fade_intraday_stop_caps_the_squeeze_loss() -> None:
    from mm.research.listing_fade_stops import StopParams, simulate

    n = 10
    ts = _days(n)
    px: list[float | None] = [None, 10.0, 10, 10, 60, 60, 60, 60, 60, 60]  # +500% on day 4
    hi: list[float | None] = [None, 10.0, 10, 10, 65, 60, 60, 60, 60, 60]
    close = pl.DataFrame({"ts": ts, "X": px})
    high = pl.DataFrame({"ts": ts, "X": hi})
    zero = pl.DataFrame({"ts": ts, "X": [0.0] * n})
    p = StopParams(delay=1, hold=20, stop=0.5, max_names=1, slippage=0.1, cost_bps=0.0)
    r, trades, stops = simulate(close, high, close, zero, p)
    assert trades == 1
    assert stops == 1
    # Gap open at 60 > stop 15: filled at 60 * 1.1 = 66 vs prior close 10 -> -560%.
    assert r[4] == pytest.approx(-(66 / 10 - 1))
    p2 = StopParams(delay=1, hold=20, stop=0.5, max_names=1, slippage=0.1, cost_bps=0.0)
    opn = pl.DataFrame({"ts": ts, "X": [None, 10.0, 10, 10, 10, 60, 60, 60, 60, 60]})
    r2, _, _ = simulate(close, high, opn, zero, p2)
    assert r2[4] == pytest.approx(-(15 * 1.1 / 10 - 1))  # stop hit intraday: filled at 16.5
