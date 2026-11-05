from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from sqlalchemy import Engine

from mm.core.types import Side
from mm.costs import BpsCost, IbkrPerShareCost, IndiaDeliveryCost, cost_model_for
from mm.research.backtest import run_weights, wide
from mm.research.lookahead import LookaheadError, assert_no_lookahead
from mm.validation.experiments import ExperimentLog
from mm.validation.gates import evaluate_g0, evaluate_g1
from mm.validation.metrics import cagr, max_drawdown, sharpe, summarize
from mm.validation.pbo import pbo_cscv
from mm.validation.resample import bootstrap_ci
from mm.validation.sharpe_tests import (
    deflated_sharpe,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe,
)
from mm.validation.walkforward import make_folds, walk_forward_select

RNG = np.random.default_rng(42)


# Metrics --------------------------------------------------------------------------------
def test_basic_metrics() -> None:
    r = np.array([0.1, -0.5, 0.2])
    assert max_drawdown(r) == pytest.approx(0.5)
    assert cagr(np.full(365, 0.0), 365) == 0.0
    assert sharpe(np.zeros(10)) == 0.0
    assert cagr(np.full(365, (1.10) ** (1 / 365) - 1), 365) == pytest.approx(0.10, rel=1e-9)
    s = summarize(RNG.normal(0.001, 0.01, 1000))
    assert s.n == 1000
    assert 0 < s.hit_rate < 1


# PSR / DSR ------------------------------------------------------------------------------
def test_psr_is_half_at_benchmark() -> None:
    assert probabilistic_sharpe(0.1, 0.1, 500) == pytest.approx(0.5)
    assert probabilistic_sharpe(0.2, 0.0, 500) > 0.99


def test_expected_max_sharpe_matches_monte_carlo() -> None:
    sims = np.random.default_rng(0).standard_normal((20_000, 100)).max(axis=1).mean()
    assert expected_max_sharpe(100, 1.0) == pytest.approx(sims, abs=0.05)
    assert expected_max_sharpe(1, 1.0) == 0.0


def test_min_track_record_length_inverts_psr() -> None:
    n = min_track_record_length(0.1, 0.0, prob=0.95)
    assert probabilistic_sharpe(0.1, 0.0, round(n)) == pytest.approx(0.95, abs=0.005)


def test_dsr_punishes_the_best_of_many_noise_trials() -> None:
    rng = np.random.default_rng(1)
    trials = rng.normal(0, 0.01, (750, 200))
    srs = trials.mean(axis=0) / trials.std(axis=0, ddof=1)
    best = trials[:, int(np.argmax(srs))]
    assert deflated_sharpe(best, n_trials=200, trial_sharpes=srs) < 0.5
    assert deflated_sharpe(best, n_trials=1) > 0.8  # looks great if you hide the search


def test_dsr_accepts_a_real_edge() -> None:
    r = np.random.default_rng(2).normal(0.002, 0.01, 1500)  # SR ~3.8 annualised
    assert deflated_sharpe(r, n_trials=50) > 0.95


# PBO ------------------------------------------------------------------------------------
def test_pbo_noise_is_coin_flip() -> None:
    m = np.random.default_rng(3).normal(0, 0.01, (1600, 30))
    res = pbo_cscv(m, n_blocks=10)
    assert 0.25 < res.pbo < 0.75


def test_pbo_low_when_one_variant_has_edge() -> None:
    m = np.random.default_rng(4).normal(0, 0.01, (1600, 30))
    m[:, 7] += 0.003
    assert pbo_cscv(m, n_blocks=10).pbo < 0.05


def test_pbo_input_validation() -> None:
    with pytest.raises(ValueError, match="2 variants"):
        pbo_cscv(np.zeros((100, 1)))
    with pytest.raises(ValueError, match="even"):
        pbo_cscv(np.zeros((100, 3)), n_blocks=5)


# Walk-forward and bootstrap -------------------------------------------------------------
def test_folds_never_overlap_and_test_follows_train() -> None:
    folds = make_folds(1000, train=300, test=100, embargo=5)
    assert folds
    for f in folds:
        assert f.train_end + 5 == f.test_start
        assert f.test_end - f.test_start == 100
    for a, b in itertools.pairwise(folds):
        assert a.test_end <= b.test_start
    assert all(f.train_start == 0 for f in make_folds(1000, 300, 100, anchored=True))


