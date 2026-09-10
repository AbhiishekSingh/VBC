"""Make the three money-gating timestamps timezone-aware.

``unlocks.expires_at``, ``jobs.cooldown_until`` and ``jobs.completed_at``
were declared as bare ``mapped_column(nullable=...)``, which produces
``TIMESTAMP WITHOUT TIME ZONE``. Every other timestamp in the schema is
``TIMESTAMPTZ``.

Two consequences, and the quiet one is the expensive one:

  * In Python the UTC offset was silently dropped on write, so comparing a
    stored value against ``datetime.now(timezone.utc)`` raised
    ``TypeError: can't compare offset-naive and offset-aware datetimes``.
    Loud, and therefore harmless.

  * In SQL it does NOT raise. PostgreSQL reinterprets the naive value in the
    server's own ``TimeZone`` setting. On a server running Asia/Kolkata that
    shifts every expiry by 5h30m in the wrong direction.

``unlocks.expires_at`` is the value that decides whether a ₹220 company
unlock has to be bought again, and ``jobs.cooldown_until`` guards the ₹5
filings refresh. An expiry wrong by hours means either a duplicate charge or
a company treated as unlocked when its unlock has lapsed.

THE CONVERSION ASSUMES THE STORED VALUES ARE UTC, which is what the
application wrote (it always passed an aware UTC datetime; the column
discarded the offset). ``AT TIME ZONE 'UTC'`` re-attaches it. If any row was
written by something other than this application, check it before upgrading.
"""

from __future__ import annotations

from alembic import op

revision = "0003_timestamptz"
down_revision = "0002_immutability"
branch_labels = None
depends_on = None

COLUMNS = (
    ("unlocks", "expires_at"),
    ("jobs", "cooldown_until"),
    ("jobs", "completed_at"),
)


def upgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE timestamptz USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE timestamp USING {column} AT TIME ZONE 'UTC'"
        )