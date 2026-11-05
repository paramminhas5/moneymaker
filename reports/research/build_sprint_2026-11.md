# Build sprint, Nov 2026: remaining sleeves

Branch `build/remaining-sleeves`, from main after PR #4. Six items built. Every new strategy is at stage `research`. No live or paper stage was changed, no protected file was touched, and nothing was traded.

## Scorecard

| # | Sleeve | Built | Key result (net, out of sample unless noted) | G1 |
|---|---|---|---|---|
| 1 | Core filtered hold (`core_hold`) | strategy, tests, gate, B&H comparison | OOS Sharpe 1.08, CAGR 13.9%, DSR 1.00; full-sample max DD 20.6% vs 39.3% for buy-and-hold | **FAIL**: PBO 0.88, OOS DD 27.2% > 25%, event-driven not run |
| 2 | BTC dip-buy (`btc_dipbuy`) | strategy, tests, gate | OOS Sharpe 0.29, DSR 0.28 with all 150 trials counted, DD 45% | **FAIL**, killed |
| 3 | Listing fade (`listing_fade`, `listing_fade_stops`) | 923-symbol survivorship-free universe, TradFi filter, close-stop and intraday-stop versions | 70% of new listings fall within 4 weeks (median -18%), yet every variant loses 99% to squeezes, costs and funding | **FAIL**, killed |
| 4 | Football model (`football_dc`) | Dixon-Coles, weekly walk-forward over 22k matches, season sim, Polymarket comparison, CLV proposal queue | log loss 0.989 vs Pinnacle close 0.964; value bets -6 to -8% ROI, CLV -2.6% | **FAIL**; queue measures futures CLV with no money |
| 5 | SPY/QQQ noise-area intraday | strategy, Alpaca adapter, synthetic tests | **not run**: no free minute history without a key | not run |
| 6 | Theme-call tracker | ledger, `mm theme add/report`, tests | empty ledger, waiting for Param's calls | n/a |

**No sleeve passed G1.** Every strategy in the repo also fails "event-driven confirmation", because the Nautilus harness is phase 5 work. Gate thresholds were not changed.

## What is worth acting on
- **Core hold** is the only useful result. The 200-day filter halves drawdown (20.6% vs 39.3%) for about 4 points less CAGR, and it was in cash for 2008 and most of 2022. It fails on PBO because its variants are near-identical (the edge is the filter, not the parameters), and on drawdown because the walk-forward sometimes picked daily-check variants. Honest next step: pre-commit the monthly MA200 version as v2 and paper-track it. Don't tune it to pass.
- **Football**: the model loses to bookmakers on matches, as goals-only models do. Five season-futures proposals are logged in `ledger/football_proposals.jsonl` to measure closing-line value with no money. Two concern Man City, where the market is likely pricing a possible points deduction that the model can't see; that is the case for Param's veto.
- **Killed**: BTC dip-buy (its edge was BTC's uptrend) and listing fade (right-tail squeezes). Neither should get capital.

## Engineering added
- **Data.**
  - football-data.co.uk source.
  - Binance archive listing helpers: every perp ever listed, plus first-months windows.
  - Yahoo bad-print repair (`drop_reversal_spikes`) and a Mon-Fri calendar for mixed-venue portfolios.
  - Fetch scripts for each dataset.
- **Research engine.**
  - `hold_between_rebalances`: true monthly rebalancing with no daily drift trades.
  - Per-symbol costs in `Spec`.
  - `gate_matrix`: G1 for non-Spec streams.
  - Experiment-log `export` and `backfill`. The 126 trials of the one-trade-a-day study were back-filled so the dip-buy DSR pays for the search that found it.
- **CLI.** `mm theme add/report`, `mm experiments list/export/backfill`. `mm backtest` and `mm gate` work for `core_hold`, `btc_dipbuy` and `listing_fade`.
- **Tests.** 29 new tests: no-lookahead for every new signal, rules, cost and funding sign, the stop-fill model, the Dixon-Coles fit being point in time, season-sim consistency, the proposal queue and the theme ledger. Tests, ruff and pyright are green.
- **Dependencies.** `scipy` added (Dixon-Coles fit). It is already in the SPEC stack.

## Trial counts (experiment log; exported to `reports/research/experiments_*.csv`)

| Family | Trials |
|---|---|
| `core_hold_v1` | 17 (8-variant sweep run twice, plus buy-and-hold) |
| `one_trade_day_v1` | 150 (126 back-filled, plus a 12-variant sweep run twice) |
| `listing_fade_v1` | 20 (8 close-stop, 12 intraday-stop) |
| `football_dc_v1` | 18 (9 variants run twice) |

Repeat runs were made so the gate reports carry a clean commit hash. They are counted, which only makes the DSR stricter. Caveat: the experiment DB is the local SQLite in `var/`, which isn't in git. The CSV exports are the durable record, and the S1/S2/S4 trial history from earlier sessions is not in this container's DB.

## What still needs Param
1. **Review this PR** (not merged by the agent).
2. **Alpaca keys** (free paper account), stored as `MM_SECRET_ALPACA_KEY_ID` and `MM_SECRET_ALPACA_SECRET`. They unlock the intraday backtest.
3. **Theme calls**: add real ones with `mm theme add TICKER --thesis "..."`. About 20 closed calls are needed before the sleeve can be judged.
4. **Decisions only Param can make:**
   - Whether a core sleeve should get its own drawdown budget in `risk.yaml` (the default is 25%).
   - Whether to approve paper-tracking a pre-committed monthly MA200 core hold.
5. **Earlier open items** (from doc 12): `jurisdiction.active` is still `singapore` (Binance is read-only there, Polymarket is close-only), and the risk caps are still at micro-capital levels.
