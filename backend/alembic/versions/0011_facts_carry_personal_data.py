"""Correct the `facts` column comment: it carries personal data in full.

Migration 0005 created the column with the comment "Carries no PAN, no
unmasked contact detail and no document body." That was true of the
parsers at the time and stopped being true on 9 Nov 2026, when the
person-level parsers stopped masking.

A column comment that describes a property the data does not have is not
cosmetic. It is what a DBA reads when deciding which columns need
narrower grants, and this one said, in the database itself, that `facts`
was the safe half of a pair where in fact both halves now hold a named
individual's PAN, date of birth, email, home addresses and income band.

No data changes. SQLAlchemy keeps `comment=` on the model in step with
whichever migration last set it; if the two drift, `alembic revision
--autogenerate` emits a spurious modify_comment migration on the next
run, which is how a mechanical diff ends up in an unrelated changeset.

Rebuilding the blobs themselves is a SEPARATE step and is deliberately
not done here: `scripts/backfill_facts` re-runs the parsers over the
payloads already on file, with no network calls and no credits. Until it
runs, rows written before PARSER_VERSION 5 still hold the masked strings.
A migration is the wrong place for it — it would run inside the deploy's
schema transaction, over every row, with no way to watch it.

Revision ID: 0011_facts_carry_personal_data
Revises: 0010_many_results_per_check
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_facts_carry_personal_data"
down_revision = "0010_many_results_per_check"
branch_labels = None
depends_on = None


#: Byte-identical to `VendorCheck.facts`'s `comment=` in app/db/models.py.
NEW = (
    "Renderable projection of raw_response. Derived, disposable, "
    "rebuildable by re-running the parser over the payload. Carries "
    "personal data in full, including PAN and contact details: it is "
    "read by the internal evidence screen, never by a client."
)

#: What migration 0005 set, byte for byte.
OLD = (
    "Renderable projection of raw_response. Derived, disposable, "
    "rebuildable by re-running the parser over the payload. Carries "
    "no PAN, no unmasked contact detail and no document body."
)


def _comment(text: str) -> None:
    op.alter_column(
        "vendor_checks",
        "facts",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        comment=text,
        existing_comment=None,
    )


def upgrade() -> None:
    _comment(NEW)


def downgrade() -> None:
    """Restores the old wording.

    Reversible because nothing but a comment moved. Worth saying plainly:
    going back restores a SENTENCE, not a behaviour — the parsers at that
    point would still be whichever version the code is on, so a downgrade
    here can leave the database asserting something about the blobs that
    is not true of them. Downgrading past 0010 is the destructive one.
    """
    _comment(OLD)
