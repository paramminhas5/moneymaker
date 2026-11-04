from __future__ import annotations

import json
from pathlib import Path

import pytest
import structlog
from sqlalchemy import Engine, select
from typer.testing import CliRunner

from mm.control.cli import app
from mm.db.schema import AuditLog
from mm.db.session import session_scope
from mm.db.state import StateStore
from mm.logging import REDACTED, redact
from mm.secrets import MissingSecretError, get_secret


def test_kill_switch_lifecycle(engine: Engine) -> None:
    store = StateStore(engine)
    assert not store.is_halted()
    store.engage_kill("test", actor="agent:risk")
    assert store.is_halted()
    with pytest.raises(PermissionError):
        store.release_kill(actor="agent:risk")
    store.release_kill(actor="human")
    assert not store.is_halted()
    with session_scope(engine) as s:
        actions = [a.action for a in s.scalars(select(AuditLog)).all()]
    assert actions == ["kill_engaged", "kill_released"]


def test_agents_can_pause_but_not_resume(engine: Engine) -> None:
    store = StateStore(engine)
    store.pause("s1", actor="agent:risk")
    assert store.paused() == {"s1"}
    with pytest.raises(PermissionError):
        store.resume("s1", actor="agent:ops")
    store.resume("s1", actor="human")
    assert store.paused() == frozenset()


def test_secret_never_prints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM_SECRET_HL_KEY", "super-secret-value")
    s = get_secret("hl_key")
    assert "super-secret" not in repr(s)
    assert "super-secret" not in str(s)
    assert s.reveal() == "super-secret-value"
    with pytest.raises(MissingSecretError):
        get_secret("nope")


def test_log_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM_SECRET_X", "abcdef123456")
    out = redact(None, "info", {"event": "url https://x/abcdef123456/y", "api_key": "zzz"})
    assert "abcdef123456" not in json.dumps(dict(out))
    assert out["api_key"] == REDACTED
    structlog.reset_defaults()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("MM_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    return CliRunner()


def test_cli_status_kill_unkill(cli_env: CliRunner) -> None:
    r = cli_env.invoke(app, ["status"])
    assert r.exit_code == 0, r.output
    assert "off" in r.output
    r = cli_env.invoke(app, ["kill", "--reason", "drill"])
    assert r.exit_code == 0
    assert "ENGAGED" in r.output
    assert "ENGAGED" in cli_env.invoke(app, ["status"]).output
    r = cli_env.invoke(app, ["unkill"], input="nope\n")
    assert r.exit_code == 1
    r = cli_env.invoke(app, ["unkill"], input="RELEASE\n")
    assert r.exit_code == 0
    assert "released" in r.output


def test_cli_jurisdiction(cli_env: CliRunner) -> None:
    r = cli_env.invoke(app, ["jurisdiction", "show", "uae"])
    assert r.exit_code == 0
    assert "hyperliquid" in r.output
    r = cli_env.invoke(app, ["jurisdiction", "set", "uae"])
    assert "deliberately does not write" in " ".join(r.output.split())


def test_cli_unbuilt_commands_say_which_phase(cli_env: CliRunner) -> None:
    r = cli_env.invoke(app, ["gate", "s1_crypto_trend"])
    assert r.exit_code == 2
    assert "phase 3" in r.output
