from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from mm.strategies.common import hysteresis_gate, trailing_stop


def _ts(n: int) -> list[datetime]:
    return [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)]


def test_hysteresis_gate_holds_state_inside_band() -> None:
    # MA of 3; price sits just above then just below the MA inside a 10% band: no flips.
    px = pl.Series([100.0, 100, 100, 120, 105, 95, 80, 95, 105])
    g = hysteresis_gate(px, 3, 0.10)
    assert g[:3] == [0.0, 0.0, 0.0]  # MA not ready / not above band
    assert g[3] == 1.0  # 120 > 106.7 * 1.1
    assert g[4] == 1.0  # inside band: keep
    assert g[6] == 0.0  # 80 < 93.3 * 0.9


def test_trailing_stop_exits_and_waits_for_reset() -> None:
    n = 8
    close = pl.DataFrame({"ts": _ts(n), "A": [100.0, 110, 120, 100, 125, 130, 130, 140]})
    target = pl.DataFrame({"ts": _ts(n), "A": [1.0, 1, 1, 1, 1, 0, 1, 1]})
    atr = pl.DataFrame({"ts": _ts(n), "A": [5.0] * n})
    out = trailing_stop(target, close, atr, mult=3.0)["A"].to_list()
    # peak 120 -> stop 105; close 100 at t=3 triggers. Stays flat at t=4 despite target 1.
    assert out[:3] == [1.0, 1.0, 1.0]
    assert out[3] == 0.0
    assert out[4] == 0.0
    assert out[5] == 0.0  # target reset to zero
    assert out[6] == 1.0  # fresh entry allowed
