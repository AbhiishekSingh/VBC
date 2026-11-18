"""Let a result say "needs confirmation".

WHAT BROKE, AND WHY IT GOT THROUGH
----------------------------------
`NEEDS_CONFIRMATION` was added to `CheckStatus` when "Attention" was
retired on 17 Nov 2026. `vendor_checks.status` has carried a CHECK
constraint since migration 0001:

    status IN ('pass','warn','fail','skip','unavailable',
               'not_configured','skipped_missing_input')

The new value was never added to it. So the enum, the API and the
screen all accepted a status the DATABASE refused, and every check
that returned it failed on INSERT with an IntegrityError — a 500 on
the run, after the provider had been called and the money spent.

A dozen checks emit it: courtsearch, causelist, resolve, dresolve,
gst, court, dup, rp, dwhois, refresh, frefresh and dcontact. Running
almost any real vendor hits one.

The test suite did not catch this because the tests that exercise a
real INSERT are the DB-backed ones, and those SKIP when no Postgres is
present — 916 passed, 129 skipped, and the 129 were exactly the ones
that would have failed. A green suite with a skipped section is not a
green suite for a schema change.

THE LESSON, WORTH THE LINES
---------------------------
Adding a value to a Python enum is not adding a value to the database.
`CheckStatus` is mirrored in three places — this constraint, the
TypeScript union in `types/domain.ts`, and the enum itself — and only
one of them fails loudly when they disagree. Any future status needs
all three, and a migration.

`warn` STAYS in the list. Nothing emits it any more, but rows written
before 17 Nov 2026 hold it, and a constraint is checked on UPDATE as
well as INSERT — dropping it would make every historical row
unwritable, so setting one aside would fail.

Revision ID: 0013_status_allows_needs_confirmation
Revises: 0012_ignore_instead_of_delete
"""

from __future__ import annotations

from alembic import op

revision = "0013_status_allows_needs_confirmation"
down_revision = "0012_ignore_instead_of_delete"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_vendor_checks_status_enum"
TABLE = "vendor_checks"

#: WRITTEN OUT IN FULL, not assembled from a constant. A migration is a
#: record of what was done to a database that already exists, and it is
#: read years later by someone asking "what did the schema allow in
#: November". A variable makes that question require running the file.
#:
#: It also means `test_status_parity.py` can read this list without
#: importing the module, which is what makes the check cheap enough to
#: run on every commit.
NEW = (
    "status IN ('pass','warn','needs_confirmation','fail','skip',"
    "'unavailable','not_configured','skipped_missing_input')"
)
OLD = (
    "status IN ('pass','warn','fail','skip','unavailable',"
    "'not_configured','skipped_missing_input')"
)


def _swap(check: str) -> None:
    """Postgres cannot alter a CHECK in place; it is dropped and remade."""
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, check)


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    """Rows holding the new value must go somewhere a narrower
    constraint will accept, or it cannot be recreated.

    `unavailable` is the honest destination: both mean the check did
    not establish anything about this vendor, and neither is a pass.
    Going back loses the distinction between "we could not identify the
    subject" and "the provider could not be reached", which is a real
    loss — downgrading this migration is not free.
    """
    op.execute(
        "UPDATE vendor_checks SET status = 'unavailable' "
        "WHERE status = 'needs_confirmation'"
    )
    _swap(OLD)
