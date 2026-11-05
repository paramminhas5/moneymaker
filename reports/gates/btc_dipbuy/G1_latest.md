# G1 gate report: `btc_dipbuy` - **FAILED**

- Created: 2026-11-05T14:39:35+00:00
- Data snapshot: `5fddddc01da3535a`
- Code commit: `5741488c85e599db56820ac92cab0e937b14f57e`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 6.98y | >= 2.0y |  |
| OOS net Sharpe | **FAIL** | 0.29 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | **FAIL** | -0.38 (upper 0.87) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | **FAIL** | 0.281 | >= 0.95 | N = 150 logged trials |
| Probability of backtest overfitting | **FAIL** | 0.583 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | **FAIL** | 44.8% | <= 25% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 2548.0000 |
| total_return | 0.3291 |
| cagr | 0.0416 |
| vol | 0.3019 |
| sharpe | 0.2863 |
| sortino | 0.1592 |
| max_drawdown | 0.4483 |
| calmar | 0.0928 |
| skew | 0.1831 |
| kurtosis | 37.5818 |
| hit_rate | 0.3897 |
| deflated_sharpe | 0.2813 |
| annual_turnover | 30.0824 |
| annual_cost_drag | 0.0869 |
| walkforward_stability | 0.2857 |
| pbo_degradation_slope | -0.5770 |

## Notes

- Rule mined from reports/research/one_trade_day_v1.md (best of 126 scenarios)
- Family one_trade_day_v1: the 126 prior scenarios are back-filled before the sweep
- Spot, 1x, 12 bp one-way (taker 10 bp + spread/slippage)
- Walk-forward: train 730 / test 182 periods, chose variants [6, 6, 6, 2, 0, 0, 0, 0, 3, 5, 5, 4, 4, 6]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
