# G1 gate report: `listing_fade` - **FAILED**

- Created: 2026-11-05T15:02:38+00:00
- Data snapshot: `f375f591718355d9`
- Code commit: `42dc83fd2ec45f061d48d93e00011feaae2701a0+dirty`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 4.49y | >= 2.0y |  |
| OOS net Sharpe | **FAIL** | -0.04 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | **FAIL** | -0.80 (upper 0.83) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | **FAIL** | 0.252 | >= 0.95 | N = 8 logged trials |
| Probability of backtest overfitting | **FAIL** | 0.587 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | **FAIL** | 99.8% | <= 25% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 1638.0000 |
| total_return | -0.9891 |
| cagr | -0.6343 |
| vol | 1.2616 |
| sharpe | -0.0444 |
| sortino | -0.0354 |
| max_drawdown | 0.9978 |
| calmar | -0.6357 |
| skew | -2.2014 |
| kurtosis | 21.7491 |
| hit_rate | 0.5295 |
| deflated_sharpe | 0.2525 |
| annual_turnover | 54.5036 |
| annual_cost_drag | 0.1042 |
| walkforward_stability | 0.3333 |
| pbo_degradation_slope | -0.8935 |

## Notes

- Binance USD-M archive incl. delisted symbols; live venue would be Hyperliquid perps
- Funding charged/received daily; stop 10.0 means effectively no stop
- Max 3 names, 1/3 each: gross 1x, never levered
- Walk-forward: train 730 / test 182 periods, chose variants [1, 1, 6, 1, 0, 4, 0, 6, 3]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
