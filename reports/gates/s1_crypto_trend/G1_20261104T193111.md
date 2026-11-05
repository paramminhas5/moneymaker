# G1 gate report: `s1_crypto_trend` - **FAILED**

- Created: 2026-11-04T19:31:11+00:00
- Data snapshot: `0a81eefc446df27e`
- Code commit: `fbb00ad0ef39788c8ad85dca9adb4606bb0d6fbc+dirty`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 6.48y | >= 2.0y |  |
| OOS net Sharpe | pass | 0.79 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | **FAIL** | -0.10 (upper 1.66) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | **FAIL** | 0.877 | >= 0.95 | N = 54 logged trials |
| Probability of backtest overfitting | pass | 0.190 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | pass | 28.3% | <= 35% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 2366.0000 |
| total_return | 1.3975 |
| cagr | 0.1444 |
| vol | 0.1953 |
| sharpe | 0.7886 |
| sortino | 0.6529 |
| max_drawdown | 0.2834 |
| calmar | 0.5096 |
| skew | 0.0710 |
| kurtosis | 24.9468 |
| hit_rate | 0.4813 |
| deflated_sharpe | 0.8767 |
| annual_turnover | 23.7881 |
| annual_cost_drag | 0.0275 |
| walkforward_stability | 0.4615 |
| pbo_degradation_slope | -0.8004 |

## Notes

- Universe is point-in-time top-N by trailing 90d median quote volume
- Includes delisted names (LUNA, FTT) in candidates: no survivorship bias
- Walk-forward: train 730 / test 182 periods, chose variants [35, 24, 6, 8, 6, 7, 7, 8, 8, 8, 8, 8, 26]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
