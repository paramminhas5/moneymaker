# MONEYMAKER: build spec v1

Owner: Param Minhas. Status: v1, 4 Nov 2026.
Research backing this spec is in the claude.ai project "Money" (docs 01-04).

## 0. What this is

A multi-market automated trading system with one control terminal and a swarm of AI agents around it. It trades **only strategies that have passed hard statistical gates**. It moves real money only after a human approves.

The edge is not a secret signal. Published signals decay fast, and most retail traders lose, both by large margins (see doc 03). Ours comes from four things:

1. **A strategy factory.** Agents generate many hypotheses. A validator that can't be argued with kills almost all of them using Deflated Sharpe, PBO and walk-forward tests. Only survivors trade.
2. **Capacity-constrained niches** that are too small for funds: cross-venue funding spreads, mid-cap perp funding, thin markets.
3. **Cost discipline.** Low turnover, maker orders where possible, near-zero fixed costs.
4. **Survival.** Volatility targeting, fractional Kelly, kill switches, auto-demotion. Staying alive is what lets returns compound.

## 1. Non-negotiable rules

- Live trading needs a human approval (typed confirmation in the CLI or Telegram) for every promotion from paper to live and for every capital increase.
- **Agents can never:**
  - raise risk limits
  - promote a strategy to live
  - edit the jurisdiction profile
  - touch API keys
  - withdraw funds
- **API keys:**
  - trade-only, withdrawals disabled
  - IP-whitelisted wherever the venue supports it
  - stored in an encrypted secrets store, never in git
