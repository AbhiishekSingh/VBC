"""Set a result aside instead of destroying it.

Step 3 had a Delete that ran `session.delete(row)`. It was there so an
analyst could take a result out of the score, and it did that — by
destroying the evidence and the spend record along with it.

Two of this product's own commitments were in conflict and the delete
resolved them the wrong way:

  * a result is evidence, and evidence is kept;
  * a call that cost money stays in the ledger whatever anyone later
    decides about its answer.

A deleted row left a sentence in the audit log and a hole in the spend.
Any ledger built over `vendor_checks` would have under-reported what was
actually billed, and under-reported it silently.

So: nothing is destroyed. These three columns record that a PERSON set a
result aside — when, who, and why. An ignored result keeps its payload,
its facts and its cost. History counts it. The score does not read it.
Step 3 greys it and prints the reason. It can be reinstated, because the
judgement it records is a person's and people reconsider.

`ignore_reason` is nullable in the DATABASE and required by the API. A
column that is NOT NULL cannot hold the rows that predate it, and there
are none here only because nothing has been ignored yet — which is not a
guarantee worth encoding in a constraint that the next backfill would
have to fight.

Nothing is backfilled: every existing row is in force, which is what
NULL already means.

Revision ID: 0012_ignore_instead_of_delete
Revises: 0011_facts_carry_personal_data
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_ignore_instead_of_delete"
down_revision = "0011_facts_carry_personal_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_checks",
        sa.Column(
            "ignored_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "When a person set this result aside. NULL means it counts. "
                "Ignored results are kept whole and still counted as spend."
            ),
        ),
    )
    op.add_column(
        "vendor_checks",
        sa.Column("ignored_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "vendor_checks",
        sa.Column("ignore_reason", sa.Text(), nullable=True),
    )

    # Finds the in-force results of one vendor — the read the serialiser
    # and the scoring engine now make on every vendor fetch. Partial, so
    # it indexes only the rows that count; the ignored ones are read by
    # History, which filters by vendor and date rather than by this.
    op.create_index(
        "ix_vendor_checks_in_force",
        "vendor_checks",
        ["vendor_id", "check_id"],
        postgresql_where=sa.text("ignored_at IS NULL"),
    )


def downgrade() -> None:
    """Drops the columns.

    DESTRUCTIVE, and worth naming precisely: the rows all survive, but
    every judgement about them is lost. A result an analyst set aside
    with a reason comes back counting toward the score, silently, with
    nothing on screen to say it was ever set aside. The audit log still
    holds the act; the state does not.
    """
    op.drop_index("ix_vendor_checks_in_force", table_name="vendor_checks")
    op.drop_column("vendor_checks", "ignore_reason")
    op.drop_column("vendor_checks", "ignored_by")
    op.drop_column("vendor_checks", "ignored_at")
