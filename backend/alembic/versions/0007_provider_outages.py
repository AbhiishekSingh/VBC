"""Which providers cannot be called right now, and why.

We buy data from four outside services on prepaid accounts. When one runs
out of money, every check against it fails the same way — and with no
shared record, every analyst learns that separately. The first discovers
it from a failed run; so does the tenth, each having waited for a call
that could not succeed, on a vendor file in front of a client.

One row here means ONE person meets the error. Everyone after them sees
those checks marked unavailable before they select anything, with the
provider's own reason, and no further calls go out.

`provider_message` IS THE PROVIDER'S TEXT, never ours. An account can be
refused for an empty balance, a revoked key, or an IP that is not
allowlisted — WhoisXML returns all three behind one 403 — and a fixed
message of ours would send the wrong person to the wrong place two times
in three.

The unique index is PARTIAL: one OPEN outage per provider, unlimited
closed ones. Closed rows are the history, and "how long was FileSure down
and what did it say" is the question asked after a client complains. It
cannot be answered from rows that were deleted.

`last_probe_at` is what stops the block being permanent. Once nothing
calls a provider, nothing can discover it is working again, so topping up
the balance would fix nothing until somebody edited the database. Every
fifteen minutes one check is let through; it succeeds and the outage
clears, or it fails and the clock restarts.

Nothing is backfilled. Outages before this migration were never recorded,
and inventing them would put false history under a table whose purpose is
to be believed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_provider_outages"
down_revision = "0006_stored_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_outages",
        sa.Column("id", sa.Integer(), nullable=False),
        # Matches Provider.value in app/domain/types.py — "filesure",
        # "whoisxml", "finagg", "ecourts". One spelling across the runner,
        # this table and the API; a provider blocked under one name and
        # looked up under another stays invisible on the screen that
        # exists to show it.
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("provider_message", sa.Text(), nullable=False),
        sa.Column("detected_on_check", sa.String(length=32), nullable=True),
        sa.Column("detected_on_vendor", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False,
                  server_default="run"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # No foreign key on detected_on_vendor: the outage is about OUR
    # account, not about that vendor, and deleting the vendor must not
    # take the record of a provider failure with it.
    op.create_index(
        "uq_provider_outage_open",
        "provider_outages",
        ["provider"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
        sqlite_where=sa.text("cleared_at IS NULL"),
    )
    op.create_index(
        "ix_provider_outage_started", "provider_outages", ["started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_provider_outage_started", table_name="provider_outages")
    op.drop_index("uq_provider_outage_open", table_name="provider_outages")
    op.drop_table("provider_outages")
