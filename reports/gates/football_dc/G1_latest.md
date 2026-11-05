# G1 gate report: `football_dc` - **FAILED**

- Created: 2026-11-05T14:41:27+00:00
- Data snapshot: `fb21a4e4d966082c`
- Code commit: `5741488c85e599db56820ac92cab0e937b14f57e`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 10.00y | >= 2.0y |  |
| OOS net Sharpe | **FAIL** | -1.55 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | **FAIL** | -2.16 (upper -0.99) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | **FAIL** | 0.000 | >= 0.95 | N = 18 logged trials |
| Probability of backtest overfitting | **FAIL** | 0.409 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | **FAIL** | 100.0% | <= 25% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 3650.0000 |
| total_return | -1.0000 |
| cagr | -0.6679 |
| vol | 0.5962 |
| sharpe | -1.5532 |
| sortino | -1.1998 |
| max_drawdown | 1.0000 |
| calmar | -0.6679 |
| skew | 1.3076 |
| kurtosis | 17.3562 |
| hit_rate | 0.3436 |
| deflated_sharpe | 0.0000 |
| walkforward_stability | 0.4000 |
| pbo_degradation_slope | -0.8425 |

## Notes

- Hypothetical 1% flat stakes at Pinnacle's early price (PSH/PSD/PSA)
- Research only: Polymarket trading is disabled in every profile
- Walk-forward train/test (730, 365), chose variants [2, 5, 5, 5, 2, 5, 1, 8, 8, 3]
- Event-driven confirmation not run: not applicable until a paper venue exists
