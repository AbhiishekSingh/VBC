"""SQLAlchemy base, shared column types and conventions.

CONVENTIONS ENFORCED HERE
-------------------------
* Money is ALWAYS an integer number of paisa, never a float and never
  rupees. FileSure's API reports paisa; storing 22000 rather than 220.00
  removes every rounding question. Columns are named ``*_paisa`` so a
  reviewer can see the unit without opening the docs.
* Timestamps are timezone-aware and set by the database, so a row's time
  does not depend on which worker wrote it.
* Naming conventions are declared so Alembic generates stable, predictable
  constraint names instead of database-assigned ones that differ between
  environments.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

#: Predictable constraint names — without this Alembic emits unnamed
#: constraints that cannot be dropped cleanly in a downgrade.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: JSONB on PostgreSQL, plain JSON elsewhere so the suite can run without
#: a server when needed. Production is always PostgreSQL.
JsonB = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def money() -> Mapped[int]:
    """An amount in paisa. Divide by 100 only at the point of display."""
    return mapped_column(BigInteger, nullable=False, default=0)


def created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
