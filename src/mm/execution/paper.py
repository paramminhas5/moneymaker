"""Paper trading: run a strategy's latest target weights against live Hyperliquid prices.

Conservative fill model: every order crosses the spread (buys at the ask, sells at the bid) and
pays the taker fee. Funding is charged on open positions between runs. Every order passes the
same pre-trade risk checks as live; rejections are recorded, never worked around.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Protocol

import yaml
from sqlalchemy import Engine

from mm.config import Settings
from mm.config.loader import config_dir
from mm.core.types import BookTop, Instrument, Mode, OrderIntent, OrderType, Product, Side, Stage
from mm.db.schema import AuditLog, EquitySnapshot, FillRecord, OrderRecord, SystemState
from mm.db.session import session_scope
from mm.db.state import StateStore
from mm.execution.hyperliquid_md import CoinMeta, hl_coin
from mm.risk.pretrade import PreTradeContext, check_order
from mm.strategies import Spec


class MarketData(Protocol):
    def meta(self) -> dict[str, CoinMeta]: ...
    def mids(self) -> dict[str, Decimal]: ...
    def book(self, coin: str, band: float = 0.005) -> BookTop: ...
    def funding_since(self, coin: str, start_ms: int) -> Decimal: ...


VENUE = "hyperliquid"
TAKER_FEE = Decimal("0.00045")
MIN_NOTIONAL = Decimal("10")


@dataclass(slots=True)
class Account:
    capital: Decimal
    cash: Decimal
    positions: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    last_run_ms: int = 0

    def qty(self, coin: str) -> Decimal:
        return Decimal(self.positions.get(coin, {}).get("qty", "0"))

    def to_json(self) -> dict[str, Any]:
        return {
            "capital": str(self.capital),
            "cash": str(self.cash),
            "positions": self.positions,
            "last_run_ms": self.last_run_ms,
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> Account:
        return Account(
            Decimal(d["capital"]),
            Decimal(d["cash"]),
            d.get("positions", {}),
            int(d.get("last_run_ms", 0)),
        )


@dataclass(slots=True)
class RunReport:
    strategy_id: str
    ts: datetime
    equity: Decimal
    cash: Decimal
    funding_paid: Decimal
    fills: list[str] = field(default_factory=list[str])
    rejections: list[str] = field(default_factory=list[str])
    skipped: list[str] = field(default_factory=list[str])


def strategy_stage(strategy_id: str, root: Path | None = None) -> Stage:
    path = (root or config_dir()) / "strategies" / f"{strategy_id}.yaml"
    if not path.exists():
        return Stage.RESEARCH
    return Stage(yaml.safe_load(path.read_text()).get("stage", "research"))


def _load_account(engine: Engine, sid: str, capital: Decimal) -> Account:
    with session_scope(engine) as s:
        row = s.get(SystemState, f"paper:{sid}")
        if row is None:
            acct = Account(capital=capital, cash=capital)
            s.add(SystemState(key=f"paper:{sid}", value=acct.to_json()))
            s.add(
                AuditLog(
                    actor="system", action=f"paper_open:{sid}", detail={"capital": str(capital)}
                )
            )
            return acct
        return Account.from_json(dict(row.value))


def _save_account(engine: Engine, sid: str, acct: Account) -> None:
    with session_scope(engine) as s:
        row = s.get(SystemState, f"paper:{sid}")
        assert row is not None
        row.value = acct.to_json()


def _round_qty(qty: Decimal, decimals: int) -> Decimal:
    q = Decimal(1).scaleb(-decimals)
    return qty.quantize(q, rounding=ROUND_DOWN)


def run_paper(
    spec: Spec,
    settings: Settings,
    engine: Engine,
    md: MarketData,
    *,
    capital: Decimal,
    now: datetime | None = None,
) -> RunReport:
    now = now or datetime.now(UTC)
    stage = strategy_stage(spec.id)
    if stage.rank < Stage.PAPER.rank:
        raise PermissionError(f"{spec.id} is at stage '{stage}'; paper needs owner approval")

    data = spec.load_data()
    extras = {k: v for k, v in data.items() if k != "close"}
    weights = spec.signal(data["close"], dict(spec.base_params), **extras)
    target_row = weights.tail(1).row(0, named=True)
    signal_ts = target_row.pop("ts")

    acct = _load_account(engine, spec.id, capital)
    meta, mids = md.meta(), md.mids()
    report = RunReport(spec.id, now, Decimal(0), acct.cash, Decimal(0))

    # 1. Funding on positions held since the last run.
    if acct.last_run_ms:
        for coin, pos in list(acct.positions.items()):
            qty = Decimal(pos["qty"])
            if qty and coin in mids:
                rate = md.funding_since(coin, acct.last_run_ms)
                paid = qty * mids[coin] * rate
                acct.cash -= paid
                report.funding_paid += paid

    def equity() -> Decimal:
        return acct.cash + sum(
            (acct.qty(c) * mids[c] for c in acct.positions if c in mids), Decimal(0)
        )

    eq = equity()
    store = StateStore(engine)
    halted, paused = store.is_halted(), store.paused()

    # 2. Orders: sells first (frees cash), then buys.
    plans: list[tuple[str, str, Decimal, int]] = []
    for sym, w in target_row.items():
        coin, mult = hl_coin(sym)
        if coin not in meta or coin not in mids:
            if w:
                report.skipped.append(f"{sym}: not listed on Hyperliquid (target {w:.3f})")
            continue
        target_notional = Decimal(str(w or 0)) * eq
        delta_qty = target_notional / mids[coin] - acct.qty(coin)
        delta_qty = _round_qty(abs(delta_qty), meta[coin].sz_decimals).copy_sign(delta_qty)
        if delta_qty == 0 or abs(delta_qty) * mids[coin] < MIN_NOTIONAL:
            # Closing a dust position is always allowed (reduce-only).
            if not (w == 0 and acct.qty(coin) != 0):
                continue
            delta_qty = -acct.qty(coin)
        plans.append((sym, coin, delta_qty, mult))
    plans.sort(key=lambda p: p[2])  # negatives (sells) first

    with session_scope(engine) as s:
        for _sym, coin, dq, _mult in plans:
            book = md.book(coin)
            side = Side.BUY if dq > 0 else Side.SELL
            price = book.ask if side is Side.BUY else book.bid
            current = acct.qty(coin)
            reduce_only = current != 0 and abs(current + dq) < abs(current) and dq * current < 0
            inst = Instrument(VENUE, coin, Product.PERP, coin, "USD", min_notional=MIN_NOTIONAL)
            intent = OrderIntent(
                spec.id, inst, side, abs(dq), OrderType.LIMIT, price, reduce_only=reduce_only
            )
            gross = sum(
                (abs(acct.qty(c)) * mids[c] for c in acct.positions if c in mids), Decimal(0)
            )
            ctx = PreTradeContext(
                settings=settings,
                mode=Mode.PAPER,
                strategy_stage=stage,
                equity_usd=equity(),
                gross_exposure_usd=gross,
                positions={f"{VENUE}:{c}": acct.qty(c) for c in acct.positions},
                book=book,
                halted=halted,
                paused_strategies=paused,
            )
            decision = check_order(intent, ctx)
            oid = uuid.uuid4().hex
            s.add(
                OrderRecord(
                    id=oid,
                    strategy_id=spec.id,
                    mode="paper",
                    venue=VENUE,
                    symbol=coin,
                    side=side.value,
                    quantity=abs(dq),
                    limit_price=price,
                    status="filled" if decision.approved else "rejected",
                    risk_reasons={"reasons": list(decision.reasons)},
                )
            )
            if not decision.approved:
                report.rejections.append(f"{side} {abs(dq)} {coin}: {'; '.join(decision.reasons)}")
                continue
            notional = abs(dq) * price
            fee = notional * TAKER_FEE
            acct.cash -= dq * price + fee
            new_qty = current + dq
            pos = acct.positions.get(coin, {"qty": "0", "avg": "0"})
            if new_qty == 0:
                acct.positions.pop(coin, None)
            else:
                avg = Decimal(pos["avg"])
                if dq > 0:
                    avg = (avg * current + price * dq) / new_qty if new_qty else price
                acct.positions[coin] = {"qty": str(new_qty), "avg": str(avg)}
            s.add(
                FillRecord(
                    order_id=oid, quantity=abs(dq), price=price, fee=fee, fee_currency="USD", ts=now
                )
            )
            report.fills.append(f"{side} {abs(dq)} {coin} @ {price} (fee {fee:.4f})")

        acct.last_run_ms = int(now.timestamp() * 1000)
        report.equity, report.cash = equity(), acct.cash
        s.add(EquitySnapshot(mode="paper", sleeve=spec.id, equity_usd=report.equity, ts=now))
        s.add(
            AuditLog(
                actor="system",
                action=f"paper_run:{spec.id}",
                detail={
                    "signal_ts": str(signal_ts),
                    "fills": len(report.fills),
                    "rejections": len(report.rejections),
                    "equity": str(report.equity),
                },
            )
        )
    _save_account(engine, spec.id, acct)
    return report
