"""Persisted switches: kill switch and paused strategies. Every change is audit-logged."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine

from mm.core.types import utcnow
from mm.db.schema import AuditLog, SystemState
from mm.db.session import session_scope

KILL_KEY = "kill_switch"
PAUSED_KEY = "paused_strategies"


class StateStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _get(self, key: str) -> dict[str, Any] | None:
        with session_scope(self.engine) as s:
            row = s.get(SystemState, key)
            return dict(row.value) if row else None

    def _set(self, key: str, value: dict[str, Any], actor: str, action: str) -> None:
        with session_scope(self.engine) as s:
            row = s.get(SystemState, key)
            if row is None:
                s.add(SystemState(key=key, value=value, updated_at=utcnow()))
            else:
                row.value = value
                row.updated_at = utcnow()
            s.add(AuditLog(actor=actor, action=action, detail=value))

    # Kill switch -------------------------------------------------------------------------
    def kill_status(self) -> dict[str, Any]:
        return self._get(KILL_KEY) or {"engaged": False, "reason": "", "by": ""}

    def is_halted(self) -> bool:
        return bool(self.kill_status().get("engaged"))

    def engage_kill(self, reason: str, actor: str) -> None:
        """Anyone (human, agent, system) may engage the kill switch."""
        self._set(
            KILL_KEY,
            {"engaged": True, "reason": reason, "by": actor, "at": utcnow().isoformat()},
            actor,
            "kill_engaged",
        )

    def release_kill(self, actor: str) -> None:
        """Only a human may release it."""
        if actor != "human":
            raise PermissionError("only the human owner can release the kill switch")
        self._set(KILL_KEY, {"engaged": False, "reason": "", "by": actor}, actor, "kill_released")

    # Pauses ------------------------------------------------------------------------------
    def paused(self) -> frozenset[str]:
        data = self._get(PAUSED_KEY) or {"ids": []}
        return frozenset(data.get("ids", []))

    def pause(self, strategy_id: str, actor: str) -> None:
        ids = sorted(self.paused() | {strategy_id})
        self._set(PAUSED_KEY, {"ids": ids}, actor, f"pause:{strategy_id}")

    def resume(self, strategy_id: str, actor: str) -> None:
        if actor != "human":
            raise PermissionError("only the human owner can resume a strategy")
        ids = sorted(self.paused() - {strategy_id})
        self._set(PAUSED_KEY, {"ids": ids}, actor, f"resume:{strategy_id}")
