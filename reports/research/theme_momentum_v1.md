# "Buy what's buzzing, sell at the first downtrend": theme momentum backtest v1 (5 Nov 2026)

**Idea tested.** Find the themes the market is piling into (AI chips, energy, uranium, defence,
crypto miners, and so on), buy the leaders, and sell at the first sign of a downtrend.

**Data.** Daily adjusted prices from July 2001 to Nov 2026 for 44 US sector, theme and commodity
ETFs, plus SPY and QQQ. The theme list was picked with hindsight (uranium, solar, semis and
lithium are themes we already know became hot), so the test is biased in the idea's favour.

**Rules.** Every week, take the ETFs trading above their 200-day average, rank them by a blend of
3-, 6- and 12-month returns, and hold the top 3 or 5. "First downtrend" exit: sell a holding the
day it closes below its 50-day average, and stay in cash until the next weekly ranking. Costs: 5 bp
per side.

| Strategy | CAGR | Max DD | 2020-26 CAGR |
|---|---|---|---|
| QQQ buy & hold | **12.1%** | 56% | **19.6%** |
| SPY buy & hold | 9.5% | 55% | 15.2% |
| Themes top 3, sell at first downtrend | 5.4% | 50% | 17.4% |
| Themes top 5, 200-day only | 6.1% | 44% | 9.5% |
| Sectors top 5, 200-day only | 8.3% | **23.5%** | 9.0% |
| Sectors top 3, sell at first downtrend | 4.9% | 23% | 8.7% |

**Findings.**
1. **Chasing themes did not beat simply holding the Nasdaq**, even with a universe picked in hindsight.
2. **"Sell at the first downtrend" (a close below the 50-day average) lowered returns in every
   version.** Hot themes dip below their 50-day average constantly. Each exit and re-entry pays
   costs and misses the rebound.
3. **The 200-day filter on sectors is the useful piece.** It cut the maximum drawdown from 55% to
   about 23% for a little less return.
4. **Hyped themes held outright were brutal.** Uranium (URA) -4.4%/yr with a -94% drawdown since
   2010. Solar (TAN) -7.4%/yr, -95% since 2008. AI "shovels" (SMH) +13.5%/yr, but with a -71% drawdown.
5. This matches Ben-David, Franzoni, Kim & Moussawi (RFS 2023). Specialised ETFs launched after a
   theme gets hot underperform by about 6%/yr over their first five years, because the underlying
   stocks are already overvalued by the time the theme is visible.

8 variants logged as family `theme_mom_v1`.
