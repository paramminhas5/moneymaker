"""Dixon-Coles fit, point-in-time behaviour, season simulation, scoring and proposal queue."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mm.data.sources.football_data import parse_csv, season_code
from mm.research.football.dixon_coles import DCConfig, fit, simulate_season
from mm.research.football.evaluate import score, value_bets
from mm.research.football.proposals import ProposalQueue

TEAMS = ["Strong", "Mid1", "Mid2", "Mid3", "Weak"]
STRENGTH = {"Strong": 0.6, "Mid1": 0.1, "Mid2": 0.0, "Mid3": -0.1, "Weak": -0.6}


def _league(n_rounds: int = 30, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    d = date(2020, 1, 4)
    for _ in range(n_rounds):
        for h in TEAMS:
            for a in TEAMS:
                if h == a:
                    continue
                lam = np.exp(0.25 + STRENGTH[h] - STRENGTH[a] * 0.5)
                mu = np.exp(STRENGTH[a] - STRENGTH[h] * 0.5)
                rows.append(
                    {
                        "date": d,
                        "home": h,
                        "away": a,
                        "hg": float(rng.poisson(lam)),
                        "ag": float(rng.poisson(mu)),
                    }
                )
        d += timedelta(days=7)
    return pl.DataFrame(rows)


def test_fit_recovers_team_ordering_and_home_advantage() -> None:
    m = fit(_league(), date(2021, 1, 1), DCConfig(xi=0.0, window_days=10_000))
    strength = {t: m.attack[i] + m.defence[i] for i, t in enumerate(m.teams)}
    assert strength["Strong"] > strength["Mid2"] > strength["Weak"]
    assert 0.1 < m.home < 0.4
    ph, pd_, pa = m.outcome_probs("Strong", "Weak")
    assert ph + pd_ + pa == pytest.approx(1.0)
    assert ph > 0.6


def test_fit_is_point_in_time() -> None:
    lg = _league()
    as_of = date(2020, 6, 1)
    a = fit(lg, as_of)
    future = lg.filter(pl.col("date") >= as_of).with_columns(pl.lit(9.0).alias("hg"))
    b = fit(pl.concat([lg.filter(pl.col("date") < as_of), future]), as_of)
    assert np.allclose(a.attack, b.attack)
    assert a.home == pytest.approx(b.home)


def test_unknown_team_gets_weak_prior() -> None:
    m = fit(_league(), date(2021, 1, 1))
    ph, _, _ = m.outcome_probs("Promoted FC", "Strong")
    assert ph < 0.4


def test_season_simulation_probabilities_are_consistent() -> None:
    lg = _league(8)
    m = fit(lg, date(2021, 1, 1))
    played = lg.head(6)
    sim = simulate_season(m, played, TEAMS, n_sims=2000, seed=1)
    assert sim["p_title"].sum() == pytest.approx(1.0)
    assert sim["p_top4"].sum() == pytest.approx(4.0)
    assert sim["p_bottom3"].sum() == pytest.approx(3.0)
    assert sim.filter(pl.col("team") == "Strong")["p_title"][0] > 0.4


def test_score_and_value_bets() -> None:
    pred = pl.DataFrame(
        {
            "date": [date(2024, 1, 1)] * 2,
            "div": ["E0"] * 2,
            "result": ["H", "A"],
            "m_H": [0.6, 0.2],
            "m_D": [0.2, 0.3],
            "m_A": [0.2, 0.5],
            "pc_H": [0.5, 0.3],
            "pc_D": [0.25, 0.3],
            "pc_A": [0.25, 0.4],
            "PSH": [2.0, 3.0],
            "PSD": [3.5, 3.4],
            "PSA": [4.0, 2.2],
            "PSCH": [1.9, 3.2],
            "PSCD": [3.6, 3.4],
            "PSCA": [4.1, 2.4],
        }
    )
    s = score(pred, "m")
    assert s.n == 2
    assert 0 < s.brier < 2
    assert s.log_loss > 0
    bets = value_bets(pred, edge=0.05)
    assert bets.height == 2
    first = bets.row(0, named=True)
    assert first["outcome"] == "H"
    assert first["won"]
    assert first["profit"] == pytest.approx(0.01)
    assert first["clv"] == pytest.approx(2.0 * 0.5 - 1)


def test_parse_csv_handles_bom_and_two_digit_years() -> None:
    raw = (
        "﻿Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,PSH,PSD,PSA\nE0,11/08/23,A,B,1,0,H,2.0,3.4,4.0\n"
    ).encode("latin-1", errors="ignore")
    df = parse_csv(raw, 2023, "E0")
    assert df["date"][0] == date(2023, 8, 11)
    assert df["div"][0] == "E0"
    assert season_code(2023) == "2324"


def test_proposal_queue_logs_clv_and_never_trades(tmp_path: Path) -> None:
    q = ProposalQueue(tmp_path / "q.jsonl")
    now = datetime(2026, 11, 5, tzinfo=UTC)
    assert (
        q.propose(market="m", match="x", outcome="H", model_prob=0.52, entry_price=0.50, now=now)
        is None
    )  # edge 2% < 3%
    p = q.propose(market="m", match="x", outcome="H", model_prob=0.60, entry_price=0.50, now=now)
    assert p is not None
    q.record_close(p.id, 0.55)
    q.settle(p.id, won=True)
    final = q.all()[0]
    assert final.status == "settled"
    assert final.clv == pytest.approx(0.05)
    assert final.pnl_per_share == pytest.approx(0.5)
    assert q.summary()["mean_clv"] == pytest.approx(0.05)
    assert not hasattr(q, "place_order")
