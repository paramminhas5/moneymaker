"""G1 for research streams that are not `Spec` strategies (e.g. football bets): take a T x N
matrix of per-period returns (one column per logged variant), walk forward, PBO, gate report."""

from __future__ import annotations

import numpy as np

from mm.config import load_settings
from mm.validation.experiments import ExperimentLog
from mm.validation.gates import GateReport, Kind, evaluate_g1
from mm.validation.metrics import FloatArray
from mm.validation.pbo import pbo_cscv
from mm.validation.walkforward import make_folds, walk_forward_select


def gate_matrix(
    strategy_id: str,
    family: str,
    kind: Kind,
    matrix: FloatArray,
    log: ExperimentLog,
    *,
    periods_per_year: float,
    walkforward: tuple[int, int],
    data_snapshot: str,
    code_commit: str,
    notes: list[str] | None = None,
) -> GateReport:
    m = np.asarray(matrix, dtype=np.float64)
    first = int(np.argmax(np.any(m != 0, axis=1)))
    m = m[first:]
    folds = make_folds(m.shape[0], *walkforward)
    wf = walk_forward_select(m, folds, periods_per_year)
    pbo = pbo_cscv(m, n_blocks=10) if m.shape[1] >= 2 else None
    sleeve = load_settings().risk.sleeve(strategy_id)
    g1 = evaluate_g1(
        strategy_id,
        kind=kind,
        oos_returns=wf.oos_returns,
        n_trials=log.n_trials(family),
        trial_sharpes=log.trial_sharpes(family),
        pbo=pbo,
        sleeve_max_dd=float(sleeve.max_drawdown_pct) / 100,
        event_driven_gap=None,
        data_snapshot=data_snapshot,
        code_commit=code_commit,
        periods_per_year=periods_per_year,
        walkforward_stability=wf.stability,
    )
    g1.notes.extend(notes or [])
    g1.notes.append(f"Walk-forward train/test {walkforward}, chose variants {wf.chosen}")
    g1.notes.append("Event-driven confirmation not run: not applicable until a paper venue exists")
    return g1
