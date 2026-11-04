# CLAUDE.md: rules for any AI agent working in this repo

Read SPEC.md first. It is the source of truth. If something you want to do conflicts with SPEC.md, stop and ask.

## Hard rules
- Never place a live (real-money) order, enable a live venue, or change `stage: live` in any config. Only the human owner does that through `mm promote`.
- **Never edit these files:**
  - `config/risk.yaml`
  - `config/jurisdictions/*`
  - the `active` jurisdiction setting
  - any secrets file
- **Never weaken these:**
  - a risk check
  - a validation gate
  - a no-lookahead test
- **Secrets:** never commit them, never print them in logs, never put them in URLs. Use the secrets loader.
- **Geoblocks:** never write code that gets around a venue's geoblock (VPN routing, proxies, spoofed location). Venues allowed by the active jurisdiction profile are the only ones that trade.
- Use testnets, sandboxes and paper accounts for every integration test.

## Engineering standards
- Python 3.12, `uv`, `ruff`, `pyright` strict in `src/mm/core`, `risk`, `execution`, `portfolio`.
- Every strategy has:
  - a typed config
  - unit tests
  - a no-lookahead test
  - a cost model
  - a gate report before it moves stage
- **Backtests:**
  - Reproducible (seed + data snapshot ID + commit hash recorded).
  - Log every research variant to the experiment log. Under-reporting trials breaks the Deflated Sharpe calculation and is treated as a bug.
- **APIs:** check current library and API docs before writing an adapter. Exchange APIs changed a lot in 2026. Pin versions in `uv.lock`.
- **Tests:** keep the hot path deterministic and LLM-free. LLMs are for research, ops and reporting only.
- **Commits:** small and focused, with conventional messages. Open a PR per build phase with a short report: what works, gate results, known gaps.

## When unsure
Prefer the safer option, write down the assumption in the PR, and continue. Ask the human only for things that can't be undone or that touch money.
