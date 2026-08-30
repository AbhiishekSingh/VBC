# The database

PostgreSQL 16. Fourteen tables, two migrations, one seeder.

```bash
export VBC_DATABASE_URL="postgresql+psycopg://vbc_app:...@host/vbc"
python -m alembic upgrade head      # schema + immutability triggers
python -m app.db.seed               # catalog: 32 checks, 18 params, 13 rules, 17 templates
```

The seeder is idempotent — safe on every deploy. It only writes a new
`catalog_versions` row when the catalog's content hash actually changes.

---

## The reconstruction problem, and why this schema differs from §13

§13 of the handoff says `raw_response` makes a historical score
reconstructable from the payload it was computed on. That is half of it.

A score is a function of **two** things: the evidence, and the rules applied
to it. Storing raw payloads covers the evidence. But `check_definitions`,
`scan_parameters` and `risk_rules` are seeded, mutable tables — the moment a
provider gets configured or an option string is corrected, a score taken
last year can no longer be reproduced even with every original byte on file,
because the rules moved underneath it.

For most applications that is a curiosity. For an audit product it is the
whole point: *"why was this vendor onboarded"* has to be answerable years
later, to someone not inclined to take our word for it.

So two tables exist that §13 does not list:

| Table | What it holds |
|---|---|
| `catalog_versions` | Immutable, SHA-256-hashed snapshot of the entire catalog as it stood |
| `vendor_scores` | Immutable snapshot of a computed score, citing its catalog version and coverage-policy version, with the full pillar breakdown and risk ledger |

`decisions` points at a **score snapshot**, never at a live recomputation.
`reconstruct_score()` returns a historical score together with whether the
catalog has changed since — so the system can say "these figures are the
record of what was decided, but today's rules would not reproduce them"
rather than leaving someone to discover that for themselves.

---

## Immutability is triggers **and** privileges

`audit_log`, `vendor_scores`, `catalog_versions` and `decisions` reject
`UPDATE` and `DELETE` via trigger (migration `0002`). An audit log that
application code can rewrite is worth very little in the situation it exists
for, so this is a database control rather than a convention.

**The triggers do not cover everything, and this matters at deployment:**

1. **`TRUNCATE` bypasses them.** PostgreSQL fires row-level `BEFORE DELETE`
   triggers for `DELETE` but not for `TRUNCATE`. A role holding that
   privilege can empty the audit trail with the triggers still in place.
2. **The table owner can drop them.** Owning a table means being able to
   remove its triggers.

Both close with privilege, not more SQL. **The application must connect as a
role that owns nothing** and holds only what it needs. The full `GRANT` block
is in `immutability.sql`; the shape of it:

```sql
CREATE ROLE vbc_app LOGIN PASSWORD '...';

-- Ordinary tables: full DML
GRANT SELECT, INSERT, UPDATE, DELETE ON vendors, vendor_checks, … TO vbc_app;

-- Append-only tables: no UPDATE, no DELETE, no TRUNCATE
GRANT SELECT, INSERT ON audit_log, vendor_scores, decisions, catalog_versions TO vbc_app;

-- Catalog: read-only at runtime; the seeder runs as the owner
GRANT SELECT ON check_definitions, scan_parameters, … TO vbc_app;
```

There is no combination of the above that lets the application empty the
audit trail. `test_truncate_bypasses_the_append_only_guard` asserts the gap
explicitly so it does not get forgotten.

---

## Conventions

**Money is always integer paisa.** Never a float, never rupees. FileSure
reports paisa; storing `22000` rather than `220.00` removes every rounding
question. Columns are named `*_paisa` so the unit is visible without
consulting docs.

**NULL is a real state, not missing data.** A `scan_ratings.value` of NULL
means Not Applicable — the parameter leaves *both* sides of the SCAN
fraction. It must not decay into an empty string; there is a test for that.

**Hooks are rows, not absences.** All nine unconfigured checks are seeded
with `state = 'not_configured'`, and `gst` still declares that it would fill
C1–C5. A gap in coverage has to be something a query can name. In an audit
product, silence must never look like a clean result.

**One SCAN parameter, one template.** `manual_field_templates.maps_to` is
UNIQUE where set. Two templates writing the same parameter would make the
score depend on data-entry order, so the constraint lives in the database
rather than in the seeder's memory.

**Overrides require a reason.** A CHECK constraint refuses a decision marked
`is_override` without a substantive `override_reason`. Not to discourage
overrides — Azahan was overridden and the human was right — but so the file
records why.

---

## PII: needs a decision before go-live

`vendor_checks.raw_response` holds real API payloads, and FileSure director
profiles carry **PAN numbers and masked contact details**. This is personal
data under the DPDP Act.

It cannot simply be dropped — it *is* the evidence, and removing it defeats
the reconstruction guarantee above. So the controls have to be:

- **Access**: restrict `SELECT` on `vendor_checks.raw_response` to a
  narrower role than the general application role, or move payloads to a
  separate table with its own grants.
- **Retention**: agree how long payloads are kept after a decision, and
  whether they are redacted (PAN masked, contacts stripped) rather than
  deleted once the retention window closes. Redaction preserves the score's
  reconstructability while shedding the identifiers.

**This is an open question for the client**, alongside §18.1 and §18.2. It is
flagged here rather than silently decided.

---

## Tests

`app/tests/test_database.py` runs against a real PostgreSQL server, not
SQLite. The schema depends on JSONB, CHECK constraints and triggers; a SQLite
approximation would pass while production rejected the same operation, which
is the least useful kind of green test. The suite skips automatically when no
server is reachable.

```bash
VBC_TEST_DATABASE_URL="postgresql+psycopg://.../vbc_test" python -m pytest
```
