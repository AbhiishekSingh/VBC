"""Index of stored documents — the PDFs behind a finding.

Revision ID: 0006_stored_documents
Revises: 0005_facts_layer
Create Date: 2026-09-13

`download` and `courtorders` fetch real documents and, until now, recorded a
size and a digest and discarded the bytes. A report said "order retrieved"
with nothing to open.

The files themselves go to a content-addressed directory on disk, NOT into
this table — an order PDF is ~50 KB and a busy vendor has dozens, and
`raw_response` is already the largest column in the schema. This table is the
index: whose document it is, which check fetched it, when, and how big.

`sha256` is UNIQUE because the store is content-addressed: identical bytes
are one file. So the same filing fetched for two vendors produces one row,
recording the first vendor to fetch it — access is authorised by session,
not by ownership of the row.

`vendor_id` is ON DELETE SET NULL rather than CASCADE. Deleting a vendor
should not silently orphan a file on disk that nothing then points at; the
row survives as a record that the bytes exist and why.

Nothing is backfilled. Documents fetched before this migration were never
stored and cannot be recovered without re-fetching them — which costs money
and returns today's document, not the one that was read at the time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_stored_documents"
down_revision = "0005_facts_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("vendor_id", sa.String(length=16), nullable=True),  # matches vendors.id
        sa.Column("check_id", sa.String(length=32), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_type", sa.String(length=64), nullable=False,
                  server_default="application/pdf"),
        sa.Column("bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", name="uq_stored_documents_sha256"),
    )
    op.create_index("ix_stored_documents_vendor", "stored_documents", ["vendor_id"])


def downgrade() -> None:
    # Drops the index only. The FILES on disk are deliberately left alone:
    # this migration never created them, and deleting evidence to reverse a
    # schema change is not a trade anyone should make silently. Remove
    # `storage/documents/` by hand if that is genuinely wanted.
    op.drop_index("ix_stored_documents_vendor", table_name="stored_documents")
    op.drop_table("stored_documents")
