"""Run a strategy spec through G0 and G1: lookahead check, sweep, walk-forward, PBO, report."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from mm.config import load_settings
from mm.costs import cost_model_for
from mm.data.catalog import Catalog
from mm.research.backtest import BacktestResult, run_weights
from mm.research.lookahead import LookaheadError, assert_no_lookahead
from mm.strategies import Spec
from mm.validation.experiments import ExperimentLog, code_commit
from mm.validation.gates import GateReport, evaluate_g0, evaluate_g1
from mm.validation.metrics import FloatArray, sharpe, summarize
from mm.validation.pbo import pbo_cscv
from mm.validation.walkforward import make_folds, walk_forward_select


@dataclass(slots=True)
class PipelineResult:
    g0: GateReport
    g1: GateReport | None
    base: BacktestResult
    variants: list[dict[str, Any]]
    oos: FloatArray


def _grid(spec: Spec) -> list[dict[str, Any]]:
    keys = list(spec.sweep)
    out = []
    for combo in itertools.product(*(spec.sweep[k] for k in keys)):
        p = dict(spec.base_params)
        p.update(dict(zip(keys, combo, strict=True)))
        out.append(p)
    return out


def _run(spec: Spec, data: dict[str, Any], params: dict[str, Any]) -> BacktestResult:
    extras = {k: v for k, v in data.items() if k != "close"}
    close = data["close"]
    weights = spec.signal(close, params, **extras)
    kwargs: dict[str, Any] = {}
    if spec.costs == "model":
        kwargs["cost_model"] = cost_model_for(spec.venue)
        kwargs["capital"] = spec.capital
    else:
        kwargs["cost_bps"] = spec.cost_bps
    if "funding" in data:
        kwargs["funding"] = data["funding"]
    return run_weights(close, weights, **kwargs)


def run_pipeline(
    spec: Spec,
    log: ExperimentLog,
    *,
    progress: Callable[[str], None] = lambda _: None,
    max_variants: int | None = None,
) -> PipelineResult:
    settings = load_settings()
    cat = Catalog()
    snapshot = cat.snapshot_id()
    commit = code_commit()
    data = spec.load_data()
    close: pl.DataFrame = data["close"]
    extras = {k: v for k, v in data.items() if k != "close"}

    # G0 -------------------------------------------------------------------------------
    progress("G0: no-lookahead harness")
    try:
        assert_no_lookahead(
            lambda d: spec.signal(d, dict(spec.base_params), **_trim(extras, d)), close, n_cuts=5
        )
        no_la = True
    except LookaheadError as exc:
        progress(f"  LOOKAHEAD: {exc}")
        no_la = False
    base_a = _run(spec, data, dict(spec.base_params))
    base_b = _run(spec, data, dict(spec.base_params))
    deterministic = bool(np.allclose(base_a.net, base_b.net))
    g0 = evaluate_g0(
        spec.id,
        no_lookahead=no_la,
        tests_passed=True,
        cost_model=_cost_label(spec),
        deterministic=deterministic,
        data_snapshot=snapshot,
        code_commit=commit,
    )
    g0.save()
    if not g0.passed:
        return PipelineResult(g0, None, base_a, [], np.array([]))

    # Sweep (every variant logged) -----------------------------------------------------
    grid = _grid(spec)
    if max_variants:
        grid = grid[:max_variants]
    progress(f"G1: sweeping {len(grid)} variants")
    nets: list[FloatArray] = []
    variants: list[dict[str, Any]] = []
    for p in grid:
        res = _run(spec, data, p)
        s = summarize(res.net, spec.periods_per_year)
        log.log(
            strategy_id=spec.id,
            family=spec.family,
            params=p,
            data_snapshot=snapshot,
            metrics={
                **s.as_dict(),
                "sharpe_per_period": sharpe(res.net, annualize=False),
                "annual_turnover": res.annual_turnover,
            },
            commit=commit,
        )
        nets.append(res.net)
        variants.append(
            {
                "params": p,
                "sharpe": s.sharpe,
                "mdd": s.max_drawdown,
                "turnover": res.annual_turnover,
            }
        )

    # Walk-forward -----------------------------------------------------------------------
    m = np.column_stack(nets)
    first_valid = int(np.argmax(np.any(m != 0, axis=1)))  # skip warm-up where nothing trades
    m = m[first_valid:]
    train, test = spec.walkforward
    folds = make_folds(m.shape[0], train, test)
    progress(f"G1: walk-forward over {len(folds)} folds")
    wf = walk_forward_select(m, folds, spec.periods_per_year)
    pbo = pbo_cscv(m, n_blocks=10) if m.shape[1] >= 2 else None

    sleeve = settings.risk.sleeve(spec.id)
    g1 = evaluate_g1(
        spec.id,
        kind=spec.kind,
        oos_returns=wf.oos_returns,
        n_trials=log.n_trials(spec.family),
        trial_sharpes=log.trial_sharpes(spec.family),
        pbo=pbo,
        sleeve_max_dd=float(sleeve.max_drawdown_pct) / 100,
        event_driven_gap=None,  # Nautilus confirmation arrives in phase 5
        data_snapshot=snapshot,
        code_commit=commit,
        periods_per_year=spec.periods_per_year,
        annual_turnover=float(np.mean([v["turnover"] for v in variants])),
        annual_cost_drag=base_a.annual_cost_drag,
        walkforward_stability=wf.stability,
    )
    g1.notes.extend(spec.notes)
    g1.notes.append(
        f"Walk-forward: train {train} / test {test} periods, chose variants {wf.chosen}"
    )
    g1.notes.append("Event-driven confirmation not run: NautilusTrader harness is phase 5")
    g1.save()
    return PipelineResult(g0, g1, base_a, variants, wf.oos_returns)


def _cost_label(spec: Spec) -> str:
    if spec.costs == "model":
        return spec.venue
    if isinstance(spec.cost_bps, Mapping):
        return "per-symbol bps: " + ", ".join(f"{k} {v:g}" for k, v in spec.cost_bps.items())
    return f"{spec.cost_bps}bp flat"


def _trim(extras: dict[str, Any], d: pl.DataFrame) -> dict[str, Any]:
    """Cut every extra frame to the same ts range as the (truncated) close frame."""
    t_max = d["ts"].max()
    out: dict[str, Any] = {}
    for k, v in extras.items():
        if isinstance(v, pl.DataFrame) and "ts" in v.columns:
            out[k] = v.filter(pl.col("ts") <= t_max)
        elif isinstance(v, dict):
            out[k] = {kk: vv.filter(pl.col("ts") <= t_max) for kk, vv in v.items()}
        else:
            out[k] = v
    return out
