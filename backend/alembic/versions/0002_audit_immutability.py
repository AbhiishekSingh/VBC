"""Append-only enforcement for the audit trail, scores and decisions.

WHY THIS IS A MIGRATION AND NOT APPLICATION CODE
------------------------------------------------
An audit log that application code can rewrite is worth very little in the
situation it exists for: an investigation into whether the process was
followed, in which the application is precisely what is being questioned.
"We only ever append" is a claim; a trigger that raises on UPDATE is a
control.

The triggers cover UPDATE and DELETE. They do NOT cover TRUNCATE —
PostgreSQL fires row-level BEFORE DELETE triggers for DELETE but not for
TRUNCATE — and they do not bind the table owner, who can drop them. Both
gaps close with privilege rather than with more SQL: the application role
must own nothing and hold only SELECT and INSERT on these tables. The GRANT
block is documented in app/db/immutability.sql.

Revision ID: 0002_immutability
Revises: 0001_initial
"""

from alembic import op

revision = "0002_immutability"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

APPEND_ONLY_TABLES = ("audit_log", "vendor_scores", "catalog_versions", "decisions")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vbc_deny_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                '% on % is not permitted: this table is append-only. '
                'Record a correcting entry instead.',
                TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in APPEND_ONLY_TABLES:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE TRIGGER {table}_no_{operation.lower()}
                    BEFORE {operation} ON {table}
                    FOR EACH ROW EXECUTE FUNCTION vbc_deny_mutation();
                """
            )


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        for operation in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{operation} ON {table};")
    op.execute("DROP FUNCTION IF EXISTS vbc_deny_mutation();")
