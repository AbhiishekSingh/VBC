"""The vendor's contact number, for the person-level checks.

Five Gridlines checks — identity, digital footprint, address, EPFO
membership and employment history — key on a mobile number, and `vendors`
had nowhere to put one. `spoc` is a name and `designation` a job title;
neither is dialable.

NULLABLE, like every other identifier on this table. Nothing is
compulsory at intake. A vendor with no number simply cannot have those
five run, which the screen reports as a missing input rather than as an
empty result — the distinction this whole product turns on.

TEN CHARACTERS, NOT MORE
------------------------
Stored bare: ten digits, no `+91`, no spaces. `app/domain/validation.py`
enforces `^[6-9]\\d{9}$` at BLOCK level, and the width here is what makes
a wrong format fail loudly at the database rather than quietly at the
provider.

BLOCK rather than WARN is deliberate and worth the sentence. For a CIN, a
typo produces an error. For a mobile number it produces **a different
person's PAN, date of birth and home address**, with nothing in the
response to say so. An unverifiable wrong answer is worse than no answer.

Nothing is backfilled. No vendor has ever had a number recorded, and
inventing one would be inventing a person.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_vendor_contact_mobile"
down_revision = "0008_outage_per_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendors",
        sa.Column("contact_mobile", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    # Dropping the column discards every number recorded against a vendor.
    # That is the intended effect of reversing this migration — the five
    # checks that read it are gone too — but it is not recoverable, and
    # the numbers were typed in by hand.
    op.drop_column("vendors", "contact_mobile")
