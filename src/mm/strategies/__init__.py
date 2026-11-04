"""Strategies. Each exposes a `Spec` the research pipeline runs; registry maps IDs to specs.

A strategy here is a pure function from a wide close frame (and optional extras) to a wide
target-weight frame, parametrised by a typed config. Nautilus live wrappers arrive in phase 5
and call the same signal code so backtest and live cannot diverge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import polars as pl

from mm.validation.gates import Kind

SignalFn = Callable[..., pl.DataFrame]


@dataclass(frozen=True, slots=True)
class Spec:
    id: str
    kind: Kind
    family: str  # experiment-log family: every sweep variant counts toward its DSR
    venue: str  # cost model + jurisdiction venue
    periods_per_year: float
    signal: SignalFn  # signal(close, params, **extras) -> weights frame
    load_data: Callable[[], dict[str, Any]]  # returns kwargs for signal + "close"
    base_params: Mapping[str, Any]
    sweep: Mapping[str, list[Any]]  # grid for the research sweep
    walkforward: tuple[int, int] = (730, 182)  # train, test periods
    costs: Literal["bps", "model"] = "bps"
    cost_bps: float = 10.0
    capital: float = 115.0
    notes: list[str] = field(default_factory=list[str])


_REGISTRY: dict[str, Spec] = {}


def register(spec: Spec) -> Spec:
    _REGISTRY[spec.id] = spec
    return spec


def _load_all() -> None:
    import mm.strategies.s1_crypto_trend
    import mm.strategies.s2_funding_carry
    import mm.strategies.s4_india_etf  # noqa: F401


def get(strategy_id: str) -> Spec:
    _load_all()
    if strategy_id not in _REGISTRY:
        raise KeyError(f"unknown strategy '{strategy_id}'; have {sorted(_REGISTRY)}")
    return _REGISTRY[strategy_id]


def all_ids() -> list[str]:
    _load_all()
    return sorted(_REGISTRY)
