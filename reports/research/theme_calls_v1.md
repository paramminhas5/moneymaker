# Theme-call sleeve tracker v1 (5 Nov 2026)

**What it is.** A scorecard for Param's own theme calls (e.g. "semis on AI capex"). It decides, from evidence, whether a theme-call sleeve earns capital. It does not trade.

- **Ledger.** `ledger/theme_calls.csv` (committed, append-only): date, ticker, thesis, horizon in days (default 180).
- **Add a call.** `mm theme add SMH --thesis "AI capex keeps going" [--date 2026-11-05] [--horizon-days 180]`. Future dates are rejected.
- **Report.** `mm theme report` lists each call's return and QQQ's return over exactly the same dates, the excess, and the hit rate and mean and median excess across calls. Prices are daily adjusted closes from the lake, refreshed from Yahoo when stale.
- **No free fills.** A call is entered at the first close strictly after the call date, so a call made during the day never gets that day's close. A call is scored up to its horizon, then frozen as "closed". Calls with no price yet show as "pending".

**Status.** The ledger is empty. Calls must be Param's own; none were invented for him. Suggested bar before the sleeve gets money: at least 20 closed calls with a positive median excess vs QQQ and a hit rate above 55%. With fewer calls, luck and skill can't be told apart. Theme momentum as a *systematic* rule already lost to holding QQQ (`theme_momentum_v1.md`), so the bar is real.

Code: `src/mm/research/theme_calls.py`; tests in `tests/test_intraday_and_themes.py`.
