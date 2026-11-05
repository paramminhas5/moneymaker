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
| 2 | Data pipeline | next |
| 3 | Research and validation engine | |
| 4 | Strategies S1, S2, S4 through gate G1 | |
| 5 | Paper trading | |
| 6 | Control plane: TUI, API, MCP, approvals | |
| 7 | Agent swarm | |
| 8 | Deploy | |

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
