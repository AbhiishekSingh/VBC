"""`CheckStatus` is declared in four places. They must agree.

WHAT WENT WRONG, 18 NOV 2026
----------------------------
`NEEDS_CONFIRMATION` was added to the Python enum when "Attention" was
retired. `vendor_checks.status` has carried a CHECK constraint since
migration 0001 listing the permitted values, and the new one was never
added to it.

So the enum accepted it, the API serialised it, the screen rendered it,
and Postgres refused it. Every check returning that status failed on
INSERT with an IntegrityError — a 500 on the run, AFTER the provider
had been called and the money spent. A new client, a new vendor and
two checks was enough to hit it.

WHY THE SUITE WAS GREEN
-----------------------
916 passed, 129 skipped. The 129 are the DB-backed tests, which skip
when no PostgreSQL is reachable, and they are precisely the ones that
perform a real INSERT. A suite with a skipped section is not green for
a schema change — and nobody reads 129 skips as a warning.

So this file asserts the agreement WITHOUT a database. It reads the
constraint out of the model source and the union out of the TypeScript,
and compares both to the enum. It runs everywhere, every time, and it
fails the moment the four drift apart.

THE FOUR PLACES
---------------
  1. `CheckStatus` in app/domain/types.py                  (the source)
  2. the CHECK constraint in app/db/models.py              (the schema)
  3. the same constraint in an alembic migration           (the database)
  4. the TypeScript union in frontend/src/types/domain.ts  (the client)

Only (3) fails loudly, and only in production.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.domain.types import CheckStatus

BACKEND = pathlib.Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
MODELS = BACKEND / "app" / "db" / "models.py"
MIGRATIONS = BACKEND / "alembic" / "versions"
TS_DOMAIN = REPO / "frontend" / "src" / "types" / "domain.ts"

#: Statuses the ENUM carries. The authority the other three answer to.
EXPECTED = {s.value for s in CheckStatus}


def _quoted(text: str) -> set[str]:
    return set(re.findall(r"'([a-z_]+)'", text))


def _model_constraint() -> set[str]:
    """The `status IN (...)` list on vendor_checks, from the source.

    Read as TEXT rather than through SQLAlchemy's metadata because the
    constraint is a raw SQL string either way — reflecting it would
    only re-parse the same characters with more machinery.
    """
    source = MODELS.read_text()
    # The vendor_checks constraint, not the jobs one: match on the
    # statuses rather than on position in the file.
    for match in re.finditer(r'"status IN \((.*?)\)"', source, re.DOTALL):
        body = match.group(1).replace('"\n', "").replace('"', "")
        values = _quoted(body)
        if "pass" in values:
            return values
    raise AssertionError("no vendor_checks status constraint found in models.py")


class TestTheModelMatchesTheEnum:
    def test_every_status_is_permitted_by_the_constraint(self):
        """THE REGRESSION. A status the enum can produce and the
        database will not store is a 500 on a paid call."""
        missing = EXPECTED - _model_constraint()
        assert not missing, (
            f"{sorted(missing)} can be produced by CheckStatus but is not "
            f"in the vendor_checks CHECK constraint. Add it there AND in a "
            f"new alembic migration — the model alone does not change a "
            f"database that already exists."
        )

    def test_the_constraint_permits_nothing_the_enum_cannot_produce(self):
        """A value the database allows and the code cannot make is dead,
        and usually means a rename happened in one place only."""
        extra = _model_constraint() - EXPECTED
        assert not extra, f"{sorted(extra)} is permitted but unreachable"

    def test_warn_is_still_permitted(self):
        """RETIRED IS NOT REMOVED. Rows written before 17 Nov 2026 hold
        `warn`, and a CHECK is enforced on UPDATE as well as INSERT —
        dropping it would make every historical row unwritable, so
        setting one aside would fail."""
        assert "warn" in _model_constraint()


class TestAMigrationCarriesItToTheDatabase:
    def test_some_migration_permits_every_status(self):
        """The model is what SQLAlchemy would CREATE from nothing. An
        existing database only changes when a migration says so.

        ANY migration containing the full set satisfies this, rather
        than the newest one. A migration file holds the list twice —
        once in `upgrade`, once in the narrower `downgrade` — and
        taking "the last match in the newest file" picks the downgrade,
        which is how this test failed against the very migration
        written to fix the bug it was written to catch.

        Distinguishing the two would mean parsing which function each
        string sits in. Not worth it: the question here is "did anyone
        write a migration for this status", and a superset anywhere in
        the history answers it.
        """
        seen: list[set[str]] = []
        for path in sorted(MIGRATIONS.glob("*.py")):
            for match in re.finditer(r"status IN \(([^)]*)\)", path.read_text()):
                values = _quoted(match.group(1))
                if "pass" in values:
                    seen.append(values)
        assert seen, "no migration defines the vendor_checks status list"
        if any(EXPECTED <= values for values in seen):
            return
        missing = EXPECTED - set().union(*seen)
        assert not missing, (
            f"{sorted(missing)} is in the enum and in the model but no "
            f"migration adds it to the database. The deployed schema will "
            f"reject it on INSERT."
        )
        raise AssertionError(
            "no single migration permits every status — the lists found "
            f"were {[sorted(v) for v in seen]}"
        )


class TestTheClientAgrees:
    @pytest.mark.skipif(not TS_DOMAIN.exists(), reason="frontend not present")
    def test_the_typescript_union_has_the_same_members(self):
        """`CheckStatus` is also a union in types/domain.ts, and
        STATUS_LABEL is keyed by it — a missing member there renders as
        `undefined` in a badge rather than failing a build."""
        source = TS_DOMAIN.read_text()
        block = source[source.index("export type CheckStatus ="):]
        block = block[: block.index("export type RuleState")]
        union = set(re.findall(r"\|\s*'([a-z_]+)'", block))
        assert union == EXPECTED, (
            f"TypeScript and Python disagree — only in TS: "
            f"{sorted(union - EXPECTED)}; only in Python: "
            f"{sorted(EXPECTED - union)}"
        )
