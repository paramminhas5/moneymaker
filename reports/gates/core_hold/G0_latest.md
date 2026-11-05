# G0 gate report: `core_hold` - **PASSED**

- Created: 2026-11-05T14:39:30+00:00
- Data snapshot: `19ad08f1831d6e56`
- Code commit: `5741488c85e599db56820ac92cab0e937b14f57e`

| Check | Result | Value | Threshold | Detail |
|---|---|---|---|---|
| no-lookahead harness | pass | True | True |  |
| unit tests | pass | True | True |  |
| cost model attached | pass | per-symbol bps: ACWI 5, QQQ 3, NIFTYBEES.NS 25, BTC-USD 15, ETH-USD 15 | a model |  |
| deterministic replay | pass | True | True | same seed + snapshot + commit gives identical returns |
