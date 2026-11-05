"""Experiment log. Every variant tried is recorded; its count is the N in the Deflated Sharpe."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import numpy as np
from sqlalchemy import Engine, func, select

from mm.db.schema import Experiment
from mm.db.session import session_scope
from mm.validation.metrics import FloatArray


def code_commit() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        )
        dirty = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        return out.stdout.strip()[:40] + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class ExperimentLog:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def log(
        self,
        *,
        strategy_id: str,
        family: str,
        params: dict[str, Any],
        data_snapshot: str,
        metrics: dict[str, float],
        seed: int = 0,
        commit: str | None = None,
    ) -> int:
        with session_scope(self.engine) as s:
            row = Experiment(
                strategy_id=strategy_id,
                family=family,
                params=params,
                data_snapshot=data_snapshot,
                code_commit=(commit or code_commit())[:40],
                seed=seed,
                metrics=metrics,
            )
            s.add(row)
            s.flush()
            return int(row.id)

    def n_trials(self, family: str) -> int:
        with session_scope(self.engine) as s:
            return int(
                s.scalar(
                    select(func.count()).select_from(Experiment).where(Experiment.family == family)
                )
                or 0
            )

    def trial_sharpes(self, family: str, key: str = "sharpe_per_period") -> FloatArray:
        with session_scope(self.engine) as s:
            rows = s.scalars(select(Experiment.metrics).where(Experiment.family == family)).all()
        vals = [float(m[key]) for m in rows if key in m]
        return np.asarray(vals, dtype=np.float64)
