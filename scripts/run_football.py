"""Football Dixon-Coles research run: walk-forward calibration vs bookmakers, value-bet CLV,
G1 on the hypothetical bet stream, and 2026/27 season simulations. Research only.

Every (xi, edge) variant is logged to the experiment log, family football_dc_v1.
Outputs: reports/research/football_dc_grid.csv, football_calibration.csv,
football_season_sim_2026.csv and reports/gates/football_dc/.
"""

import itertools
import json
from datetime import date

import numpy as np
import polars as pl

from mm.data.catalog import Catalog
from mm.db.session import init_db, make_engine
from mm.research.football.dixon_coles import DCConfig, fit, simulate_season
from mm.research.football.evaluate import daily_pnl, predict_walkforward, score, value_bets
from mm.research.matrix_gate import gate_matrix
from mm.validation.experiments import ExperimentLog, code_commit
from mm.validation.metrics import sharpe, summarize

FIRST_SEASON = 2014  # two prior seasons of history for the first fit
XIS = [0.001, 0.002, 0.004]
EDGES = [0.02, 0.05, 0.10]
OUT = "reports/research"

cat = Catalog()
snapshot = cat.snapshot_id()
commit = code_commit()
engine = make_engine()
init_db(engine)
log = ExperimentLog(engine)

matches = pl.read_parquet(cat.root / "football" / "matches.parquet")
preds = {}
for xi in XIS:
    preds[xi] = predict_walkforward(matches, DCConfig(xi=xi), FIRST_SEASON)
    print("xi", xi, preds[xi].height, flush=True)

# Calibration: each forecaster scored on the same rows (where Pinnacle close exists), and the
# model vs market-average close on every row.
cal_rows = []
for xi, p in preds.items():
    both = p.drop_nulls(["pc_H", "pe_H"])
    for name, pre, df in [
        ("model", "m", both),
        ("pinnacle_close", "pc", both),
        ("pinnacle_early", "pe", both),
        ("avg_close", "ac", both),
        ("model_all_rows", "m", p.drop_nulls(["ac_H"])),
        ("avg_close_all_rows", "ac", p.drop_nulls(["ac_H"])),
    ]:
        s = score(df, pre)
        cal_rows.append(
            {"xi": xi, "forecaster": name, "n": s.n, "brier": s.brier, "log_loss": s.log_loss}
        )
cal = pl.DataFrame(cal_rows)
cal.write_csv(f"{OUT}/football_calibration.csv")
print(cal)

# Calibration curve of the model (deciles of predicted home-win probability), best xi later.
start, end = matches["date"].min(), matches["date"].max()
grid_rows, nets = [], []
for xi, edge in itertools.product(XIS, EDGES):
    bets = value_bets(preds[xi], edge)
    pnl = daily_pnl(bets, start, end)
    s = summarize(pnl, 365)
    metrics = {
        **s.as_dict(),
        "sharpe_per_period": sharpe(pnl, annualize=False),
        "bets": float(bets.height),
        "roi_per_bet": float(bets["profit"].sum() / (0.01 * bets.height)) if bets.height else 0.0,
        "mean_clv": float(bets["clv"].mean()) if bets.height else 0.0,
        "share_pos_clv": float((bets["clv"] > 0).mean()) if bets.height else 0.0,
    }
    log.log(
        strategy_id="football_dc",
        family="football_dc_v1",
        params={"xi": xi, "edge": edge, "first_season": FIRST_SEASON, "stake": 0.01},
        data_snapshot=snapshot,
        metrics=metrics,
        commit=commit,
    )
    grid_rows.append(
        {
            "xi": xi,
            "edge": edge,
            **{
                k: metrics[k]
                for k in (
                    "bets",
                    "roi_per_bet",
                    "mean_clv",
                    "share_pos_clv",
                    "cagr",
                    "max_drawdown",
                    "sharpe",
                )
            },
        }
    )
    nets.append(pnl)
grid = pl.DataFrame(grid_rows)
grid.write_csv(f"{OUT}/football_dc_grid.csv")
print(grid)

g1 = gate_matrix(
    "football_dc",
    "football_dc_v1",
    "directional",
    np.column_stack(nets),
    log,
    periods_per_year=365,
    walkforward=(730, 365),
    data_snapshot=snapshot,
    code_commit=commit,
    notes=[
        "Hypothetical 1% flat stakes at Pinnacle's early price (PSH/PSD/PSA)",
        "Research only: Polymarket trading is disabled in every profile",
    ],
)
g1.save()
print(g1.to_markdown())

# Season simulation for the current season, model fitted as of today, best-calibrated xi.
best_xi = min(
    XIS,
    key=lambda x: cal.filter((pl.col("xi") == x) & (pl.col("forecaster") == "model_all_rows"))[
        "log_loss"
    ][0],
)
today = date(2026, 11, 5)
sims = []
for div in sorted(matches["div"].unique().to_list()):
    lg = matches.filter(pl.col("div") == div)
    cur = lg.filter(pl.col("season") == 2026)
    if cur.is_empty():
        continue
    teams = sorted(set(cur["home"].to_list()) | set(cur["away"].to_list()))
    model = fit(lg, today, DCConfig(xi=best_xi))
    sim = simulate_season(model, cur, teams, n_sims=10_000, seed=7)
    sims.append(sim.with_columns(pl.lit(div).alias("div")))
pl.concat(sims).write_csv(f"{OUT}/football_season_sim_2026.csv")
print(json.dumps({"best_xi": best_xi}))
