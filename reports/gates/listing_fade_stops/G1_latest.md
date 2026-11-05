# G1 gate report: `listing_fade_stops` - **FAILED**

- Created: 2026-11-05T15:03:00+00:00
- Data snapshot: `f375f591718355d9`
- Code commit: `5113564b957d15f222d80b4637f4fb02da02bc93`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 4.49y | >= 2.0y |  |
| OOS net Sharpe | **FAIL** | -0.14 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | **FAIL** | -0.91 (upper 0.78) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | **FAIL** | 0.070 | >= 0.95 | N = 20 logged trials |
| Probability of backtest overfitting | **FAIL** | 0.385 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | **FAIL** | 99.8% | <= 25% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 1638.0000 |
| total_return | -0.9876 |
| cagr | -0.6240 |
| vol | 1.1922 |
| sharpe | -0.1435 |
| sortino | -0.1173 |
| max_drawdown | 0.9975 |
| calmar | -0.6256 |
| skew | -1.8081 |
| kurtosis | 17.4568 |
| hit_rate | 0.5199 |
| deflated_sharpe | 0.0697 |
| walkforward_stability | 0.5556 |
| pbo_degradation_slope | -1.0287 |

## Notes

- Intraday stop-market at entry*(1+stop), filled 10% beyond (or at a gap open); 20 bp one-way; funding received/paid daily
- Binance USD-M archive incl. delisted symbols; 3 names max, 1/3 each
- Walk-forward train/test (730, 182), chose variants [2, 2, 11, 2, 2, 7, 2, 5, 5]
- Event-driven confirmation not run: not applicable until a paper venue exists
