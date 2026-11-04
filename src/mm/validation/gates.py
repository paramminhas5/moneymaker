"""Gate engine. G0 = code hygiene, G1 = statistical evidence. Reports are saved as Markdown + JSON.

The validator never edits strategy code and strategies never edit this module (separation of
duties). Thresholds come from config/gates.yaml, which only the human edits.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml

from mm.config.loader import config_dir
from mm.validation.metrics import FloatArray, sharpe, summarize
from mm.validation.pbo import PBOResult
from mm.validation.resample import bootstrap_ci
from mm.validation.sharpe_tests import deflated_sharpe

REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports" / "gates"
Kind = Literal["directional", "carry"]


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    passed: bool
    value: str
    threshold: str
    detail: str = ""


@dataclass(slots=True)
class GateReport:
    strategy_id: str
    gate: str
    checks: list[GateCheck]
    data_snapshot: str
    code_commit: str
    metrics: dict[str, float] = field(default_factory=dict[str, float])
    notes: list[str] = field(default_factory=list[str])
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_markdown(self) -> str:
        verdict = "PASSED" if self.passed else "FAILED"
        lines = [
            f"# {self.gate} gate report: `{self.strategy_id}` - **{verdict}**",
            "",
            f"- Created: {self.created_at}",
            f"- Data snapshot: `{self.data_snapshot}`",
            f"- Code commit: `{self.code_commit}`",
            "",
            "| Check | Result | Value | Threshold | Detail |",
            "|---|---|---|---|---|",
        ]
        for c in self.checks:
            lines.append(
                f"| {c.name} | {'pass' if c.passed else '**FAIL**'} | {c.value} | "
                f"{c.threshold} | {c.detail} |"
            )
        if self.metrics:
            lines += ["", "## OOS metrics", "", "| Metric | Value |", "|---|---|"]
            for k, v in self.metrics.items():
                lines.append(f"| {k} | {v:.4f} |")
        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {n}" for n in self.notes]
        return "\n".join(lines) + "\n"

    def save(self, root: Path | None = None) -> Path:
        root = (root or REPORTS_DIR) / self.strategy_id
        root.mkdir(parents=True, exist_ok=True)
        stamp = self.created_at.replace(":", "").replace("-", "")[:15]
        md = root / f"{self.gate}_{stamp}.md"
        md.write_text(self.to_markdown())
        payload = asdict(self) | {"passed": self.passed}
        (root / f"{self.gate}_{stamp}.json").write_text(json.dumps(payload, indent=2))
        (root / f"{self.gate}_latest.md").write_text(self.to_markdown())
        return md


def load_gate_config(root: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(((root or config_dir()) / "gates.yaml").read_text())


def evaluate_g0(
    strategy_id: str,
    *,
    no_lookahead: bool,
    tests_passed: bool,
    cost_model: str | None,
    deterministic: bool,
    data_snapshot: str,
    code_commit: str,
) -> GateReport:
    checks = [
        GateCheck("no-lookahead harness", no_lookahead, str(no_lookahead), "True"),
        GateCheck("unit tests", tests_passed, str(tests_passed), "True"),
        GateCheck("cost model attached", cost_model is not None, cost_model or "none", "a model"),
        GateCheck(
            "deterministic replay",
            deterministic,
            str(deterministic),
            "True",
            "same seed + snapshot + commit gives identical returns",
        ),
    ]
    return GateReport(strategy_id, "G0", checks, data_snapshot, code_commit)


def evaluate_g1(
    strategy_id: str,
    *,
    kind: Kind,
    oos_returns: FloatArray,
    n_trials: int,
    trial_sharpes: FloatArray | None,
    pbo: PBOResult | None,
    sleeve_max_dd: float,
    event_driven_gap: float | None,
    data_snapshot: str,
    code_commit: str,
    periods_per_year: float = 365.0,
    annual_turnover: float | None = None,
    annual_cost_drag: float | None = None,
    walkforward_stability: float | None = None,
    config: dict[str, Any] | None = None,
) -> GateReport:
    cfg = (config or load_gate_config())["g1"]
    r = np.asarray(oos_returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    s = summarize(r, periods_per_year)
    years = r.size / periods_per_year
    dsr = deflated_sharpe(r, n_trials, trial_sharpes)
    _, ci_lo, ci_hi = bootstrap_ci(r, lambda x: sharpe(x, periods_per_year), n_boot=500, seed=7)
    min_sr = float(cfg["min_oos_sharpe"][kind])

    checks = [
        GateCheck(
            "OOS history length",
            years >= cfg["min_oos_years"],
            f"{years:.2f}y",
            f">= {cfg['min_oos_years']}y",
        ),
        GateCheck(
            "OOS net Sharpe",
            s.sharpe >= min_sr,
            f"{s.sharpe:.2f}",
            f">= {min_sr}",
            f"{kind} strategy",
        ),
        GateCheck(
            "Sharpe 95% CI lower bound",
            ci_lo > cfg["min_sharpe_ci_lower"],
            f"{ci_lo:.2f} (upper {ci_hi:.2f})",
            f"> {cfg['min_sharpe_ci_lower']}",
            "stationary block bootstrap",
        ),
        GateCheck(
            "Deflated Sharpe probability",
            dsr >= cfg["min_dsr"],
            f"{dsr:.3f}",
            f">= {cfg['min_dsr']}",
            f"N = {n_trials} logged trials",
        ),
        GateCheck(
            "Probability of backtest overfitting",
            pbo is not None and pbo.pbo <= cfg["max_pbo"],
            f"{pbo.pbo:.3f}" if pbo else "not run",
            f"<= {cfg['max_pbo']}",
            f"{pbo.n_splits} CSCV splits" if pbo else "",
        ),
        GateCheck(
            "Max drawdown within sleeve budget",
            s.max_drawdown <= sleeve_max_dd,
            f"{s.max_drawdown:.1%}",
            f"<= {sleeve_max_dd:.0%}",
        ),
        GateCheck(
            "Event-driven confirmation",
            event_driven_gap is not None and abs(event_driven_gap) <= cfg["max_event_driven_gap"],
            f"{event_driven_gap:.1%}" if event_driven_gap is not None else "not run",
            f"<= {cfg['max_event_driven_gap']:.0%}",
            "relative gap in total return vs vectorised backtest",
        ),
    ]
    metrics = s.as_dict()
    metrics["deflated_sharpe"] = dsr
    if annual_turnover is not None:
        metrics["annual_turnover"] = annual_turnover
    if annual_cost_drag is not None:
        metrics["annual_cost_drag"] = annual_cost_drag
    if walkforward_stability is not None:
        metrics["walkforward_stability"] = walkforward_stability
    if pbo is not None:
        metrics["pbo_degradation_slope"] = pbo.perf_degradation_slope
    return GateReport(strategy_id, "G1", checks, data_snapshot, code_commit, metrics)