def test_walk_forward_picks_the_real_edge() -> None:
    m = np.random.default_rng(5).normal(0, 0.01, (1200, 5))
    m[:, 2] += 0.002
    res = walk_forward_select(m, make_folds(1200, 300, 100))
    assert res.stability >= 0.8
    assert res.chosen.count(2) >= len(res.chosen) - 1
    assert res.oos_returns.size == 900


def test_bootstrap_is_seeded_and_brackets_estimate() -> None:
    r = np.random.default_rng(6).normal(0.001, 0.01, 800)
    a = bootstrap_ci(r, sharpe, n_boot=200, seed=1)
    b = bootstrap_ci(r, sharpe, n_boot=200, seed=1)
    assert a == b
    assert a[1] <= a[0] <= a[2]


# Costs ----------------------------------------------------------------------------------
def test_cost_models() -> None:
    crypto = BpsCost(maker_bps=2, taker_bps=5, half_spread_bps=1, slippage_bps=1)
    assert crypto.cost(1000, Side.BUY) == pytest.approx(0.7)
    assert crypto.cost(1000, Side.BUY, maker=True) == pytest.approx(0.2)
    assert IbkrPerShareCost().cost(115, Side.BUY, shares=0.2) >= 1.0  # $1 minimum bites
    india = IndiaDeliveryCost()
    rt = india.round_trip_bps(2000)  # a Rs 2,000 round trip
    assert rt > 100  # over 1%: fixed fees dominate at this size
    assert india.round_trip_bps(200_000) < 30
    assert cost_model_for("hyperliquid").round_trip_bps(1000) > 0
    with pytest.raises(KeyError):
        cost_model_for("nowhere")


# Backtester -----------------------------------------------------------------------------
def _ts(n: int) -> list[datetime]:
    return [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)]


def test_backtest_timing_and_costs() -> None:
    close = pl.DataFrame({"ts": _ts(4), "A": [100.0, 110.0, 121.0, 121.0]})
    weights = pl.DataFrame({"ts": _ts(4), "A": [1.0, 1.0, 0.0, 0.0]})
    res = run_weights(close, weights, cost_bps=10)
    # Day 0: buy at close (cost 10bp), day 1: +10%, day 2: +10% then sell (cost), day 3: flat
    assert res.gross.tolist() == pytest.approx([0.0, 0.10, 0.10, 0.0])
    assert res.costs[0] == pytest.approx(0.001)
    assert res.costs[2] == pytest.approx(0.001)
    assert res.net[1] == pytest.approx(0.10)


def test_backtest_weight_today_never_earns_today() -> None:
    close = pl.DataFrame({"ts": _ts(3), "A": [100.0, 200.0, 200.0]})
    late = pl.DataFrame({"ts": _ts(3), "A": [0.0, 1.0, 1.0]})  # signal arrives on the jump day
    assert run_weights(close, late, cost_bps=0).gross[1] == 0.0


def test_backtest_funding_sign_and_untradable_assets() -> None:
    close = pl.DataFrame({"ts": _ts(3), "P": [100.0, 100.0, 100.0], "X": [None, 50.0, 50.0]})
    weights = pl.DataFrame({"ts": _ts(3), "P": [-1.0, -1.0, -1.0], "X": [1.0, 0.0, 0.0]})
    funding = pl.DataFrame({"ts": _ts(3), "P": [0.0, 0.001, 0.001], "X": [0.0, 0.0, 0.0]})
    res = run_weights(close, weights, cost_bps=0, funding=funding)
    assert res.funding[1] == pytest.approx(0.001)  # short receives positive funding
    assert res.weights[0, 1] == 0.0  # X had no price on day 0, so it could not be held


