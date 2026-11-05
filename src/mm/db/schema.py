"""Database schema. Every money-touching event and every research trial is recorded."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mm.core.types import utcnow

SCHEMA_VERSION = 1
MONEY = Numeric(28, 10)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, Decimal: MONEY}  # noqa: RUF012


class SystemState(Base):
    """Key/value switches: kill switch, paused strategies, schema version."""

    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyRecord(Base):
    """Strategy registry. `stage` changes only through the approval workflow."""

    __tablename__ = "strategies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), default="research")
    config_hash: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Experiment(Base):
    """One research trial. Every variant is logged; the count feeds the Deflated Sharpe Ratio."""

    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    family: Mapped[str] = mapped_column(String(64), index=True)  # trials in one family share DSR
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    data_snapshot: Mapped[str] = mapped_column(String(64))
    code_commit: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderRecord(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    venue: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[Decimal]
    limit_price: Mapped[Decimal | None]
    status: Mapped[str] = mapped_column(String(16))
    risk_reasons: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FillRecord(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    quantity: Mapped[Decimal]
    price: Mapped[Decimal]
    fee: Mapped[Decimal]
    fee_currency: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16))
    sleeve: Mapped[str] = mapped_column(String(64), default="account")
    equity_usd: Mapped[Decimal]
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_equity_mode_sleeve_ts", "mode", "sleeve", "ts"),)


class Approval(Base):
    """Human approvals for promotions and capital changes. Agents may only create requests."""

    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(32))  # promote | capital_change
    target: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only record of every state change and who made it."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64))  # human | agent:<role> | system
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
