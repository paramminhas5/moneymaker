# Polymarket bonding backtest v1 (5 Nov 2026): FAILED, sleeve not funded

**Question.** Does buying the side of a market that trades at 95-98.5c (or 97-99c) and holding to
resolution make money after costs?

**Data.** 3,948 resolved binary markets, Nov 2025 to Oct 2026: the top 100 by volume ending on
every 4th day. Prices are 10-minute CLOB history for the last 7 days before close, for both sides
(5.8M points). Public Gamma and CLOB APIs.

**Method.** The trigger is outcome-blind: scan both sides and buy whichever first trades inside the
band, filled as a resting maker bid at the printed price plus 0.2c, with zero fee. Hold to
resolution plus 0.1 days. Only one position per event, because legs of the same match are
correlated. Each position is 3% of equity. 16 variants were pre-committed and all are logged
(family `pm_bond_v1`).

**Result.** All 16 variants lose money.

| Variant | Trades | Win rate | Mean per trade | Annualised | Max DD |
|---|---|---|---|---|---|
| 95-98.5c, any time ≤7d before close | 1,352 | 93.8% | −3.1% | −75% | 74% |
| 95-98.5c, ≥6h before close (no in-play) | 285 | 92.6% | −4.0% | −31% | 32% |
| 97-99c, price held ≥24h first | 152 | 94.7% | −4.0% | −24% | 19% |
| Non-sports only, held ≥24h | 129 | 90.7-93.8% | −5 to −7% | −25 to −38% | 20-26% |

At an average entry of ~97c you need a win rate above 97% to break even. Realised win rates were
91-95% in every category, volume tercile and filter tried.

**Why it fails.** It is adverse selection. A side that is going to win tends to jump straight
through the band (on a goal, a data release or a result), so a resting bid never gets filled. A
side that is going to lose spends time in the band on its way down, and that is exactly when the
bid fills. The published positive results (Gebele & Matthes: median 6.2% APY) come from bidding
0.999 *after* the outcome is known, with 1-2 hour holds. That is a latency race against sweeper
bots, not this trade.

**Bias checks.**
- Losses are not concentrated in high-volume markets, so the volume-ranked sample does not
  explain the result.
- Football with a 24-hour stability filter went 30/30 (+3.4%). That is n=30 inside a 16-variant
  search: noise, not evidence.

**Decision.** Do not fund bonding. Its $1,000 moves to the cash sleeve until another sleeve passes
its gate.
