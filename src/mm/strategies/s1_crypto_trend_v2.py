"""S1 v2: S1 base signal + BTC 200-day regime gate (with hysteresis) + ATR chandelier exit.

Pre-committed from external research (doc 09): stops buy drawdown, the 200d gate cuts max DD
15-35 points in every source, and a hysteresis band fixes the 69% whipsaw rate on raw crosses.
Only the ATR multiple is varied (2.5 / 3.0 / 3.5, the plateau reported in the literature).
Trials are logged to the SAME family as v1, so the Deflated Sharpe counts every S1 trial.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from mm.strategies import Spec, register
from mm.strategies.common import atr, hysteresis_gate, trailing_stop
from mm.strategies.s1_crypto_trend import load_data
from mm.strategies.s1_crypto_trend import signal as v1_signal

BTC = "BTCUSDT"


def signal(
    close: pl.DataFrame, params: dict[str, Any], *, bars: dict[str, pl.DataFrame]
) -> pl.DataFrame:
    base = v1_signal(close, params, bars=bars)
    gate = hysteresis_gate(close[BTC], int(params["gate_ma"]), float(params["gate_band"]))
    gate_s = pl.Series("g", gate)
    syms = [c for c in base.columns if c != "ts"]
    gated = base.with_columns([(pl.col(s) * gate_s).alias(s) for s in syms])
    atr_frame = atr(bars, close, int(params["atr_span"]))
    return trailing_stop(gated, close, atr_frame, float(params["atr_mult"]))


register(
    Spec(
        id="s1_crypto_trend_v2",
        kind="directional",
        family="s1_v1",  # shared with v1 on purpose: honest trial count for the DSR
        venue="binance",
        periods_per_year=365,
        signal=signal,
        load_data=load_data,
        base_params={
            "top_n": 10,
            "donchian": [20, 55, 100],
            "ma_pairs": [[10, 50], [20, 100], [50, 200]],
            "donchian_weight": 0.5,
            "threshold": 0.5,
            "vol_span": 30,
            "target_vol": 0.30,
            "band": 0.25,
            "gate_ma": 200,
            "gate_band": 0.03,
            "atr_span": 20,
            "atr_mult": 3.0,
        },
        sweep={"atr_mult": [2.5, 3.0, 3.5]},
        walkforward=(730, 182),
        cost_bps=12.0,
        notes=[
            "v1 signal + BTC 200d gate (+/-3% hysteresis) + ATR(20) chandelier exit",
            "Only atr_mult varied; trials share the s1_v1 family so the DSR counts all 57",
        ],
    )
)
