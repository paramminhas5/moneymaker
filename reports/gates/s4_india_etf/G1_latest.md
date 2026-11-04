# G1 gate report: `s4_india_etf` - **FAILED**

- Created: 2026-11-04T19:53:13+00:00
- Data snapshot: `396d3d88c8048515`
- Code commit: `411a6a3f842a4165161b1c75ac06ca705487e70b+dirty`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 15.00y | >= 2.0y |  |
| OOS net Sharpe | **FAIL** | 0.65 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | pass | 0.17 (upper 1.12) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | **FAIL** | 0.015 | >= 0.95 | N = 24 logged trials |
| Probability of backtest overfitting | pass | 0.079 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | pass | 19.6% | <= 30% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 3780.0000 |
| total_return | 1.4377 |
| cagr | 0.0612 |
| vol | 0.0998 |
| sharpe | 0.6451 |
| sortino | 0.5175 |
| max_drawdown | 0.1959 |
| calmar | 0.3124 |
| skew | -0.2415 |
| kurtosis | 14.2970 |
| hit_rate | 0.5249 |
| deflated_sharpe | 0.0151 |
| annual_turnover | 4.8685 |
| annual_cost_drag | 0.0126 |
| walkforward_stability | 0.4667 |
| pbo_degradation_slope | -0.7704 |

## Notes

- Monthly rebalance; delivery only (NRI rules)
- MOM30IETF listed mid-2024, so the momentum leg has a short history
- Walk-forward: train 504 / test 126 periods, chose variants [0, 6, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 6, 10, 4, 4, 4, 4, 4, 4, 2, 8, 6, 6, 8, 4]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
