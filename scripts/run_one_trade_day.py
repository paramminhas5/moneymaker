"""Run the one-trade-a-day grid and write results to reports/research."""

import itertools
import json

import polars as pl

from mm.data.catalog import Catalog
from mm.research.one_trade_day import ENTRIES, Exits, build_days, run

cat = Catalog()
rows = []
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    bars = cat.read("bars_1h", "binance_perp", sym)
    fund = (
        cat.read("funding", "binance_perp", sym)
        if cat.exists("funding", "binance_perp", sym)
        else None
    )
    days = build_days(bars, fund)
    exits = [Exits(None, None, 1)]  # control: no TP/SL, exit end of day
    exits += [Exits(0.05, sl, lev) for sl, lev in itertools.product([0.025, 0.05], [1, 3, 5])]
    for (name, fn), ex in itertools.product(ENTRIES.items(), exits):
        res = run(days, fn, ex)
        rows.append(
            {
                "asset": sym.removesuffix("USDT"),
                "entry": name,
                "tp": ex.acct_tp or 0,
                "sl": ex.acct_sl or 0,
                "lev": ex.leverage,
                "trades": res.trades,
                "tp_hit": res.tp_rate,
                "sl_hit": res.sl_rate,
                "avg_per_trade": res.mean,
                "median": res.median,
                "days_ge_5pct": res.share_ge_5pct,
                "cagr": res.cagr,
                "max_dd": res.max_dd,
                "worst_losing_streak": res.worst_streak,
                "pos_months": res.pos_months,
                "x_multiple": res.final_multiple,
                "yearly": json.dumps({str(k): round(v, 3) for k, v in res.yearly.items()}),
            }
        )
df = pl.DataFrame(rows)
df.write_csv("reports/research/one_trade_day_grid.csv")
print(
    f"{df.height} scenarios; positive CAGR: {(df['cagr'] > 0).sum()}; "
    f"avg per trade >= 5%: {(df['avg_per_trade'] >= 0.05).sum()}; "
    f"wiped out (x < 0.05): {(df['x_multiple'] < 0.05).sum()}"
)
