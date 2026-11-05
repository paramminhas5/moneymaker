# Core filtered hold: backtest v1 (5 Nov 2026)

**What it is.** A long-only core portfolio with fixed slots: world equity (ACWI) 40%, Nasdaq-100 (QQQ) 25%, Nifty 50 (NIFTYBEES.NS) 15%, BTC 12%, ETH 8%. Each slot is held only while that asset is above its moving average (hysteresis band, as in trend v2). When an asset's filter is off its slot sits in cash. Rebalanced monthly; prices drift in between with no trading. Code: `src/mm/strategies/core_hold.py`, strategy id `core_hold`, stage `research`.

**Data.** Yahoo daily adjusted closes, Apr 2008 to Nov 2026 (ACWI from 2008, NIFTYBEES 2009, BTC Sep 2014, ETH Nov 2017; a slot is cash before its asset exists). Mon-Fri calendar; crypto weekend moves roll into Monday. One bad NIFTYBEES print (Dec 2019, a -90%/+900% one-day spike) is removed by `drop_reversal_spikes`.

**Costs.** One-way: QQQ 3 bp, ACWI 5 bp, NIFTYBEES 25 bp (Indian delivery charges at small size), BTC/ETH 15 bp. Cash earns 0% (conservative; T-bill yield ignored).

## Filtered vs plain buy-and-hold (same slots, full sample, net)

| Variant | CAGR | Max DD | Sharpe | Worst year | 2008 | 2022 |
|---|---|---|---|---|---|---|
| Filtered, MA200, 2% band, monthly (base) | 13.2% | 20.6% | 0.99 | -9.9% | 0.0% | -9.9% |
| Buy and hold, monthly rebalance | 17.1% | 39.3% | 0.91 | -29.1% | -26.2% | -29.1% |

The filter gives up about 4 points of CAGR for half the drawdown. In 2008 it was in cash; in 2022 it lost 10% instead of 29%. Per-asset breakdown: `core_hold_compare.csv` (the filter helped ACWI, QQQ and BTC on risk-adjusted terms; it hurt NIFTYBEES and ETH, where whipsaws cost more than the drawdowns it avoided).

## Sweep (8 filtered variants + buy-and-hold, all logged to family `core_hold_v1`)

| MA | Band | Filter check | CAGR | Max DD | Sharpe |
|---|---|---|---|---|---|
| 150 | 0% | monthly | 13.8% | 20.1% | 1.05 |
| 150 | 2% | monthly | 13.5% | 20.1% | 1.02 |
| 200 | 0% | monthly | 13.5% | 19.9% | 1.01 |
| 200 | 2% | monthly | 13.2% | 20.6% | 0.99 |
| 150 | 0% | daily | 12.6% | 30.2% | 1.03 |
| 150 | 2% | daily | 12.9% | 28.7% | 1.05 |
| 200 | 0% | daily | 12.6% | 26.0% | 1.02 |
| 200 | 2% | daily | 13.0% | 27.7% | 1.04 |

Checking the filter daily instead of monthly does not improve Sharpe and adds 6-10 points of drawdown (whipsaws in fast V-shaped recoveries).

## Gate G1 (`reports/gates/core_hold/G1_latest.md`): FAILED

| Check | Result |
|---|---|
| OOS net Sharpe (walk-forward, 15 years) | **1.08, pass** |
| Sharpe 95% CI lower bound | 0.45, pass |
| Deflated Sharpe (N = 17 logged trials) | 1.000, pass |
| PBO | **0.88, fail** |
| Max drawdown within the 25% default sleeve budget | **27.2%, fail** |
| Event-driven confirmation | not run (fails for every strategy until the Nautilus harness exists) |

Why it fails, honestly:
- **PBO 0.88** is high because the variants are nearly identical (Sharpe 0.99-1.05). With no real difference between them, the in-sample best is a coin flip out of sample, which CSCV scores as overfitting. The edge is the filter itself, not the parameter choice, but the gate can't tell those apart and it stays a fail.
- **27% OOS drawdown** comes from the walk-forward picking the daily-check variants in some folds. Every monthly variant has a full-sample max DD of 20-21%.

**Recommendation.** The monthly MA200 version is a sensible core holding with the drawdown halved, but it has not passed the gate. Do not tune it to pass. If Param wants it, the honest route is to pre-commit the monthly MA200 version as v2 and paper-track it. There is no risk.yaml entry for `core_hold`, so it uses the 25% default; whether a core sleeve should get a wider budget is Param's call in risk.yaml. The live version would use UCITS ETFs on IBKR (e.g. a world ETF and a Nasdaq-100 ETF) plus NIFTYBEES on Upstox; IBKR's $1 minimum commission matters below about $2k per slot.
