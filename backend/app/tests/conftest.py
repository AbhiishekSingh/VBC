"""Shared database fixtures.

These lived inside test_database.py, where no other module could reach
them — so a test needing a real database had to either duplicate the setup
or not be written. The second is what kept happening, which is part of why
three stale-timestamp defects survived in code that had database tests.

Against a REAL PostgreSQL server, never SQLite: the schema relies on JSONB,
CHECK constraints and append-only triggers, and a SQLite approximation would
pass while production rejected the same operation. Skipped automatically
when no server is reachable, so the suite still runs without one.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

TEST_URL = os.environ.get(
    "VBC_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres@/vbc_test?host=/tmp/pgsock&port=5433",
)

#: Vendor-side tables, cleared between tests. The catalog is left alone —
#: re-seeding for every test would be slow and would test nothing.
VENDOR_TABLES = (
    "decisions", "vendor_scores", "scan_ratings", "vendor_checks",
    "vendor_check_inputs", "vendor_manual_entries", "surveillance_entries",
    "field_visits", "unlocks", "jobs", "audit_log", "vendors",
    # The client/auth layer. Left out, rows survived between tests and the
    # second test to create CL000001 or US000001 failed on a duplicate key —
    # which looks like a bug in the code under test rather than in cleanup.
    "sessions", "users", "clients",
)


def server_available() -> bool:
    try:
        create_engine(TEST_URL).connect().close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def db_engine():
    if not server_available():
        pytest.skip("no PostgreSQL server reachable")
    engine = create_engine(TEST_URL, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        sql = (pathlib.Path(__file__).parents[1] / "db" / "immutability.sql").read_text()
        conn.execute(text(sql))
    yield engine
    engine.dispose()


#: Every vendor needs a client now. Tests that are not ABOUT the client
#: layer should not have to care, so one is created with the session.
DEFAULT_CLIENT_ID = "CL000000"


@pytest.fixture
def session(db_engine):
    """A session, with a default client already present.

    NOTE: TRUNCATE bypasses row-level triggers, which is exactly why the
    application role must not hold TRUNCATE privilege in production. Tests
    run as the owner, so cleanup is possible here.
    """
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    s: Session = factory()
    _ensure_default_client(s)
    yield s
    s.rollback()
    s.execute(text(f"TRUNCATE {', '.join(VENDOR_TABLES)} RESTART IDENTITY CASCADE"))
    s.commit()
    s.close()


def _ensure_default_client(s: Session) -> None:
    from app.db.models import Client

    if s.get(Client, DEFAULT_CLIENT_ID) is None:
        s.add(Client(id=DEFAULT_CLIENT_ID, name="Test Client"))
        s.commit()


@pytest.fixture
def seeded(session):
    """The catalog, loaded once per test.

    vendor_checks.check_id is a FOREIGN KEY into check_definitions, so a
    result cannot be recorded for a check the catalog does not define. That
    constraint is deliberate — it makes an unknown check_id a write error
    rather than an orphan row nobody notices — and it means any test that
    persists a finding needs the catalog present.
    """
    from app.db.seed import seed

    version = seed(session, note="test")
    session.commit()
    return version
