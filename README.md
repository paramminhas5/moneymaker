# MONEYMAKER

A gated, multi-market automated trading system controlled from one terminal. Read
[SPEC.md](SPEC.md) for the design and [CLAUDE.md](CLAUDE.md) for the rules every agent follows.

Nothing trades real money until a strategy has passed backtest, paper and micro-live gates and
the owner approves it.

## Quick start

```bash
uv sync --all-extras
uv run mm db init
uv run mm status
uv run mm jurisdiction show uae
uv run pytest
```

Postgres for production-like runs: `docker compose up -d postgres`, then set `MM_DATABASE_URL`
from `.env.example`. Without it the system uses a local SQLite file in `var/`.

## Build status

| Phase | What | Status |
|---|---|---|
| 1 | Foundation: config, jurisdiction enforcement, risk checks, kill switch, DB, CLI, CI | done |
| 2 | Data pipeline | done |
| 3 | Research and validation engine | done |
| 4 | Strategies S1, S2, S4 through gate G1 | done (all fail G1; see reports/gates) |
| 5 | Paper trading | trend v2 on paper (approved by owner) |
| 6 | Control plane: TUI, API, MCP, approvals | |
| 7 | Agent swarm | |
| 8 | Deploy | |

## Strategies and research sleeves

Every strategy below is at stage `research` unless noted. Run `uv run mm strategies`,
`uv run mm backtest <id>` and `uv run mm gate <id>`. Reports: `reports/research/*.md`,
gate reports: `reports/gates/<id>/`.

| ID | What | G1 | Report |
|---|---|---|---|
| `s1_crypto_trend` | Donchian + MA ensemble, vol-targeted | fail | gates/s1_crypto_trend |
| `s1_crypto_trend_v2` | v1 + BTC 200d gate + ATR exit (**paper**, owner-approved) | fail (PBO, event-driven) | gates/s1_crypto_trend_v2 |
| `s2_funding_carry` | long spot / short perp funding carry | fail | gates/s2_funding_carry |
| `s4_india_etf` | India factor ETF rotation | fail | gates/s4_india_etf |
| `core_hold` | world + Nasdaq + India ETFs + BTC/ETH, each held above its 200d MA | fail (PBO, DD 27%) | research/core_hold_v1.md |
| `btc_dipbuy` | buy BTC after a -3% day, time exit | fail | research/btc_dipbuy_v1.md |
| `listing_fade` | short new USD-M perp listings for their first weeks, max 3 names | see report | research/listing_fade_v1.md |
| `football_dc` (research module) | Dixon-Coles + season sim + Polymarket CLV queue, no trading | fail | research/football_dc_v1.md |
| noise-area intraday (research module) | SPY/QQQ intraday momentum; needs Alpaca minute data | not run | research/intraday_noise_v1.md |
| theme calls (tracker) | `mm theme add/report`: owner's calls vs QQQ | n/a | research/theme_calls_v1.md |

Experiment trial counts live in the local experiment DB (`mm experiments list`); exports of the
families used in each report are in `reports/research/experiments_*.csv`.

## Layout

```
config/           base, risk (human only), jurisdictions (human only), venues, strategies
src/mm/core       domain types
src/mm/config     typed config loading
src/mm/risk       pre-trade checks, drawdown monitor, rate limiter
src/mm/db         schema, sessions, kill switch and pause state
src/mm/control    mm CLI and alerts
tests/            unit and property tests
```
