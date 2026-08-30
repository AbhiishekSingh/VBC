"""Clients, users, sessions — and every vendor belongs to a client.

Adds the layer above vendors. A vendor is no longer a free-floating record:
it is always "this client's vendor", and an audit is always "this client's
assessment of this vendor".

EXISTING VENDORS. They have no client, and client_id is NOT NULL. So a
holding client is created and every existing vendor is attached to it,
rather than the data being dropped. Reassign by hand afterwards.

NO DEFAULT LOGIN IS CREATED HERE. A migration that inserts a known
email and password is a backdoor that ships to production and is never
removed. Create the first user with:

    python -m app.db.create_user --email you@q1ssl.com --role admin
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_clients_auth"
down_revision = "0003_timestamptz"
branch_labels = None
depends_on = None

HOLDING_CLIENT_ID = "CL000000"


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("legal_name", sa.Text, nullable=False, server_default=""),
        sa.Column("industry", sa.Text, nullable=False, server_default=""),
        sa.Column("spoc", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.Text, nullable=False, server_default=""),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_client_name"),
    )
    op.create_index("ix_clients_active", "clients", ["active"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="analyst"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_user_email"),
        sa.CheckConstraint("role IN ('analyst','approver','admin')", name="role_enum"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(16),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_session_token"),
    )
    op.create_index("ix_sessions_user", "sessions", ["user_id"])

    # --- vendors.client_id, without losing any existing vendor ---------
    op.add_column("vendors", sa.Column("client_id", sa.String(16), nullable=True))

    existing = op.get_bind().execute(sa.text("SELECT count(*) FROM vendors")).scalar()
    if existing:
        op.get_bind().execute(
            sa.text(
                "INSERT INTO clients (id, name, legal_name, notes) VALUES "
                "(:id, :name, :name, :note) ON CONFLICT (name) DO NOTHING"
            ),
            {
                "id": HOLDING_CLIENT_ID,
                "name": "Unassigned",
                "note": "Holding client created by migration 0004 for vendors "
                        "that predate the client layer. Reassign and remove.",
            },
        )
        op.get_bind().execute(
            sa.text("UPDATE vendors SET client_id = :id WHERE client_id IS NULL"),
            {"id": HOLDING_CLIENT_ID},
        )

    op.alter_column("vendors", "client_id", nullable=False)
    op.create_foreign_key(
        "fk_vendors_client_id_clients", "vendors", "clients",
        ["client_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_vendors_client", "vendors", ["client_id"])
    # One client cannot add the same company twice. Two different clients
    # can — that is the point of the client layer.
    op.create_index(
        "uq_client_cin", "vendors", ["client_id", "cin"],
        unique=True, postgresql_where=sa.text("cin IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_client_cin", table_name="vendors")
    op.drop_index("ix_vendors_client", table_name="vendors")
    op.drop_constraint("fk_vendors_client_id_clients", "vendors", type_="foreignkey")
    op.drop_column("vendors", "client_id")
    op.drop_index("ix_sessions_user", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_index("ix_clients_active", table_name="clients")
    op.drop_table("clients")
