# G1 gate report: `s1_crypto_trend_v2` - **FAILED**

- Created: 2026-11-04T22:08:12+00:00
- Data snapshot: `82b3b3d31db28713`
- Code commit: `4b9e43fd8127b938216cc161457bb23041e3193a+dirty`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 6.48y | >= 2.0y |  |
| OOS net Sharpe | pass | 1.35 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | pass | 0.46 (upper 2.14) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | pass | 0.996 | >= 0.95 | N = 57 logged trials |
| Probability of backtest overfitting | **FAIL** | 1.000 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | pass | 13.7% | <= 25% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 2366.0000 |
| total_return | 1.3984 |
| cagr | 0.1445 |
| vol | 0.1039 |
| sharpe | 1.3508 |
| sortino | 1.0448 |
| max_drawdown | 0.1366 |
| calmar | 1.0578 |
| skew | 0.5745 |
| kurtosis | 13.4899 |
| hit_rate | 0.5281 |
| deflated_sharpe | 0.9955 |
| annual_turnover | 12.6734 |
| annual_cost_drag | 0.0153 |
| walkforward_stability | 0.5385 |
| pbo_degradation_slope | -1.0021 |

## Notes

- v1 signal + BTC 200d gate (+/-3% hysteresis) + ATR(20) chandelier exit
- Only atr_mult varied; trials share the s1_v1 family so the DSR counts all 57
- Walk-forward: train 730 / test 182 periods, chose variants [0, 0, 0, 0, 0, 0, 0, 2, 1, 1, 1, 2, 2]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
