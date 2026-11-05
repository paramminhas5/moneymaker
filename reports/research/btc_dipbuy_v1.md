# BTC dip-buy: backtest v1 (5 Nov 2026)

**What it is.** The best rule from `one_trade_day_v1.md` (buy BTC after a -3% day: +0.47% per trade, 254 trades, 15% CAGR, 36% drawdown on hourly perps), re-tested as a daily strategy with exits. At the close of a day that fell by at least the threshold, go long 1x spot. Exit after `hold` days; a new dip resets the clock. Optional trend filter: only buy dips while BTC is above its 200-day average. Code: `src/mm/strategies/btc_dipbuy.py`, id `btc_dipbuy`, stage `research`.

**Data and costs.** Binance spot BTCUSDT daily, Aug 2017 to Nov 2026. 12 bp one-way (10 bp taker plus spread and slippage).

**Honest trial count.** The rule was picked as the best of 126 scenarios. Those 126 were back-filled into the experiment log (`mm experiments backfill`) under the same family, `one_trade_day_v1`, before this sweep. The Deflated Sharpe therefore pays for the search that found the rule. The gate was run twice (once on uncommitted code, then on commit `5741488`), so the family now holds 150 trials.

## Sweep (12 variants, full sample, net)

| Threshold | Hold | Trend filter | CAGR | Max DD | Sharpe |
|---|---|---|---|---|---|
| 3% | 1 day | no | 4.0% | 49.7% | 0.28 |
| 3% | 3 | no | 0.0% | 78.0% | 0.22 |
| 3% | 5 | no | 7.3% | 71.4% | 0.40 |
| 3% | 1 | yes | -1.1% | 44.0% | 0.01 |
| 3% | 3 | yes | 2.6% | 42.7% | 0.23 |
| 3% | 5 | yes | 11.5% | 46.6% | 0.53 |
| 5% | 1 | no | 4.7% | 41.7% | 0.31 |
| 5% | 3 | no | -7.5% | 77.6% | -0.04 |
| 5% | 5 | no | -14.7% | 86.1% | -0.14 |
| 5% | 1 | yes | 0.0% | 19.7% | 0.05 |
| 5% | 3 | yes | -0.2% | 40.0% | 0.08 |
| 5% | 5 | yes | 0.0% | 41.4% | 0.10 |

For comparison, BTC buy-and-hold over the same period returned 37% a year (Sharpe 0.81) with an 83% drawdown. No variant comes close on return, and none has a usable drawdown.

## Gate G1 (`reports/gates/btc_dipbuy/G1_latest.md`): FAILED on every statistical check

| Check | Result |
|---|---|
| OOS net Sharpe (7 years) | 0.29 (needs 0.7) |
| Sharpe 95% CI lower bound | -0.38 |
| Deflated Sharpe (N = 150) | 0.28 |
| PBO | 0.58 |
| Max drawdown | 44.8% (budget 25%) |

**Verdict: killed.** The hourly study's +0.47% per trade was mostly BTC's general uptrend, earned on the days after dips. Once it has to survive costs (8.7% a year of cost drag at the base settings), proper exits and a walk-forward, there is no edge. The trend-filtered 5-day hold looks best in-sample (Sharpe 0.53), but that is the kind of result a 150-trial search produces by chance.
