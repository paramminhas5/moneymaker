# SPY/QQQ noise-area intraday momentum: implementation v1, NOT backtested (5 Nov 2026)

**Status: code and tests only. No results, by design.** A real backtest needs years of 1-minute SPY/QQQ bars. None is reachable for free from the build container without an API key:
- Yahoo's 1-minute endpoint only serves about the last 30 days.
- Alpaca's market-data API returns HTTP 401 without keys.
- Alpha Vantage's intraday history needs a personal key (the demo key covers one symbol).

Nothing here was fitted, swept or run on real prices, so there is nothing for the experiment log or the gate yet. The synthetic tests prove the code is correct, not that the strategy is profitable.

## What is built (`src/mm/research/intraday_noise.py`)
The Zarattini, Aziz and Barbon (2024) rules, as specified in the paper:
- **Noise area.** For each minute of the session, sigma = the average absolute move from the day's open at that minute over the previous 14 days. Upper bound = max(open, previous close) x (1 + sigma); lower bound = min(open, previous close) x (1 - sigma).
- **Signals.** Checked every 30 minutes from 10:00 ET. Long above the upper bound, short below the lower bound. A long is closed when price falls below max(upper bound, VWAP), mirrored for shorts. Everything is flat at the close.
- **Sizing and costs.** Size targets 2% daily volatility using the previous 14 daily returns, capped at 4x. Costs are $0.0035 per share commission plus $0.001 per share slippage.
- **Data interface.** `MinuteBarSource` is a protocol. `AlpacaMinuteSource` calls GET /v2/stocks/bars (1Min, adjustment=all, paginated by page_token, checked against Alpaca's API reference on 5 Nov 2026). Keys come from the secrets loader and go in headers only. `SyntheticMinuteSource` produces deterministic test data.

## Tests (`tests/test_intraday_and_themes.py`)
- **No lookahead.** sigma at day t uses only days before t: truncating the data leaves every earlier sigma unchanged.
- **Behaviour.** The strategy makes more on synthetic data with intraday drift persistence than on a pure random walk, and it pays costs on every fill.
- **Limits.** Exposure respects the leverage cap. Trades are bounded by the number of decision times.

## What Param needs to do
1. Create a free Alpaca account (paper is enough).
2. Store the keys as `MM_SECRET_ALPACA_KEY_ID` and `MM_SECRET_ALPACA_SECRET` (sops or GitHub Actions secrets, never in git).
3. Then the next step is: pull SPY and QQQ 1-minute bars from 2016 (the free plan should allow SIP history older than 15 minutes; if Alpaca refuses, `feed="iex"` works without a subscription but covers fewer trades), add the strategy to the gate as a `Spec` on daily returns, log the small pre-committed sweep (lookback 10/14/20, step 30/60), and run G1. The paper's own result (net Sharpe ~1.3 on SPY, 2007-2024) is the benchmark, not a promise.