- **Jurisdiction enforcement:** the active jurisdiction profile decides which venues and instruments can trade. Pre-trade risk rejects anything outside it. The system never tries to get around a venue's geoblock.
- **Logging:** every experiment variant is logged with its parameters, data window and result. The trial count feeds the Deflated Sharpe calculation.
- **Determinism:** backtests must be reproducible from a seed, a data snapshot ID and a code commit hash.

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Language and tooling | Python 3.12, `uv`, `ruff`, `pyright` (strict on core), `pytest`, `hypothesis`, pre-commit, GitHub Actions | Modern, fast, typed |
| Trading engine | **NautilusTrader** (Rust core) for event-driven backtest **and** live, with the same strategy code in both | Removes backtest/live mismatch. Adapters exist for Binance, Bybit, Hyperliquid, IBKR, Polymarket |
| Research | `polars`, `vectorbt` (fast parameter sweeps), `numpy`, `scipy`, `statsmodels` | Speed for wide sweeps before event-driven confirmation |
| Data lake | Parquet in a Nautilus `ParquetDataCatalog`, plus DuckDB for ad-hoc SQL | Free, fast, point-in-time |
| State DB | Postgres 16 | Orders, fills, positions, PnL, strategy registry, experiment log, approvals, audit log |
| India executor | Thin custom service on the **Upstox** Python SDK, implementing the same `ExecutionVenue` interface | Nautilus has no Indian broker. India sleeve is monthly and low-frequency |
| Crypto venues | Binance (spot and futures, where licensed for the user's jurisdiction), **Hyperliquid** (official SDK and Nautilus adapter), CCXT for anything else | Liquidity plus on-chain perps |
| US equities | IBKR via Nautilus adapter (live), Alpaca paper for development | IBKR accepts most countries |
| Prediction markets | Polymarket Gamma/CLOB **read-only** feed by default. Execution adapter exists but is disabled unless the jurisdiction profile allows it | Legal status varies by country |
| External agents | Fere AI adapter as a **signal source** if an API is available, benchmarked like any strategy | No unvalidated capital allocation |
| Control plane | `mm` CLI (Typer), Textual TUI dashboard, FastAPI internal API, **MCP server** exposing the system to Claude and the agent swarm | "One terminal", controllable from Claude |
| Agents | Claude Agent SDK, run as scheduled jobs (off the hot path) | LLMs for research and ops, never the order path |
| Alerts and approvals | Telegram bot (alerts, `/status`, `/pnl`, `/pause`, `/kill`, approval prompts) | Phone control while travelling |
| Secrets | `sops` + `age` encrypted files, or 1Password CLI | Nothing plaintext |
| Deploy | Docker Compose. Node A: main (cheapest reliable VPS, e.g. Oracle Cloud free tier or Hetzner, in a region close to the venues). Node B: India executor on a Mumbai static-IP VPS, **only when the India sleeve goes live** (SEBI requires a static IP) | Fixed-cost target **≤ $5/month** while capital is under $2k |
| Observability | Structured JSON logs, Prometheus metrics, a Grafana dashboard (optional), daily report | Know when something breaks |

Before writing adapter code, verify current library versions and APIs against official docs. Several changed in 2026: Polymarket CLOB v2 and `py-clob-client-v2`, Hyperliquid SDK, Upstox SDK, the SEBI April 2026 algo rules.

## 3. Repository layout

```
moneymaker/
  pyproject.toml  uv.lock  .pre-commit-config.yaml  docker-compose.yml
  SPEC.md  CLAUDE.md  README.md
  config/
    base.yaml                 # global defaults
    risk.yaml                 # account and sleeve limits (human-edited only)
    jurisdictions/
      uae.yaml  singapore.yaml  thailand.yaml  india.yaml
    venues/*.yaml             # fees, min sizes, rate limits, tick sizes
    strategies/*.yaml         # params per strategy and stage (research/paper/live)
  src/mm/
    core/          # domain types: Instrument, Order, Fill, Position, Money, Clock, events
    data/          # ingestion jobs, catalog, point-in-time universes, data-quality checks
    costs/         # per-venue cost models: fees, spread, slippage, funding, taxes
    research/      # vectorbt sweeps, feature library, notebooks->scripts
    validation/    # walk-forward, DSR, PBO/CSCV, bootstrap, gates
    strategies/    # Nautilus strategies (S1..S6), each with a typed config
    risk/          # pre-trade checks, portfolio limits, kill switch, reconciliation
    execution/     # venue adapters glue, india_executor, order router
    portfolio/     # sleeve allocator, vol targeting, fractional Kelly, rebalancing bands
    control/       # mm CLI, TUI, FastAPI, MCP server, Telegram bot, approvals
    agents/        # agent roles, prompts, permissions, schedules
    reporting/     # daily/weekly reports, tearsheets
  tests/  (unit, property, integration with testnets, no-lookahead tests)
  infra/  (Dockerfiles, compose, deploy scripts, sops config)
```

## 4. Jurisdiction profiles

Every profile lists the allowed venues, instruments and limits. The `active` profile is set by the human only.

```yaml
# config/jurisdictions/uae.yaml (example; confirm with local counsel before live)
name: uae
tax_note: personal investment gains excluded under Cabinet Decision 49/2023
venues:
  binance: {spot: true, perps: true}          # via the entity licensed for the user's KYC
  hyperliquid: {perps: true}
  ibkr: {stocks: true, etfs: true}
  upstox: {mode: nri, intraday_equity: false, delivery: true}   # NRI rules
  polymarket: {read: true, trade: false}       # flip only after legal sign-off
max_leverage: 1.0
```

`singapore.yaml` and `thailand.yaml` set `polymarket.trade: false`, because Polymarket marks both as close-only. They also disable venues that don't serve those countries.

## 5. Strategy book v1

All strategies start in `research`. Parameters live in YAML. Every sweep is logged.

**S1. Crypto trend ensemble (core sleeve)**
- **Universe:** BTC and ETH, plus the top N perps by 90-day median volume (N ≤ 10, point-in-time).
- **Signal:** an ensemble of Donchian breakouts (lookbacks 20/55/100 days) and moving-average crossovers, averaged to a score between 0 and 1. Long-only or flat.
- **Sizing:** volatility target of 30% a year for the sleeve, inverse-vol weights, capped at 1.0x notional.
- **Trading:** daily evaluation. Trade only if the target changes by more than 25% of the position (rebalancing band). Maker orders with a timeout, then taker.
- **Venue:** Binance spot or Hyperliquid perps at 1x.

**S2. Funding carry (BTC/ETH)**
- **Entry:** predicted annualised funding above 15% for 3 or more intervals, and the basis is sane.
- **Position:** long spot and short perp at equal notional.
- **Exit:** funding below 5% annualised, a basis blowout, or an ADL or depeg alarm.
- **Safety:** margin buffer of 50% or more, and minimum hold of 7 days (fee break-even).
- **Monitoring:** auto-deleveraging queue position, stablecoin pegs, venue health.

**S3. Cross-venue funding spread (mid-cap perps). Research → paper first.**
- **Position:** long the perp on the venue with low funding, short the same coin where funding is high, delta-neutral.
- **Entry:** spread minus 2× round-trip fees above a threshold.
- **Safety:** per-coin and per-venue caps, liquidation-distance monitor, auto-unwind on a venue incident.
- This is the capacity-constrained niche we expect funds to ignore.

**S4. India factor ETF rotation (NRI-compatible)**
- **Rebalance:** monthly.
- **Holdings:** low-volatility ETF and momentum ETF.
- **Trend filter:** if Nifty is below its 200-day MA, rotate to a liquid or gold ETF.
- **Order rules:** delivery orders only, well under 10 orders/sec.
- **Venue:** Upstox. Runs on node B with a static IP.

**S5. US ETF trend (paper until account > $2k)**
- SPY/QQQ/TLT/GLD/IEF with a trend filter and volatility weights, rebalanced monthly.
- IBKR. The $1 minimum commission makes it uneconomic below about $2k.

**S6. Overlays and experimental features.** Each must pass the gates as an improvement to a base strategy.
- Funding-regime contrarian filter on S1.
- Polymarket implied probabilities, read-only, as macro and event features.
- Fere AI signals, if API access exists.
- LLM-derived features from news, using a timestamp-safe pipeline only.

## 6. Validation and promotion gates

| Gate | Requirement |
|---|---|
| **G0 code** | Unit and property tests pass. A no-lookahead test (shift future data and check the signal doesn't change). Cost model attached. Deterministic replay |
| **G1 backtest** | All available history across several regimes (crypto from 2019 where data allows). Walk-forward out-of-sample. **Deflated Sharpe probability ≥ 0.95** using the logged trial count. **PBO ≤ 0.20**. OOS net Sharpe ≥ 0.7 for directional strategies or ≥ 1.0 for carry. Max drawdown within the sleeve budget. Turnover and costs reported. Event-driven Nautilus run within 10% of the vectorbt result |
| **G2 paper** | Testnet or paper for ≥ 8 weeks **and** ≥ 50 trades (or 3 months for monthly strategies). Live-vs-backtest tracking error within tolerance. Zero unhandled operational incidents. **Human approval to exit** |
| **G3 micro-live** | Notional capped (start at $25-50 per sleeve) for ≥ 4 weeks. **Human approval to exit** |
| **G4 scale** | Capital steps of at most 2× per step, at least 4 weeks apart. Auto-demote to paper if drawdown exceeds 1.5× the expected max, or if the live Sharpe's lower confidence bound falls below 0 |

## 7. Risk system

- **Account:**
  - Daily loss above 3% → halt new entries.
  - Drawdown from peak above 20% → flatten all and halt. Human restart only.
- **Sleeve:** drawdown above 25% → flatten and demote that sleeve.
- **Pre-trade checks:**
  - jurisdiction allow-list
  - instrument allow-list
  - max order notional
  - position limits
  - leverage ≤ profile max
  - venue minimum size
  - rate limits
  - **exit feasibility** (book depth ≥ 20× order size, and the instrument is actually sellable)
  - fat-finger price band
- **Kill switch:** `mm kill`, Telegram `/kill`, and the MCP `kill` tool all cancel every order and optionally flatten. A dead-man heartbeat cancels open orders if the main loop stalls.
- **Reconciliation:** compare positions and balances with every venue every 5 minutes. Halt on any mismatch.
- **Sizing:** volatility targeting per sleeve, with a fractional Kelly cap at 0.25 to 0.5 of estimated Kelly after haircutting the edge by 50%.

## 8. Control plane ("one terminal")

`mm` CLI:

```
mm status | pnl | positions | orders | risk
mm data sync [--venue] [--since]
mm research sweep <strategy> | mm backtest <strategy> [--walkforward]
mm gate <strategy>            # runs G0/G1 and prints the gate report
mm paper start|stop <strategy>
mm promote <strategy> --to micro|live   # requires typed confirmation + Telegram approve
mm pause|resume <strategy|all>
mm kill [--flatten]
mm jurisdiction show|set <profile>       # human only
mm report daily|weekly
mm tui                       # live dashboard
```

The **MCP server** exposes the read tools to Claude: status, pnl, positions, run_backtest, gate_report, list_experiments, propose_strategy. It exposes `pause` and `kill` as safe write tools. It also has `request_promotion`, which only *creates* an approval request that the human must confirm. There is no tool that changes limits, keys or jurisdiction.

## 9. Agent swarm (Claude Agent SDK)

| Agent | Schedule | Can | Cannot |
|---|---|---|---|
| **Research** | Daily | Read data, write new strategy variants on a branch, run sweeps and backtests, log experiments | Touch live config, risk.yaml or keys |
| **Validator** | On every research commit | Run the gates, write gate reports, reject | Edit strategy code (separation of duties) |
| **Risk Sentinel** | Every 5 min (rule-based) plus a daily LLM review | Read everything, pause or kill | Resume, promote, or raise limits |
| **Ops** | Hourly | Health checks, restart crashed services, rotate logs, reconcile | Change strategies or limits |
| **Reporter** | Daily 08:00 user local time | Write the daily brief (PnL, risk, gate pipeline, incidents) to Telegram and the dashboard | Write anything else |

LLM calls are batched and cached. Cost budget: **≤ $10/month** in the micro-capital phase, tracked in the daily report.

## 10. Capital plan (starting ≈ ₹10,000 ≈ $115)

- **Phase A (weeks 0-8):** $0 at risk. Build, backtest, paper trade on testnets and paper accounts.
- **Phase B (micro-live, after G2 plus approval):**
  - S1 crypto trend: 50%
  - S2 carry: 30%, only while the entry condition holds, otherwise cash
  - S4 India ETF rotation: 20%, only once the NRI account and node B exist
  - S3, S5, S6 stay in paper
- **Phase C:** add outside capital only after a 3-month live record shows tracking within tolerance. The system's main job at this size is to **earn the right to scale**.

At ₹10k, even an excellent year is a few thousand rupees. The product is a verified, scalable process.

## 11. Build phases (each ends with a demo and a report)

1. **Foundation:** repo, tooling, CI, config system, secrets, Postgres schema, domain types, jurisdiction enforcement, `mm` CLI skeleton, Telegram alerts.
2. **Data:** ingestion for Binance and Hyperliquid (OHLCV, funding, OI), yfinance/Tiingo for US ETFs, NSE bhavcopy and Upstox historical data, Polymarket Gamma (read-only). Data-quality checks and point-in-time universes.
3. **Research and validation:** cost models, vectorbt sweeps, walk-forward engine, DSR, PBO/CSCV, experiment log, gate reports.
4. **Strategies S1, S2, S4** in Nautilus, plus backtests through G1. Publish gate reports.
5. **Paper trading:** testnet and paper adapters, india_executor in Upstox sandbox, reconciliation, risk system, kill switch, dead-man switch.
6. **Control plane:** TUI, FastAPI, MCP server, approval workflow.
7. **Agent swarm and daily reporting.**
8. **Deploy:** Docker Compose on node A. Node B only when India goes live.
9. **S3, S5, S6** through the pipeline.
