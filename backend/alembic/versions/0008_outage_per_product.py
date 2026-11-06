"""Block the pool that ran out, not the whole provider.

WHY THIS CHANGE EXISTS
----------------------
`provider_outages` keyed on the provider, on the assumption that a
provider has one wallet. WhoisXML does not. On 6 Nov 2026 a single key,
from a single IP, inside one minute:

    ssl-certificates   200        domain-reputation  200
    whois-history      403        reverse-whois      403

The Domain Research Suite subscription had lapsed while the standalone
products were fine. Under the old schema the first 403 would have marked
ALL FIVE WhoisXML checks unavailable for every user — taking away two
checks that were answering normally. The platform would have caused a
wider outage than the one it exists to prevent.

`product` is the pool. "" means the provider's whole account, which is
true for FileSure, eCourts and FinAGG — each bills from one wallet, and
splitting them would mean every endpoint discovering an empty wallet
separately.

NOT NULL WITH A "" DEFAULT, NOT NULLABLE
----------------------------------------
Postgres treats NULLs as distinct in a unique index, so a nullable column
would allow two open rows for the same provider and silently break the
idempotency the table depends on — one run with eight failing checks
would write eight rows instead of one.

The unique index is rebuilt over (provider, product) rather than altered,
because a partial unique index cannot have a column added in place.

Existing rows backfill to "" — provider-wide, which is what they meant
when they were written.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_outage_per_product"
down_revision = "0007_provider_outages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_outages",
        sa.Column("product", sa.String(length=48), nullable=False,
                  server_default=""),
    )
    op.drop_index("uq_provider_outage_open", table_name="provider_outages")
    op.create_index(
        "uq_provider_outage_open",
        "provider_outages",
        ["provider", "product"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
        sqlite_where=sa.text("cleared_at IS NULL"),
    )


def downgrade() -> None:
    # Close any per-product outage before narrowing the index back to the
    # provider alone. Two open rows for one provider are legal under this
    # schema and illegal under the old one, so dropping the column without
    # this would fail on the index rebuild — in the middle of a
    # downgrade, which is the worst place to discover it.
    op.execute(
        "UPDATE provider_outages SET cleared_at = now() "
        "WHERE cleared_at IS NULL AND product <> ''"
    )
    op.drop_index("uq_provider_outage_open", table_name="provider_outages")
    op.create_index(
        "uq_provider_outage_open",
        "provider_outages",
        ["provider"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
        sqlite_where=sa.text("cleared_at IS NULL"),
    )
    op.drop_column("provider_outages", "product")
