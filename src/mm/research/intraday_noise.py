"""SPY/QQQ "noise area" intraday momentum (Zarattini, Aziz and Barbon, 2024).

Rules, per trading day t and minute-of-session tau (minutes since the 09:30 ET open):
- move(t, tau) = |close(t, tau) / open(t) - 1|; sigma(t, tau) = mean of move over the previous
  `lookback` days at the same tau (days before t only).
- Upper = max(open_t, close_{t-1}) * (1 + sigma), Lower = min(open_t, close_{t-1}) * (1 - sigma).
- At each decision time (every `step` minutes from 10:00): long if close > Upper, short if
  close < Lower. An open long is closed at a decision time when close < max(Upper, VWAP)
  (mirror for shorts). Everything is flat at the close (last bar of the session).
- Size: equity * min(max_leverage, target_daily_vol / sigma_daily), where sigma_daily is the
  std of the previous 14 daily close-to-close returns. Shares are whole numbers.
- Costs: commission per share + slippage per share on every fill.

The paper reports net Sharpe ~1.3 on SPY over 2007-2024. NOTHING HERE HAS BEEN BACKTESTED ON
REAL DATA: no free minute history long enough is reachable without an API key. The code runs on
any `MinuteBarSource`; `AlpacaMinuteSource` needs MM_SECRET_ALPACA_KEY_ID/_SECRET (free paper
account; the IEX feed is free, SIP history is delayed 15 minutes on the free plan).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import numpy as np
import polars as pl

from mm.data.http import PoliteClient
from mm.secrets import get_secret

MINUTE_SCHEMA = {
    "ts": pl.Datetime("ms", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}
SESSION_MINUTES = 390  # 09:30-16:00 ET


class MinuteBarSource(Protocol):
    def bars(self, symbol: str, start: date, end: date) -> pl.DataFrame:
        """Regular-session 1-minute bars with columns of MINUTE_SCHEMA plus `day` (session date)
        and `tau` (minutes since the open, 0..389). Split/dividend adjusted."""
        ...


@dataclass(frozen=True, slots=True)
class NoiseConfig:
    lookback: int = 14
    step: int = 30  # minutes between decision times
    first_decision: int = 30  # 10:00 ET
    target_daily_vol: float = 0.02
    max_leverage: float = 4.0
    commission_per_share: float = 0.0035
    slippage_per_share: float = 0.001
    capital: float = 100_000.0


def _sigma_table(bars: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """sigma(day, tau): mean |close/open_day - 1| over the previous `lookback` days at tau."""
    day_open = bars.group_by("day").agg(pl.col("open").sort_by("tau").first().alias("day_open"))
    mv = bars.join(day_open, on="day").with_columns(
        (pl.col("close") / pl.col("day_open") - 1).abs().alias("move")
    )
    return (
        mv.sort("tau", "day")
        .with_columns(
            pl.col("move")
            .shift(1)
            .rolling_mean(lookback, min_samples=lookback)
            .over("tau")
            .alias("sigma")
        )
        .select("day", "tau", "sigma")
    )


def backtest(bars: pl.DataFrame, cfg: NoiseConfig | None = None) -> pl.DataFrame:
    """Daily results: day, ret (net, on capital), gross, costs, trades, exposure.

    Equity is reset to `capital` each day for sizing (no compounding inside the backtest), which
    makes daily returns comparable across the sample.
    """
    cfg = cfg or NoiseConfig()
    bars = bars.sort("ts")
    sig = _sigma_table(bars, cfg.lookback)
    daily = (
        bars.group_by("day")
        .agg(
            pl.col("open").sort_by("tau").first().alias("o"),
            pl.col("close").sort_by("tau").last().alias("c"),
        )
        .sort("day")
        .with_columns(pl.col("c").shift(1).alias("prev_c"))
        .with_columns((pl.col("c") / pl.col("prev_c") - 1).alias("r"))
        .with_columns(pl.col("r").shift(1).rolling_std(14, min_samples=14).alias("vol14"))
    )
    full = bars.join(sig, on=["day", "tau"], how="left").join(
        daily.select("day", "o", "prev_c", "vol14"), on="day", how="left"
    )
    out: list[dict[str, Any]] = []
    for (day,), g in full.sort("day", "tau").group_by(["day"], maintain_order=True):
        g = g.sort("tau")
        prev_c, vol14 = g["prev_c"][0], g["vol14"][0]
        if prev_c is None or vol14 is None or g["sigma"].null_count() == g.height or vol14 <= 0:
            continue
        o = float(g["o"][0])
        up_ref, lo_ref = max(o, float(prev_c)), min(o, float(prev_c))
        lev = min(cfg.max_leverage, cfg.target_daily_vol / float(vol14))
        close = g["close"].to_numpy()
        vol = g["volume"].to_numpy()
        tau = g["tau"].to_numpy()
        sigma = g["sigma"].fill_null(np.inf).to_numpy()
        typical = (g["high"].to_numpy() + g["low"].to_numpy() + close) / 3
        cum_pv = np.cumsum(typical * vol)
        cum_v = np.cumsum(vol)
        vwap = np.where(cum_v > 0, cum_pv / np.maximum(cum_v, 1e-12), close)
        pos = 0  # shares, signed
        cash_pnl, costs, trades = 0.0, 0.0, 0
        last_px = close[0]
        exposure = 0.0
        for k in range(len(close)):
            px = close[k]
            cash_pnl += pos * (px - last_px)
            last_px = px
            exposure += abs(pos) * px
            is_last = k == len(close) - 1
            decide = tau[k] >= cfg.first_decision and (tau[k] - cfg.first_decision) % cfg.step == 0
            target = pos
            if is_last:
                target = 0
            elif decide:
                ub = up_ref * (1 + sigma[k])
                lb = lo_ref * (1 - sigma[k])
                if (pos > 0 and px < max(ub, vwap[k])) or (pos < 0 and px > min(lb, vwap[k])):
                    target = 0
                if px > ub:
                    target = int(cfg.capital * lev / o)
                elif px < lb:
                    target = -int(cfg.capital * lev / o)
            if target != pos:
                qty = abs(target - pos)
                costs += qty * (cfg.commission_per_share + cfg.slippage_per_share)
                trades += 1
                pos = target
        out.append(
            {
                "day": day,
                "gross": cash_pnl / cfg.capital,
                "costs": costs / cfg.capital,
                "ret": (cash_pnl - costs) / cfg.capital,
                "trades": trades,
                "avg_exposure": exposure / len(close) / cfg.capital,
            }
        )
    return pl.DataFrame(out)


# --- Sources ----------------------------------------------------------------------------------


def _session(df: pl.DataFrame) -> pl.DataFrame:
    """Keep 09:30-15:59 New York time and add `day` and `tau`."""
    ny = df.with_columns(pl.col("ts").dt.convert_time_zone("America/New_York").alias("ny"))
    mins = pl.col("ny").dt.hour().cast(pl.Int32) * 60 + pl.col("ny").dt.minute().cast(pl.Int32)
    return (
        ny.with_columns((mins - 570).alias("tau"), pl.col("ny").dt.date().alias("day"))
        .filter((pl.col("tau") >= 0) & (pl.col("tau") < SESSION_MINUTES))
        .drop("ny")
        .sort("ts")
    )


class SyntheticMinuteSource:
    """Deterministic random-walk minute bars for tests. Optional intraday drift persistence lets
    tests check that the strategy makes money when momentum exists and loses costs when not."""

    def __init__(self, seed: int = 0, momentum: float = 0.0, vol_per_min: float = 0.0006):
        self.seed, self.momentum, self.vol = seed, momentum, vol_per_min

    def bars(self, symbol: str, start: date, end: date) -> pl.DataFrame:
        rng = np.random.default_rng(self.seed)
        rows: list[dict[str, Any]] = []
        px = 400.0
        d = start
        while d <= end:
            if d.weekday() < 5:
                px *= float(np.exp(rng.normal(0, 0.004)))  # overnight gap
                open_utc = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)  # 09:30 EST
                drift = rng.normal(0, self.momentum)
                for m in range(SESSION_MINUTES):
                    o = px
                    px *= float(np.exp(drift + rng.normal(0, self.vol)))
                    hi, lo = max(o, px) * 1.0001, min(o, px) * 0.9999
                    rows.append(
                        {
                            "ts": open_utc + timedelta(minutes=m),
                            "open": o,
                            "high": hi,
                            "low": lo,
                            "close": px,
                            "volume": 1000.0,
                            "day": d,
                            "tau": m,
                        }
                    )
            d += timedelta(days=1)
        return pl.DataFrame(rows).with_columns(pl.col("ts").dt.cast_time_unit("ms"))


class AlpacaMinuteSource:
    """Alpaca market data v2 (GET /v2/stocks/bars, 1Min, adjustment=all), paginated.

    Needs MM_SECRET_ALPACA_KEY_ID and MM_SECRET_ALPACA_SECRET. Keys go in headers only, never in
    URLs or logs. Free accounts: use feed="iex" (or "sip" for history older than 15 minutes).
    """

    URL = "https://data.alpaca.markets/v2/stocks/bars"

    def __init__(self, client: PoliteClient, feed: str = "sip") -> None:
        self.client, self.feed = client, feed

    def _pages(self, symbol: str, start: date, end: date) -> Iterator[list[dict[str, Any]]]:
        headers = {
            "APCA-API-KEY-ID": get_secret("alpaca_key_id").reveal(),
            "APCA-API-SECRET-KEY": get_secret("alpaca_secret").reveal(),
        }
        token: str | None = None
        while True:
            params: dict[str, str | int] = {
                "symbols": symbol,
                "timeframe": "1Min",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 10_000,
                "adjustment": "all",
                "feed": self.feed,
            }
            if token:
                params["page_token"] = token
            resp = self.client.get(self.URL, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            yield body.get("bars", {}).get(symbol, [])
            token = body.get("next_page_token")
            if not token:
                break

    def bars(self, symbol: str, start: date, end: date) -> pl.DataFrame:
        rows = [r for page in self._pages(symbol, start, end) for r in page]
        if not rows:
            return pl.DataFrame(schema=MINUTE_SCHEMA)
        df = pl.DataFrame(rows).select(
            pl.col("t").str.to_datetime(time_zone="UTC").dt.cast_time_unit("ms").alias("ts"),
            pl.col("o").cast(pl.Float64).alias("open"),
            pl.col("h").cast(pl.Float64).alias("high"),
            pl.col("l").cast(pl.Float64).alias("low"),
            pl.col("c").cast(pl.Float64).alias("close"),
            pl.col("v").cast(pl.Float64).alias("volume"),
        )
        return _session(df)
