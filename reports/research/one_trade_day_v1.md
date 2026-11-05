# "One trade a day for 5-6%": backtest v1 (5 Nov 2026)

**Data.** Binance USD-M perp hourly bars, Jan 2020 to Oct 2026 (BTC, ETH; SOL from Sep 2020).

**Costs.**
- Hyperliquid taker fee of 4.5 bp plus 1 bp slippage on each side, and 5 bp extra on stops.
- Funding charged for the hours each trade is held.
- If an hourly bar touches both the take-profit and the stop, the stop is assumed to hit first.

**Grid.** 126 scenarios:
- 6 entry rules: always long at 00:00 UTC; follow the 20-day trend; buy the dip after a -3% day; chase after a +3% day; breakout long; breakout long or short.
- 7 exit/leverage combos: no TP or stop at 1x, plus TP +5% on the account with a stop at -2.5% or -5%, at 1x, 3x and 5x.
- Run on each of the 3 assets.

**Results.**
- **No scenario averages anywhere near 5% per trade.** The best average is **+0.47%** (BTC dip-buy, 254 trades).
- **The exact idea tested (TP +5%, stop -2.5%) loses money with every entry rule, at every leverage.** At 3x and 5x the account is wiped out in almost every case.
- The +5% target is hit on 12-33% of days. The stop is hit far more often.
- 12 of 126 scenarios have a positive CAGR. All 12 are 1x with no TP or stop, which makes them mostly long crypto. The best is ETH breakout-long: 19% CAGR with a 54% drawdown.
- **Buy-and-hold beat every scenario** over this period (BTC 42%/yr, ETH 52%/yr, SOL 74%/yr).
- **One round trip a day costs 33% a year in fees at 1x and 70% at 3x.** That is the core reason a daily trade struggles.

**Takeaway.** A daily-trade strategy has to beat about 0.1% a day in costs before it earns anything. The best rule found earns about 0.2-0.5% per trade gross of beta. The 5-6% a day target is 10-50x what the data shows.

Full grid: `one_trade_day_grid.csv`. The trials are logged in the experiment log as family `one_trade_day_v1`.
