"""Facts layer: a renderable projection of each check's stored payload.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12

WHAT THIS ADDS, AND WHY IT IS TWO COLUMNS RATHER THAN A TABLE
-------------------------------------------------------------
``vendor_checks.raw_response`` holds the provider's bytes and is the evidence
a historical score is defended with. It is not, and should not become,
something a screen reads: it is 20 KB of provider JSON per check, in a
different shape per provider, and it carries PAN numbers and contact details.

``facts`` is a projection of it — the same information in one small, stable
shape a report can render. It is DERIVED and DISPOSABLE, which is the whole
point: when a parse defect is found (four have been, see
``vbc-provider-parse-guards.md``), the fix is to bump the parser and re-run it
over the payloads already on file. No re-paid API calls, no migration, no
lost history. ``parser_version`` is what makes a defective vintage findable.

JSONB and not a column per field, because the shapes do not fit columns:
twenty-five directors with forty role objects each, sixty-one GST places of
business, three thousand filings. And because provider field names change —
which is what all four of those defects were.

NULLABLE, no default, no backfill. Every renderer degrades to the existing
``value``/``detail`` line when ``facts`` is absent, so this can be applied
before or after the application is deployed, in either order, with no window
where anything is broken. Rows written before this migration simply keep the
behaviour they have today until their check is next run.

BEFORE RUNNING
--------------
``down_revision`` below assumes ``0002`` (the immutability triggers) is
still head. Confirm with ``python -m alembic heads`` and correct it if this
branch has picked up another migration in between.

A NOTE ON GRANTS — the DPDP question in db/README.md
----------------------------------------------------
This migration deliberately does NOT change any grant. But it makes the
choice available for the first time: ``facts`` is written by a parser that
never copies a PAN, an unmasked contact address or a document body into it,
so the application role that serves screens needs SELECT on ``facts`` only,
and ``raw_response`` can be restricted to a narrower role that reads it for
audit and reconstruction. That is redaction by construction rather than by a
retention job, and it is a decision for whoever owns the retention policy —
not something a schema migration should make on their behalf.

``vendor_checks`` is not one of the four append-only tables, so no trigger
work is needed here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005_facts_layer"
down_revision = "0004_clients_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_checks",
        sa.Column(
            "facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Renderable projection of raw_response. Derived, disposable, "
                "rebuildable by re-running the parser over the payload. "
                "Carries no PAN, no unmasked contact detail and no document "
                "body."
            ),
        ),
    )
    op.add_column(
        "vendor_checks",
        sa.Column(
            "parser_version",
            sa.String(length=16),
            nullable=True,
            comment=(
                "Which parser produced `facts`, so a defective vintage can be "
                "found and rebuilt."
            ),
        ),
    )

    # Finds every row whose facts need rebuilding after a parser fix:
    #   SELECT ... WHERE parser_version IS DISTINCT FROM '2';
    # Partial, because rows with no facts at all are the "never parsed" case
    # and are found by `facts IS NULL` instead — a different question, and
    # one that should not pay for this index.
    op.create_index(
        "ix_vendor_checks_parser_version",
        "vendor_checks",
        ["parser_version"],
        postgresql_where=sa.text("parser_version IS NOT NULL"),
    )


def downgrade() -> None:
    # Safe in a way most downgrades are not: `facts` is derived, so dropping
    # it destroys nothing that cannot be rebuilt from `raw_response`, which
    # this migration never touched.
    op.drop_index("ix_vendor_checks_parser_version", table_name="vendor_checks")
    op.drop_column("vendor_checks", "parser_version")
    op.drop_column("vendor_checks", "facts")
