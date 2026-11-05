# G1 gate report: `s2_funding_carry` - **FAILED**

- Created: 2026-11-04T19:53:10+00:00
- Data snapshot: `396d3d88c8048515`
- Code commit: `411a6a3f842a4165161b1c75ac06ca705487e70b+dirty`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 4.49y | >= 2.0y |  |
| OOS net Sharpe | pass | 6.38 | >= 1.0 | carry strategy |
| Sharpe 95% CI lower bound | pass | 4.24 (upper 8.64) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | pass | 1.000 | >= 0.95 | N = 24 logged trials |
| Probability of backtest overfitting | pass | 0.000 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | pass | 0.6% | <= 10% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 1638.0000 |
| total_return | 0.1707 |
| cagr | 0.0357 |
| vol | 0.0055 |
| sharpe | 6.3801 |
| sortino | 4.6064 |
| max_drawdown | 0.0064 |
| calmar | 5.6273 |
| skew | 1.3128 |
| kurtosis | 16.6954 |
| hit_rate | 0.7912 |
| deflated_sharpe | 1.0000 |
| annual_turnover | 14.9787 |
| annual_cost_drag | 0.0116 |
| walkforward_stability | 0.6667 |
| pbo_degradation_slope | -0.7875 |

## Notes

- Margin buffer, ADL and depeg monitors are live-only concerns (phase 5)
- Backtest assumes perp short is fully collateralised (1x), no liquidation risk
- Walk-forward: train 730 / test 182 periods, chose variants [2, 10, 10, 2, 2, 2, 2, 0, 2]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
