"""Engine and session factory. MM_DATABASE_URL picks the database (default: local SQLite)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from mm.db.schema import SCHEMA_VERSION, Base, SystemState

DEFAULT_SQLITE = Path(__file__).resolve().parents[3] / "var" / "mm.db"


def database_url() -> str:
    url = os.environ.get("MM_DATABASE_URL")
    if url:
        return url
    DEFAULT_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE}"


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as s, s.begin():
        if s.get(SystemState, "schema_version") is None:
            s.add(SystemState(key="schema_version", value={"version": SCHEMA_VERSION}))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session, session.begin():
        yield session
