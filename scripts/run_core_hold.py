"""Core filtered hold vs plain buy-and-hold (same slots, monthly rebalance), full history and
per asset. Logs the buy-and-hold variant to family core_hold_v1 (it was looked at, so it counts).
Writes reports/research/core_hold_compare.csv."""

import polars as pl

from mm.data.catalog import Catalog
from mm.db.session import init_db, make_engine
from mm.research.backtest import run_weights
from mm.strategies import get
from mm.strategies.core_hold import COST_BPS, signal
from mm.validation.experiments import ExperimentLog, code_commit
from mm.validation.metrics import sharpe, summarize

spec = get("core_hold")
data = spec.load_data()
close = data["close"]
engine = make_engine()
init_db(engine)
log = ExperimentLog(engine)
snap = Catalog().snapshot_id()
rows = []


def run(label: str, cl: pl.DataFrame, params: dict, log_it: bool = False) -> None:
    w = signal(cl, params)
    res = run_weights(cl, w, cost_bps=COST_BPS)
    s = summarize(res.net, 261)
    if log_it:
        log.log(
            strategy_id="core_hold",
            family="core_hold_v1",
            params=params,
            data_snapshot=snap,
            metrics={**s.as_dict(), "sharpe_per_period": sharpe(res.net, annualize=False)},
            commit=code_commit(),
        )
    yearly = (
        res.frame()
        .with_columns(pl.col("ts").dt.year().alias("y"))
        .group_by("y")
        .agg(((pl.col("net") + 1).product() - 1).alias("r"))
        .sort("y")
    )
    rows.append(
        {
            "variant": label,
            "cagr": s.cagr,
            "max_dd": s.max_drawdown,
            "sharpe": s.sharpe,
            "vol": s.vol,
            "worst_year": float(yearly["r"].min()),
            "y2008": yearly.filter(pl.col("y") == 2008)["r"].to_list()[:1] or [None],
            "y2022": float(yearly.filter(pl.col("y") == 2022)["r"][0]),
            "turnover_per_year": float(res.turnover.mean() * 261),
        }
    )


base = dict(spec.base_params)
run("filtered (base: MA200, 2% band, monthly)", close, base)
run("buy and hold (monthly rebalance)", close, base | {"filter": False}, log_it=True)
for sym in [c for c in close.columns if c != "ts"]:
    one = close.select("ts", sym)
    run(f"{sym} filtered (slot weight only)", one, base)
    run(f"{sym} buy and hold (slot weight only)", one, base | {"filter": False})
df = pl.DataFrame(rows).with_columns(pl.col("y2008").list.first())
df.write_csv("reports/research/core_hold_compare.csv")
with pl.Config(tbl_rows=30, tbl_width_chars=200):
    print(df)
