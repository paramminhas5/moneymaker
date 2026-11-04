You are the lead engineer for MONEYMAKER, a multi-market automated trading system. The repo is `paramminhas5/moneymaker`. SPEC.md and CLAUDE.md are at the repo root. Read both fully before doing anything. SPEC.md is the source of truth and CLAUDE.md holds the hard rules. If anything here conflicts with them, they win.

## Goal for this session
Deliver build phases 1-4 from SPEC.md section 11:

1. foundation
2. data
3. research and validation
4. strategies S1 (crypto trend ensemble), S2 (funding carry) and S4 (India factor ETF rotation), taken through gate G1 with published gate reports

No live trading. Testnets, sandboxes and historical data only.

## How to work
- Start by making a task list. Then build phase by phase. At the end of each phase:
  - commit
  - open a PR titled `phase-N: <name>` with a short report (what works, test results, gate results, known gaps, assumptions)
  - continue to the next phase without waiting unless you hit something irreversible or money-related
- Before writing any venue adapter or data job, check the current official docs and pin versions:
  - NautilusTrader
  - Hyperliquid Python SDK
  - Binance API
  - Upstox Python SDK and the SEBI April 2026 retail-algo rules
  - Polymarket CLOB v2 / Gamma (read-only)
  - ib_async
  - Alpaca paper
  - yfinance or Tiingo
  - NSE bhavcopy tools
  Several of these changed in 2026. Don't rely on memory.
- Use a sub-agent for each independent slice where it helps (for example: data ingestion, validation math, CLI). Keep the validator's code separate from strategy code.
- Prefer boring, well-tested code over clever code. Type everything in core, risk, execution and portfolio.

## Must-have outcomes by the end
- `uv run mm --help` works. `mm data sync`, `mm backtest <strategy> --walkforward`, `mm gate <strategy>`, `mm status` and `mm kill` all run (kill is a no-op in backtest mode but fully wired).
- **Jurisdiction profiles** for uae, singapore, thailand and india exist. Pre-trade risk rejects any venue or instrument the active profile doesn't allow, and there is a test proving it.
- **Data:** Binance and Hyperliquid OHLCV plus funding history, US ETF daily bars, NSE ETF daily bars and Polymarket Gamma snapshots all land in the Parquet catalog, with data-quality checks.
- **Validation module:**
  - walk-forward
  - Deflated Sharpe Ratio
  - PBO via CSCV
  - bootstrap confidence intervals
  - an experiment log in Postgres that counts every trial
  Unit tests check them against known reference values.
- **Per-venue cost models:** fees, spread, slippage and funding.
- **Strategies S1, S2 and S4:**
  - implemented as NautilusTrader strategies with YAML configs
  - no-lookahead tests
  - vectorbt sweeps (logged)
  - event-driven confirmation
  - one gate report each, saved under `reports/gates/` with equity curve, drawdown, OOS metrics, DSR, PBO, turnover and costs
- **Honesty:** if a strategy fails G1, say so plainly in the report and don't tune it until it passes. That is the system working.

## Then stop and report
Tell me in plain language:

1. what was built
2. which strategies passed or failed G1 and why
3. what phase 5 (paper trading) needs from me: exchange testnet keys, Alpaca paper keys, Upstox sandbox app, Telegram bot token, VPS choice
4. the monthly fixed cost the setup will need

Don't use em dashes in reports.
