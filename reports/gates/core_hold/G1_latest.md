# G1 gate report: `core_hold` - **FAILED**

- Created: 2026-11-05T14:39:31+00:00
- Data snapshot: `19ad08f1831d6e56`
- Code commit: `5741488c85e599db56820ac92cab0e937b14f57e`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| OOS history length | pass | 15.00y | >= 2.0y |  |
| OOS net Sharpe | pass | 1.08 | >= 0.7 | directional strategy |
| Sharpe 95% CI lower bound | pass | 0.45 (upper 1.64) | > 0.0 | stationary block bootstrap |
| Deflated Sharpe probability | pass | 1.000 | >= 0.95 | N = 17 logged trials |
| Probability of backtest overfitting | **FAIL** | 0.881 | <= 0.2 | 252 CSCV splits |
| Max drawdown within sleeve budget | **FAIL** | 27.2% | <= 25% |  |
| Event-driven confirmation | **FAIL** | not run | <= 10% | relative gap in total return vs vectorised backtest |

## OOS metrics

| Metric | Value |
|---|---|
| n | 3915.0000 |
| total_return | 6.0531 |
| cagr | 0.1391 |
| vol | 0.1288 |
| sharpe | 1.0764 |
| sortino | 0.9528 |
| max_drawdown | 0.2723 |
| calmar | 0.5108 |
| skew | -1.5178 |
| kurtosis | 26.5867 |
| hit_rate | 0.5584 |
| deflated_sharpe | 0.9999 |
| annual_turnover | 4.3194 |
| annual_cost_drag | 0.0022 |
| walkforward_stability | 0.4000 |
| pbo_degradation_slope | -1.0112 |

## Notes

- Slots: ACWI 40%, QQQ 25%, NIFTYBEES 15%, BTC 12%, ETH 8%; cash when filter is off
- Cash earns 0% in the backtest (conservative: T-bill yield ignored)
- Buy-and-hold benchmark logged separately in the same family (scripts/run_core_hold.py)
- Walk-forward: train 522 / test 261 periods, chose variants [0, 0, 0, 6, 6, 1, 1, 0, 7, 0, 0, 3, 3, 1, 5]
- Event-driven confirmation not run: NautilusTrader harness is phase 5
