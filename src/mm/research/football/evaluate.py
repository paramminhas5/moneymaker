"""Walk-forward evaluation of the Dixon-Coles model against bookmaker prices.

For each league, the model is refit every Monday on matches strictly before that Monday and
predicts that week's matches. Benchmarks: Pinnacle closing odds (sharpest public price; missing
after mid-2025), the market-average closing odds, and Pinnacle's earlier price (PSH/PSD/PSA,
collected days before kick-off). Probabilities from odds are de-vigged proportionally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import polars as pl

from mm.research.football.dixon_coles import DCConfig, DCModel, fit

OUTCOMES = ("H", "D", "A")


def devig(h: pl.Expr, d: pl.Expr, a: pl.Expr) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    s = 1 / h + 1 / d + 1 / a
    return (1 / h) / s, (1 / d) / s, (1 / a) / s


def predict_walkforward(matches: pl.DataFrame, config: DCConfig, first_season: int) -> pl.DataFrame:
    """Out-of-sample model probabilities for every match from `first_season` onward."""
    rows: list[dict[str, object]] = []
    for div in sorted(matches["div"].unique().to_list()):
        lg = matches.filter(pl.col("div") == div).sort("date")
        test = lg.filter(pl.col("season") >= first_season)
        if test.is_empty():
            continue
        weeks = test.with_columns(
            (pl.col("date") - pl.duration(days=pl.col("date").dt.weekday() - 1)).alias("wk")
        )
        model: DCModel | None = None
        for (wk,), grp in weeks.group_by(["wk"], maintain_order=True):
            assert isinstance(wk, date)
            try:
                model = fit(lg, wk, config, warm=model)
            except ValueError:
                continue
            for r in grp.iter_rows(named=True):
                ph, pd_, pa = model.outcome_probs(r["home"], r["away"])
                rows.append(
                    {
                        "div": div,
                        "season": r["season"],
                        "date": r["date"],
                        "home": r["home"],
                        "away": r["away"],
                        "result": r["result"],
                        "m_H": ph,
                        "m_D": pd_,
                        "m_A": pa,
                    }
                )
    pred = pl.DataFrame(rows)
    return pred.join(
        matches.select(
            "div",
            "date",
            "home",
            "away",
            "PSH",
            "PSD",
            "PSA",
            "PSCH",
            "PSCD",
            "PSCA",
            "AvgCH",
            "AvgCD",
            "AvgCA",
        ),
        on=["div", "date", "home", "away"],
        how="left",
    ).with_columns(
        *[
            e.alias(f"pc_{o}")
            for e, o in zip(
                devig(pl.col("PSCH"), pl.col("PSCD"), pl.col("PSCA")), OUTCOMES, strict=True
            )
        ],
        *[
            e.alias(f"ac_{o}")
            for e, o in zip(
                devig(pl.col("AvgCH"), pl.col("AvgCD"), pl.col("AvgCA")), OUTCOMES, strict=True
            )
        ],
        *[
            e.alias(f"pe_{o}")
            for e, o in zip(
                devig(pl.col("PSH"), pl.col("PSD"), pl.col("PSA")), OUTCOMES, strict=True
            )
        ],
    )


@dataclass(frozen=True, slots=True)
class Scores:
    n: int
    brier: float
    log_loss: float


def score(pred: pl.DataFrame, prefix: str) -> Scores:
    """Multi-class Brier (sum over H/D/A of squared error) and log loss for one forecaster."""
    df = pred.drop_nulls([f"{prefix}_{o}" for o in OUTCOMES])
    if df.is_empty():
        return Scores(0, float("nan"), float("nan"))
    p = df.select([f"{prefix}_{o}" for o in OUTCOMES]).to_numpy()
    y = np.stack([(df["result"] == o).to_numpy() for o in OUTCOMES], axis=1).astype(np.float64)
    brier = float(((p - y) ** 2).sum(axis=1).mean())
    ll = float(-np.log(np.clip((p * y).sum(axis=1), 1e-12, 1)).mean())
    return Scores(df.height, brier, ll)


def value_bets(pred: pl.DataFrame, edge: float, stake: float = 0.01) -> pl.DataFrame:
    """Hypothetical flat-stake bets at Pinnacle's early price where model EV exceeds `edge`.

    One bet per match at most (the outcome with the largest EV). Returns per-bet rows with
    profit (fraction of bankroll) and closing-line value: early odds / fair closing odds - 1,
    where the fair closing odds de-vig Pinnacle's close. Research only: nothing is placed.
    """
    df = pred.drop_nulls(["PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA"])
    out: list[dict[str, object]] = []
    for r in df.iter_rows(named=True):
        evs = {o: r[f"m_{o}"] * r[f"PS{o}"] - 1 for o in OUTCOMES}
        o = max(evs, key=lambda k: evs[k])
        if evs[o] <= edge:
            continue
        odds = float(r[f"PS{o}"])
        won = r["result"] == o
        fair_close = 1 / float(r[f"pc_{o}"])
        out.append(
            {
                "date": r["date"],
                "div": r["div"],
                "outcome": o,
                "odds": odds,
                "model_p": r[f"m_{o}"],
                "ev": evs[o],
                "won": won,
                "profit": stake * (odds - 1) if won else -stake,
                "clv": odds / fair_close - 1,
            }
        )
    return (
        pl.DataFrame(out)
        if out
        else pl.DataFrame(
            schema={
                "date": pl.Date,
                "div": pl.Utf8,
                "outcome": pl.Utf8,
                "odds": pl.Float64,
                "model_p": pl.Float64,
                "ev": pl.Float64,
                "won": pl.Boolean,
                "profit": pl.Float64,
                "clv": pl.Float64,
            }
        )
    )


def daily_pnl(bets: pl.DataFrame, start: date, end: date) -> np.ndarray:
    """Calendar-daily bankroll returns (zeros on days without bets) for the gate engine."""
    days = pl.DataFrame({"date": pl.date_range(start, end, timedelta(days=1), eager=True)})
    agg = bets.group_by("date").agg(pl.col("profit").sum()) if bets.height else None
    if agg is None:
        return np.zeros(days.height)
    return days.join(agg, on="date", how="left")["profit"].fill_null(0.0).to_numpy()
