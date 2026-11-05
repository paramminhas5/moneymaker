"""Proposal queue for football markets on Polymarket. RESEARCH ONLY: it never places orders.

Flow (all human-visible, append-only JSONL so nothing is lost or rewritten):
1. `propose`: the model's probability for an outcome is compared with the Polymarket ask. If the
   edge clears a threshold, a proposal is appended with the entry price it *would* have paid.
2. `record_close`: just before kick-off the market's last price is recorded as the closing line.
   Closing-line value (CLV) = closing price - entry price, in probability points. Positive CLV
   on average is the earliest honest sign of an edge; it shows up long before PnL is significant.
3. `settle`: after the match, the outcome is recorded and the hypothetical PnL computed.

Polymarket trading is disabled in every jurisdiction profile today, so the queue is the end of the
line: it measures whether the model would beat the closing price, nothing more.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Proposal:
    id: str
    created_at: str
    market: str  # Polymarket market slug or condition id
    match: str  # "E0 2026-11-08 Arsenal v Chelsea"
    outcome: str  # "H", "D", "A" or a market-specific label
    model_prob: float
    entry_price: float  # YES ask at proposal time, 0..1
    edge: float  # model_prob - entry_price
    status: str = "proposed"  # proposed -> closed -> settled
    close_price: float | None = None
    clv: float | None = None
    won: bool | None = None
    pnl_per_share: float | None = None


class ProposalQueue:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Proposal]:
        out: dict[str, Proposal] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text().splitlines():
            if line.strip():
                p = Proposal(**json.loads(line))
                out[p.id] = p  # later lines are newer versions of the same proposal
        return out

    def _append(self, p: Proposal) -> Proposal:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(p)) + "\n")
        return p

    def all(self) -> list[Proposal]:
        return list(self._load().values())

    def propose(
        self,
        *,
        market: str,
        match: str,
        outcome: str,
        model_prob: float,
        entry_price: float,
        min_edge: float = 0.03,
        now: datetime | None = None,
    ) -> Proposal | None:
        """Append a proposal if model_prob - entry_price >= min_edge, else return None."""
        if not 0 < entry_price < 1 or not 0 <= model_prob <= 1:
            raise ValueError("prices and probabilities must be in (0, 1)")
        edge = model_prob - entry_price
        if edge < min_edge:
            return None
        ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        return self._append(
            Proposal(
                uuid.uuid4().hex[:12], ts, market, match, outcome, model_prob, entry_price, edge
            )
        )

    def record_close(self, proposal_id: str, close_price: float) -> Proposal:
        p = self._load()[proposal_id]
        return self._append(
            replace(p, status="closed", close_price=close_price, clv=close_price - p.entry_price)
        )

    def settle(self, proposal_id: str, won: bool) -> Proposal:
        p = self._load()[proposal_id]
        pnl = (1.0 - p.entry_price) if won else -p.entry_price
        return self._append(replace(p, status="settled", won=won, pnl_per_share=pnl))

    def summary(self) -> dict[str, float]:
        ps = self.all()
        clvs = [p.clv for p in ps if p.clv is not None]
        pnls = [p.pnl_per_share for p in ps if p.pnl_per_share is not None]
        return {
            "proposals": float(len(ps)),
            "with_close": float(len(clvs)),
            "mean_clv": float(sum(clvs) / len(clvs)) if clvs else 0.0,
            "share_positive_clv": float(sum(c > 0 for c in clvs) / len(clvs)) if clvs else 0.0,
            "settled": float(len(pnls)),
            "pnl_per_share": float(sum(pnls)) if pnls else 0.0,
        }
