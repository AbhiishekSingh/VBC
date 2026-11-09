"""Many results per check, one of them primary.

Revision ID: 0010_many_results_per_check
Revises: 0009_vendor_contact_mobile
Create Date: 2026-11-09

WHAT THIS CHANGES, AND WHY
--------------------------
`vendor_checks` held exactly ONE result per (vendor, check) — enforced by
`uq_vendor_check` — and a re-run overwrote it.

That lost the thing the work is actually made of. An analyst reads the
director list off MCA, takes each director's number, and runs the person
checks once per director. The second run erased the first. The same is
true of any check somebody wants to try twice with different inputs.

So results accumulate. Exactly one per (vendor, check) is PRIMARY — the
one SCAN, the risk score and the report read — and that is enforced by a
PARTIAL unique index rather than by whoever remembers to check.

Two things this migration is careful about:

  * EVERY EXISTING ROW BECOMES PRIMARY. There is one per check today, so
    marking them all primary is both correct and the only value that
    keeps scoring working across the upgrade. A row left unprimary would
    be a check that plainly has an answer and is not counted — the
    silent kind of wrong this product exists to prevent.

  * THE INPUTS SNAPSHOT IS BACKFILLED FROM `vendor_check_inputs`. Those
    rows are unique per (vendor, check, key), so they hold whatever was
    typed LAST. For the one result that exists today that is also what
    it ran with, so copying them is accurate now and stops being
    ambiguous the moment a second result appears.

Reversible. The downgrade keeps the primary row for each check and
DELETES the others, because the old unique constraint cannot be restored
while they exist. It says so out loud rather than failing halfway.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_many_results_per_check"
down_revision = "0009_vendor_contact_mobile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_checks",
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False,
            server_default=sa.false(),
            comment=("The one result of this check that SCAN, the risk "
                     "score and the report read. Exactly one per "
                     "vendor+check."),
        ),
    )
    op.add_column(
        "vendor_checks",
        sa.Column(
            "inputs", sa.dialects.postgresql.JSONB(), nullable=True,
            comment=("The input values THIS result was produced from, "
                     "snapshotted at run time so evidence stays "
                     "self-describing."),
        ),
    )

    # Every row that exists is the only result for its check, so every
    # row is the primary one. Done BEFORE the index is created, or the
    # index would be built against rows that are all still false.
    op.execute("UPDATE vendor_checks SET is_primary = true")

    # What was asked, as far as it can be known for results that predate
    # the snapshot. Accurate today because there is one result per check.
    op.execute(
        """
        UPDATE vendor_checks vc
        SET inputs = sub.inputs
        FROM (
            SELECT vendor_id, check_id,
                   jsonb_object_agg(key, value) AS inputs
            FROM vendor_check_inputs
            GROUP BY vendor_id, check_id
        ) AS sub
        WHERE vc.vendor_id = sub.vendor_id
          AND vc.check_id = sub.check_id
        """
    )

    op.drop_constraint("uq_vendor_check", "vendor_checks", type_="unique")
    op.create_index(
        "uq_vendor_check_primary", "vendor_checks",
        ["vendor_id", "check_id"], unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_index(
        "ix_vendor_checks_vendor_check", "vendor_checks",
        ["vendor_id", "check_id", "fetched_at"],
    )

    op.alter_column("vendor_checks", "is_primary", server_default=None)


def downgrade() -> None:
    # DESTRUCTIVE, and deliberately so: the old constraint is one row per
    # vendor per check, and it cannot be restored while several exist.
    # The primary of each is kept because it is the one everything read.
    op.execute(
        """
        DELETE FROM vendor_checks
        WHERE is_primary IS NOT TRUE
        """
    )
    op.drop_index("ix_vendor_checks_vendor_check", table_name="vendor_checks")
    op.drop_index("uq_vendor_check_primary", table_name="vendor_checks")
    op.create_unique_constraint(
        "uq_vendor_check", "vendor_checks", ["vendor_id", "check_id"]
    )
    op.drop_column("vendor_checks", "inputs")
    op.drop_column("vendor_checks", "is_primary")