def test_backtest_capital_aware_costs_bite_small_accounts() -> None:
    close = pl.DataFrame({"ts": _ts(30), "E": [100.0] * 30})
    flip = pl.DataFrame({"ts": _ts(30), "E": [1.0 if i % 2 == 0 else 0.0 for i in range(30)]})
    small = run_weights(close, flip, cost_model=IndiaDeliveryCost(), capital=2000)
    big = run_weights(close, flip, cost_model=IndiaDeliveryCost(), capital=2_000_000)
    assert small.net.sum() < big.net.sum() < 0


def test_wide_alignment() -> None:
    a = pl.DataFrame({"ts": _ts(3), "close": [1.0, 2.0, 3.0]})
    b = pl.DataFrame({"ts": _ts(4)[1:], "close": [5.0, 6.0, 7.0]})
    w = wide({"A": a, "B": b})
    assert w.height == 4
    assert w["A"].null_count() == 1


# Lookahead harness ----------------------------------------------------------------------
def test_lookahead_harness() -> None:
    data = pl.DataFrame(
        {"ts": _ts(300), "close": np.cumprod(1 + np.random.default_rng(8).normal(0, 0.02, 300))}
    )

    def causal(df: pl.DataFrame) -> pl.DataFrame:
        return df.select(
            "ts", (pl.col("close") > pl.col("close").rolling_mean(20)).cast(pl.Float64).alias("sig")
        )

    def leaky(df: pl.DataFrame) -> pl.DataFrame:
        return df.select(
            "ts", (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Float64).alias("sig")
        )

    def centred(df: pl.DataFrame) -> pl.DataFrame:  # subtle leak: centred window
        return df.select("ts", pl.col("close").rolling_mean(21, center=True).alias("sig"))

    assert_no_lookahead(causal, data)
    with pytest.raises(LookaheadError):
        assert_no_lookahead(leaky, data)
    with pytest.raises(LookaheadError):
        assert_no_lookahead(centred, data)


# Experiment log and gates -----------------------------------------------------------------
def test_experiment_log(engine: Engine) -> None:
    log = ExperimentLog(engine)
    for i in range(5):
        log.log(
            strategy_id="s1",
            family="s1_v1",
            params={"lb": i},
            data_snapshot="abc",
            metrics={"sharpe_per_period": 0.01 * i},
            commit="deadbeef",
        )
    assert log.n_trials("s1_v1") == 5
    assert log.trial_sharpes("s1_v1").tolist() == pytest.approx([0, 0.01, 0.02, 0.03, 0.04])
    assert log.n_trials("other") == 0


def test_g1_passes_a_strong_honest_strategy_and_fails_missing_evidence(tmp_path: Path) -> None:
    r = np.random.default_rng(9).normal(0.0015, 0.01, 1100)  # ~3 years, SR ~2.9
    m = np.random.default_rng(10).normal(0, 0.01, (1100, 8))
    m[:, 0] = r
    pbo = pbo_cscv(m, n_blocks=10)
    common = {
        "kind": "directional",
        "oos_returns": r,
        "n_trials": 8,
        "trial_sharpes": None,
        "pbo": pbo,
        "sleeve_max_dd": 0.35,
        "data_snapshot": "snap",
        "code_commit": "c",
    }
    good = evaluate_g1("demo", event_driven_gap=0.02, **common)  # type: ignore[arg-type]
    assert good.passed, good.to_markdown()
    missing = evaluate_g1("demo", event_driven_gap=None, **common)  # type: ignore[arg-type]
    assert not missing.passed
    assert "**FAIL**" in missing.to_markdown()
    path = good.save(tmp_path)
    assert path.exists()
    assert (tmp_path / "demo" / "G1_latest.md").exists()


def test_g1_fails_noise() -> None:
    r = np.random.default_rng(11).normal(0, 0.01, 1100)
    rep = evaluate_g1(
        "noise",
        kind="directional",
        oos_returns=r,
        n_trials=100,
        trial_sharpes=None,
        pbo=None,
        sleeve_max_dd=0.35,
        event_driven_gap=0.0,
        data_snapshot="s",
        code_commit="c",
    )
    assert not rep.passed


def test_g0() -> None:
    rep = evaluate_g0(
        "s",
        no_lookahead=True,
        tests_passed=True,
        cost_model=None,
        deterministic=True,
        data_snapshot="s",
        code_commit="c",
    )
    assert not rep.passed
