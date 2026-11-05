import itertools
import json

import polars as pl

from mm.data.catalog import Catalog
from mm.research.backtest import run_weights, wide
from mm.research.theme_momentum import ThemeParams, weights
from mm.validation.metrics import summarize

cat = Catalog()


def load(syms):
    return wide({s: cat.read("bars_1d", "yahoo", s) for s in syms}, column="adj_close")


SECTORS = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"]
THEMES = SECTORS + [
    "SMH",
    "SOXX",
    "IGV",
    "SKYY",
    "CIBR",
    "BOTZ",
    "FDN",
    "OIH",
    "XOP",
    "GLD",
    "SLV",
    "GDX",
    "COPX",
    "XME",
    "URA",
    "LIT",
    "TAN",
    "ICLN",
    "ITA",
    "XBI",
    "IBB",
    "KRE",
    "XHB",
    "ITB",
    "IYT",
    "JETS",
    "KWEB",
    "INDA",
    "EWZ",
    "EWJ",
    "EWT",
    "DBA",
    "PAVE",
    "XRT",
    "VNQ",
]
start = "2001-07-01"
rows = []


def stats(name, r, ts, extra={}):
    df = pl.DataFrame({"ts": ts, "r": r}).filter(
        pl.col("ts") >= pl.datetime(2001, 7, 1, time_zone="UTC")
    )
    s = summarize(df["r"].to_numpy(), 252)
    yr = (
        df.group_by(pl.col("ts").dt.year().alias("y"))
        .agg(((pl.col("r") + 1).product() - 1).alias("ret"))
        .sort("y")
    )
    sub = {}
    for a, b in ((2001, 2010), (2011, 2019), (2020, 2026)):
        x = df.filter(pl.col("ts").dt.year().is_between(a, b))["r"].to_numpy()
        sub[f"{a}-{b}"] = summarize(x, 252).cagr
    rows.append(
        {
            "name": name,
            "cagr": s.cagr,
            "vol": s.vol,
            "sharpe": s.sharpe,
            "max_dd": s.max_drawdown,
            **{k: v for k, v in sub.items()},
            **extra,
            "yearly": json.dumps({int(y): round(v, 3) for y, v in zip(yr["y"], yr["ret"])}),
        }
    )


for b in ["SPY", "QQQ"]:
    c = load([b])
    stats(f"{b} buy & hold", (c[b] / c[b].shift(1) - 1).fill_null(0).to_numpy(), c["ts"])
for uni_name, uni in (("sectors(9)", SECTORS), ("themes(44)", THEMES)):
    c = load(uni)
    ew = c.select("ts", *[pl.lit(1 / len(uni)).alias(s) for s in uni])
    stats(
        f"{uni_name} equal-weight hold",
        run_weights(
            c,
            ew.with_columns(
                [pl.when(c[s].is_null()).then(0.0).otherwise(pl.col(s)).alias(s) for s in uni]
            ),
            cost_bps=5,
        ).net,
        c["ts"],
    )
    for n, ex in itertools.product([3, 5], [0, 50]):
        p = ThemeParams(top_n=n, exit_ma=ex)
        res = run_weights(c, weights(c, p), cost_bps=5)
        stats(
            f"{uni_name} top{n} {'exit<50d daily' if ex else '200d weekly only'}",
            res.net,
            c["ts"],
            {
                "turnover": res.annual_turnover,
                "time_invested": float((res.weights.sum(axis=1) > 0).mean()),
            },
        )
df = pl.DataFrame(rows)
df.write_csv("reports/research/theme_momentum_grid.csv")
with pl.Config(tbl_rows=30, tbl_width_chars=200, fmt_str_lengths=40):
    print(
        df.select(
            "name",
            *[
                pl.col(c).mul(100).round(1)
                for c in ["cagr", "vol", "max_dd", "2001-2010", "2011-2019", "2020-2026"]
            ],
            pl.col("sharpe").round(2),
        )
    )
