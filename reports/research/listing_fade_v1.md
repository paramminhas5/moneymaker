# Listing fade: backtest v1 (5 Nov 2026)

**Idea (doc 12, aggressive sleeve).** Most new tokens trade below their listing price within weeks. The plan was to short newly listed perps for their first weeks, at most 3 names, with a +50% stop.

**Data, free of survivorship bias.** Every Binance USD-M USDT perp in the public archive (`data.binance.vision`), delisted names included: 923 symbols. Listings after the archive start (Jan 2020) give the sample. Since mid-2025 Binance also lists TradFi perps (stocks, ETFs, metals, FX, pre-IPO names); those are excluded. They are identified by quiet weekends (a stock perp barely moves on Saturday and Sunday) plus an explicit list. That leaves **694 crypto listings**, 2020 to Oct 2026 (239 of them in 2025). First three months of daily bars and funding per listing (`scripts/fetch_listing_perps.py`). Listing day = first daily bar, known on that day.

## Base rates (from the day-1 close, before costs)

| Days after listing | Median return | Share lower | Mean return |
|---|---|---|---|
| 7 | -9.1% | 67% | -3.1% |
| 14 | -13.1% | 68% | +0.9% |
| 28 | -17.9% | 70% | +7.5% |
| 56 | -26.9% | 75% | -1.5% |

The thesis is right about the typical coin: 70% are lower after four weeks. But the mean is near zero or positive, because **23% of listings close at least 50% above the day-1 close at some point in their first 28 days**, and a few go up 5-10x (BLESS +532% in one day in Oct 2025). A short book holds the median but pays the mean, plus volatility drag on positions that move 100%+ a year.

## Two versions tested, 20 variants, all in family `listing_fade_v1`

**A. `listing_fade` Spec: stop checked on daily closes** (8 variants: delay 1/3 days, hold 14/28, stop +50% or none). Costs: 20 bp one-way plus actual funding.

| Variant (delay, hold, stop) | Full-sample result |
|---|---|
| best: 3, 28, +50% | -92% total, Sharpe 0.29 |
| worst: 1, 28, +50% and 1, 14, none | account below zero (equity < 0 at 1/3 weight) |

A close-based stop can't help against a coin that rips 500% intraday.

**B. Intraday stop-market orders** (`src/mm/research/listing_fade_stops.py`, 12 variants: delay 1/3, hold 14/28, stop +30/+50/+100%). The stop fills 10% beyond the stop price, or at the open on a gap. Same costs and funding.

| Delay | Hold | Stop | Trades | CAGR | Max DD | Sharpe |
|---|---|---|---|---|---|---|
| 1 | 28 | +50% | 238 | -49% | 99.5% | 0.01 |
| 1 | 28 | +100% | 214 | -49% | 99.6% | 0.04 |
| 1 | 14 | +50% | 350 | -57% | 99.9% | -0.17 |
| 3 | 14 | +30% | 377 | -78% | 100% | -0.87 |

Every variant loses 99%+. The full grid is in `listing_fade_grid.csv`; base rates per listing are in `listing_fade_base_rates.csv`. Tighter stops get hit constantly (new coins move 20-30% a day), and wider stops let the squeezes through. For the base variant (delay 1, hold 28, +50% stop), removing costs, stop slippage and funding raises the Sharpe from 0.01 to 0.43, but CAGR is still -13% because volatility drag on the short book is huge. There is a small gross edge, and realistic execution costs on new coins more than eat it. This decomposition is a diagnostic, not a logged variant.

## Gates: FAILED

- `listing_fade` (G1): OOS Sharpe -0.04, DSR 0.25, PBO 0.59, max DD 99.8%. Run with one uncommitted docs-only change (README); code identical to commit `42dc83f`.
- `listing_fade_stops` (G1): OOS Sharpe -0.14, DSR 0.07 (N = 20), PBO 0.39, max DD 99.8%. Commit `5113564`.

## Honest caveats
- **Borrow.** Perps need no borrow, so none was charged. Shorting spot instead is usually impossible for new coins. Funding was charged as it happened: new listings often pay negative funding, so shorts pay longs.
- **Delistings.** A coin that stops printing is covered at its last close. Real delisting settlement can differ.
- **Live venue.** Hyperliquid listings differ from Binance's (often earlier, thinner books). Not tested separately: Hyperliquid's candle API only keeps recent history.
- **TradFi filter.** The filter uses each perp's first 60 days to recover static metadata (instrument type). It is not used as a signal.

**Verdict: killed.** The aggressive sleeve should not run a listing fade in this form. The only variant worth a pre-committed v2 is a beta-hedged one (short the listing, long BTC at equal notional) with smaller size. Even then, the right tail makes a fixed-fraction short book fragile.
