"""Every migration must be readable without running one.

WHAT BROKE, 18 NOV 2026
-----------------------
Migration 0013 declared a module constant:

    CONSTRAINT = op.f("ck_vendor_checks_status_enum")

`op` is a PROXY. It is bound when a migration is actually running, and
at no other time. `alembic upgrade` worked, because by the time the
revision modules were imported the proxy existed. But

    alembic heads
    alembic history

only IMPORT the revision files — they never start a migration — so both
died with

    NameError: Can't invoke function 'f', as the proxy object has not
    yet been established for the Alembic 'Operations' class.

The deploy was fine and the schema was correct. What was lost was the
ability to ASK about the schema: the two commands you reach for while
debugging a migration problem were exactly the two that no longer ran.
Nobody notices until the day they need them, which is the worst day to
find out.

WHY A TEST AND NOT JUST A FIX
-----------------------------
The fix is one line moved inside a function. The mistake is not —
`op.create_check_constraint`, `op.f`, `sa.text` through `op`, any of
them at module level does the same thing, and the next migration is
written by someone who has never read this file.

So this asserts the property rather than the line: the revision history
must be walkable with no database, no migration context and no proxy.
It costs milliseconds and it fails on the commit that breaks it rather
than on the day someone needs `alembic history`.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "alembic" / "versions"
MIGRATIONS = sorted(VERSIONS.glob("[0-9]*.py"))


def _load(path: pathlib.Path):
    """Import a revision file COLD — exactly as alembic's ScriptDirectory
    does when it is only listing revisions."""
    spec = importlib.util.spec_from_file_location(f"_rev_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_there_are_migrations_to_check():
    """A glob that silently matches nothing would make every assertion
    below vacuously true."""
    assert MIGRATIONS, f"no migration files found under {VERSIONS}"


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.stem)
def test_a_migration_imports_without_a_live_operations_proxy(path):
    """THE REGRESSION. 0013 raised NameError here.

    Anything that touches `op` belongs inside `upgrade`, `downgrade` or
    a helper they call — never at module level.
    """
    try:
        _load(path)
    except NameError as exc:  # pragma: no cover - the failure path
        pytest.fail(
            f"{path.name} cannot be imported without a running migration: "
            f"{exc}\n\nSomething in it calls `op` at module level. `op` is a "
            f"proxy bound only while a migration runs, so `alembic heads` "
            f"and `alembic history` will both fail. Move the call inside a "
            f"function."
        )


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.stem)
def test_a_migration_declares_its_place_in_the_chain(path):
    module = _load(path)
    assert getattr(module, "revision", None), f"{path.name} has no revision id"
    assert hasattr(module, "down_revision"), f"{path.name} has no down_revision"


def test_the_whole_history_walks_from_a_single_head():
    """What `alembic heads` actually answers, without the CLI or a DB.

    A second head means two migrations claim the same parent, and
    `upgrade head` then refuses to run at all.
    """
    modules = [_load(p) for p in MIGRATIONS]
    revisions = {m.revision for m in modules}
    parents = {m.down_revision for m in modules if m.down_revision}

    heads = revisions - parents
    assert len(heads) == 1, (
        f"expected one head, found {sorted(heads)} — two migrations share a "
        f"parent, and `alembic upgrade head` will refuse to choose"
    )

    missing = parents - revisions
    assert not missing, f"down_revision points at revisions that do not exist: {sorted(missing)}"


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.stem)
def test_a_revision_id_fits_the_version_table(path):
    """`alembic_version.version_num` is varchar(32).

    An over-long id lets every statement in the migration succeed and
    then fails on the final `UPDATE alembic_version`, rolling the whole
    thing back — a migration that does its work and cannot record that
    it did. Cost an hour on 0013's first draft, at 37 characters.
    """
    revision = _load(path).revision
    assert len(revision) <= 32, (
        f"{path.name}: revision id '{revision}' is {len(revision)} characters; "
        f"alembic_version.version_num holds 32"
    )
