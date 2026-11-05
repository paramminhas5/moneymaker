# Football: Dixon-Coles model vs bookmakers, v1 (5 Nov 2026). Research only.

**What it is.**
- **Model.** Dixon-Coles team strengths (attack, defence, home advantage, low-score correction rho), weighted by exponential time decay (xi), on the last 3 seasons, with a small ridge penalty.
- **Season simulation.** 10,000 Monte Carlo runs of the remaining fixtures.
- **Proposal queue.** Compares model probabilities with Polymarket prices and logs closing-line value. It never places orders.

Code: `src/mm/research/football/`, run with `scripts/run_football.py` and `scripts/football_vs_polymarket.py`.

**Data.** football-data.co.uk, top five leagues (EPL, Bundesliga, Serie A, La Liga, Ligue 1), 2012/13 to 2 Nov 2026: 25,693 matches. Pinnacle odds are present until mid-2025/26 and missing after; the market-average closing odds cover everything.

**Method (point in time).** Each league's model is refit every Monday on matches strictly before that Monday, then predicts that week. Out-of-sample from 2014/15: 22,041 matches. Odds are de-vigged proportionally. Brier is the 3-way sum of squared errors.

## Calibration (xi = 0.002, the best of 0.001 / 0.002 / 0.004)

On the 20,712 matches with both Pinnacle prices:

| Forecaster | Brier | Log loss |
|---|---|---|
| Pinnacle closing odds | **0.5727** | **0.9641** |
| Pinnacle early odds (days before kick-off) | 0.5742 | 0.9664 |
| Dixon-Coles model | 0.5887 | 0.9892 |

On the 12,911 matches with market-average closing odds (2019 onward): average close 0.9700 log loss vs model 0.9949.

**The model is clearly worse than the closing line and worse than Pinnacle's early line.** That is the normal result for a goals-only model. Bookmakers price in injuries, line-ups, motivation and fixture congestion; the model sees none of it.

## Hypothetical value bets (9 variants, family `football_dc_v1`)

Rule: bet 1% flat at Pinnacle's early price when model EV exceeds the edge threshold (2%, 5% or 10%), at most one outcome per match.

| xi | Edge | Bets | ROI per bet | Mean CLV | Bets with positive CLV |
|---|---|---|---|---|---|
| 0.001 | 2% | 18,102 | -6.0% | -2.6% | 35% |
| 0.002 | 5% | 15,354 | -7.2% | -2.6% | 35% |
| 0.004 | 10% | 11,913 | -8.0% | -2.6% | 35% |

All nine are similar: `football_dc_grid.csv`. **The line moves against the model's bets two times in three**, and losses are larger than Pinnacle's ~2.5% margin. The model disagrees with the market on most matches, and the market is right.

**Gate G1** (`reports/gates/football_dc/G1_latest.md`): **FAILED** on every check. OOS Sharpe -1.55, DSR 0.000 with N = 18 trials (the run was repeated once on clean code), PBO 0.41, and the bankroll is wiped out at 1% flat stakes.

## Season simulation and Polymarket futures (5 Nov 2026, read-only)

`football_season_sim_2026.csv` has title, top-4 and bottom-3 probabilities for all five leagues. `football_vs_polymarket_2026.csv` compares them with live Polymarket asks for the EPL title, EPL top 4 and Ligue 1 title. Five proposals with an edge of at least 3 points went into `ledger/football_proposals.jsonl`:

| Market | Model | Polymarket ask |
|---|---|---|
| Arsenal EPL title | 74.7% | 70.0% |
| Man City EPL title | 22.2% | 11.0% |
| Man City EPL top 4 | 97.6% | 43.0% |
| Brighton EPL top 4 | 73.3% | 60.0% |
| PSG Ligue 1 title | 92.1% | 89.0% |

Treat these as a measurement, not a recommendation. The model is already known to be worse than bookmakers on single matches. The Man City gaps are almost certainly the market pricing something the model can't see: Polymarket has live markets on a Man City points deduction. That is exactly the human-in-the-loop veto case in the sleeve design (doc 12). The queue will record closing prices and outcomes. CLV after about 150 proposals decides whether the model, with Param's veto, adds anything.

## Proposal-queue design (`proposals.py`)

The queue is an append-only JSONL file: one line per state change.

1. **`propose`.** Logs the market, match, outcome, model probability, the YES ask as the entry price, and the edge. Only fires if the edge is at least the threshold (default 3 points).
2. **`record_close`.** Logs the last price before resolution or kick-off. CLV = close - entry.
3. **`settle`.** Logs the outcome and PnL per share.
4. **`summary`.** Reports mean CLV, the share with positive CLV, and PnL.

There is no order method, and Polymarket `prediction` is false in every jurisdiction profile.

**Still to build:**
- A scheduled job that refreshes futures prices and records closes.
- The ±2.5-point human nudge and veto, logged as separate books.
- Draw inflation and a market-blend model (model + odds) as pre-committed v2 variants.

## Verdict
The model does not beat bookmakers and fails the gate. Keep it in research. The season-futures proposal queue is the only honest next step: measure closing-line value with no money at risk.
