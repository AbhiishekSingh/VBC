"""Engine and session factory.

The URL comes from ``app.config.Settings``, which is the ONE place that
knows how to reach the database. Reading ``os.environ`` here instead would
bypass the ``.env`` file entirely — pydantic-settings loads it, a bare
``os.environ.get`` does not — so a correctly filled ``.env`` would be
silently ignored and the fallback used instead.

The engine is built lazily. Importing this module must not open a
connection: the API has to be able to start, serve ``/health`` and report
that the database is unreachable, rather than crashing on import and
telling the operator nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Built on first use, not at import time."""
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


#: Kept for callers that want the configured URL without an engine.
def database_url() -> str:
    return get_settings().database_url


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def __getattr__(name: str):
    """Backwards compatibility for ``from app.db.session import engine``.

    Alembic's env.py and older code import ``DATABASE_URL`` and ``engine``
    as module attributes. Resolving them lazily here keeps those imports
    working without reopening the import-time-connection problem.
    """
    if name == "engine":
        return get_engine()
    if name == "DATABASE_URL":
        return database_url()
    if name == "SessionFactory":
        return get_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")