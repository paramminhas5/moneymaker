"""Listing fade research: base rates after listing, intraday-stop variants (trade-level sim) and
their G1. The close-stop Spec variants are gated separately with `mm gate listing_fade`; both
log to family listing_fade_v1 so the Deflated Sharpe counts every variant.
Outputs: reports/research/listing_fade_grid.csv, listing_fade_base_rates.csv, gate report
reports/gates/listing_fade_stops/.
"""

import itertools

import numpy as np
import polars as pl

from mm.data.catalog import Catalog
from mm.db.session import init_db, make_engine
from mm.research.backtest import wide
from mm.research.listing_fade_stops import StopParams, simulate
from mm.research.matrix_gate import gate_matrix
from mm.strategies.listing_fade import listed_symbols, load_data
from mm.validation.experiments import ExperimentLog, code_commit
from mm.validation.metrics import sharpe, summarize

cat = Catalog()
snap, commit = cat.snapshot_id(), code_commit()
engine = make_engine()
init_db(engine)
log = ExperimentLog(engine)

data = load_data()
close, funding = data["close"], data["funding"]
syms = [c for c in close.columns if c != "ts"]
bars = {s: cat.read("bars_1d", "binance_perp_new", s) for s in syms}
high = close.select("ts").join(wide(bars, "high"), on="ts", how="left").select(close.columns)
open_ = close.select("ts").join(wide(bars, "open"), on="ts", how="left").select(close.columns)

# Base rates: return from the day-1 close to day N (no costs), per listing.
px = close.select(syms).to_numpy()
first = np.isfinite(px).argmax(axis=0)
rows = []
for j, s in enumerate(syms):
    i0 = int(first[j]) + 1
    if i0 >= px.shape[0] or not np.isfinite(px[i0, j]):
        continue
    row = {
        "symbol": s,
        "listed": close["ts"][int(first[j])].date(),
        "max_up_28d": float(np.nanmax(px[i0 : i0 + 29, j]) / px[i0, j] - 1),
    }
    for n in (7, 14, 28, 56):
        k = i0 + n
        row[f"ret_{n}d"] = (
            float(px[k, j] / px[i0, j] - 1) if k < px.shape[0] and np.isfinite(px[k, j]) else None
        )
    rows.append(row)
base = pl.DataFrame(rows)
base.write_csv("reports/research/listing_fade_base_rates.csv")
listed_all = len(listed_symbols(cat))
print("listings", base.height, "of", listed_all)
for n in (7, 14, 28, 56):
    col = base[f"ret_{n}d"].drop_nulls()
    print(
        n,
        "n",
        col.len(),
        "median",
        round(float(col.median()), 3),
        "share down",
        round(float((col < 0).mean()), 3),
        "mean",
        round(float(col.mean()), 3),
    )
print("share with +50% at some close in 28d:", float((base["max_up_28d"] >= 0.5).mean()))
print("listings by year", base.group_by(pl.col("listed").dt.year()).len().sort("listed").rows())

grid, nets = [], []
for delay, hold, stop in itertools.product([1, 3], [14, 28], [0.3, 0.5, 1.0]):
    p = StopParams(delay=delay, hold=hold, stop=stop)
    r, trades, stops = simulate(close, high, open_, funding, p)
    s = summarize(r, 365)
    m = {
        **s.as_dict(),
        "sharpe_per_period": sharpe(r, annualize=False),
        "trades": float(trades),
        "stops": float(stops),
    }
    log.log(
        strategy_id="listing_fade_stops",
        family="listing_fade_v1",
        params={
            "delay": delay,
            "hold": hold,
            "stop": stop,
            "max_names": 3,
            "slippage": p.slippage,
            "cost_bps": p.cost_bps,
            "stop_type": "intraday",
        },
        data_snapshot=snap,
        metrics=m,
        commit=commit,
    )
    grid.append(
        {
            "delay": delay,
            "hold": hold,
            "stop": stop,
            "trades": trades,
            "stops": stops,
            "cagr": s.cagr,
            "max_dd": s.max_drawdown,
            "sharpe": s.sharpe,
            "total_return": s.total_return,
        }
    )
    nets.append(r)
g = pl.DataFrame(grid)
g.write_csv("reports/research/listing_fade_grid.csv")
with pl.Config(tbl_rows=20, tbl_width_chars=160):
    print(g)
g1 = gate_matrix(
    "listing_fade_stops",
    "listing_fade_v1",
    "directional",
    np.column_stack(nets),
    log,
    periods_per_year=365,
    walkforward=(730, 182),
    data_snapshot=snap,
    code_commit=commit,
    notes=[
        "Intraday stop-market at entry*(1+stop), filled 10% beyond (or at a "
        "gap open); 20 bp one-way; funding received/paid daily",
        "Binance USD-M archive incl. delisted symbols; 3 names max, 1/3 each",
    ],
)
g1.save()
print(g1.to_markdown())
