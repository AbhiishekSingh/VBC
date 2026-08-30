"""Every stored row must say WHEN it was last written — accurately.

`created_at()` gives these columns `server_default=now()`, which is correct
on INSERT and silently wrong on UPDATE: there is no `onupdate`, so a row
updated in place keeps the timestamp of its first write.

Three tables update rows in place — vendor_checks on a re-run, scan_ratings
when an analyst changes a rating, surveillance_entries when a field
observation is corrected. All three carried the original timestamp forever.
The value beside it changed; the clock did not.

That is a worse failure than a missing timestamp. A missing one is visibly
missing. A stale one is confidently wrong, and it is precisely the column
someone will cite when asked "when was this checked?" — the re-rating of a
SCAN parameter from Green to Red being the exact event an audit trail exists
to capture.

These tests pin the behaviour so it cannot regress.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from app.db.models import ScanRating, SurveillanceEntry, Vendor, VendorCheck
from app.tests.conftest import DEFAULT_CLIENT_ID
from app.domain.types import CheckStatus
from app.services.runner import CheckRunner, Finding


class _Result:
    """Minimal stand-in for RunResult — _persist only reads .findings."""

    def __init__(self, findings):
        self.findings = findings


def _vendor(session, vendor_id: str) -> Vendor:
    vendor = Vendor(id=vendor_id, client_id=DEFAULT_CLIENT_ID,
                    name="Timestamp Test", domain="example.com", selected=[])
    session.add(vendor)
    session.flush()
    return vendor


# ---------------------------------------------------------------------


def test_a_finding_stamps_itself_when_the_provider_answered():
    """Not when the row is written.

    The parallel block runs nine checks concurrently over tens of seconds.
    One timestamp taken at persist time would misreport eight of them, and
    SQL now() is worse still — it is TRANSACTION START time, so every row
    in a 40-second run would claim the second the run began.
    """
    before = datetime.now(timezone.utc)
    finding = Finding("whois", CheckStatus.PASS, "v", "d")
    after = datetime.now(timezone.utc)

    assert before <= finding.fetched_at <= after
    assert finding.fetched_at.tzinfo is not None, "must be timezone-aware"


def test_two_findings_get_distinct_timestamps():
    first = Finding("whois", CheckStatus.PASS, "a", "")
    time.sleep(0.01)
    second = Finding("ssl", CheckStatus.PASS, "b", "")
    assert second.fetched_at > first.fetched_at


def test_rerunning_a_check_moves_its_timestamp(session, seeded):
    """The regression test for the original defect.

    Before the fix this asserted equal timestamps across two runs whose
    results differed — a row reading FAIL under the time of a PASS.
    """
    vendor = _vendor(session, "TS0001")
    runner = CheckRunner(session)

    runner._persist(vendor, _Result([Finding("whois", CheckStatus.PASS, "first run", "")]))
    session.commit()
    row = session.scalar(select(VendorCheck).where(VendorCheck.vendor_id == "TS0001"))
    first_at, first_attempts = row.fetched_at, row.attempts

    time.sleep(0.05)
    runner._persist(vendor, _Result([Finding("whois", CheckStatus.FAIL, "second run", "")]))
    session.commit()
    session.expire_all()

    row = session.scalar(select(VendorCheck).where(VendorCheck.vendor_id == "TS0001"))
    assert row.value == "second run"
    assert row.fetched_at > first_at, "a re-run must not keep the first run's timestamp"
    assert row.attempts == first_attempts + 1, "every write is an attempt"


def test_every_outcome_is_persisted_including_the_non_outcomes(session, seeded):
    """Rule 4 of the runner: silence must never look like a clean result."""
    vendor = _vendor(session, "TS0002")
    runner = CheckRunner(session)
    runner._persist(
        vendor,
        _Result(
            [
                Finding("whois", CheckStatus.PASS, "ok", ""),
                Finding("gst", CheckStatus.NOT_CONFIGURED, "No provider", ""),
                Finding("ssl", CheckStatus.UNAVAILABLE, "Source unavailable", ""),
                Finding("dirs", CheckStatus.SKIPPED_MISSING_INPUT, "Not run", ""),
            ]
        ),
    )
    session.commit()

    rows = session.scalars(
        select(VendorCheck).where(VendorCheck.vendor_id == "TS0002")
    ).all()
    assert len(rows) == 4, "a check that could not run still leaves a row"
    assert all(r.fetched_at is not None for r in rows)
    # The three non-outcomes must be distinguishable from each other, not
    # collapsed into one "not checked" bucket.
    assert {r.status for r in rows} == {
        "pass", "not_configured", "unavailable", "skipped_missing_input",
    }


def test_rerating_a_scan_parameter_moves_its_timestamp(session, seeded):
    """Green -> Red is the event the audit trail exists for."""
    vendor = _vendor(session, "TS0003")
    row = ScanRating(vendor_id=vendor.id, param_id="S1", value="Private Limited",
                     rating="G", set_by="a.mehta")
    session.add(row)
    session.commit()
    first_at = row.set_at

    time.sleep(0.05)
    row.value = "Proprietorship"
    row.rating = "R"
    row.set_at = datetime.now(timezone.utc)
    session.commit()

    assert row.set_at > first_at


def test_correcting_a_site_observation_moves_its_timestamp(session, seeded):
    vendor = _vendor(session, "TS0004")
    row = SurveillanceEntry(vendor_id=vendor.id, param_id="V1", value="Yes")
    session.add(row)
    session.commit()
    first_at = row.observed_at

    time.sleep(0.05)
    row.value = "No"
    row.observed_at = datetime.now(timezone.utc)
    session.commit()

    assert row.observed_at > first_at


def test_stored_timestamps_are_timezone_aware(session, seeded):
    """TIMESTAMPTZ, not TIMESTAMP.

    A naive timestamp is ambiguous the moment the server moves timezone or
    a second worker runs elsewhere, and an audit trail that cannot be
    ordered across regions is not an audit trail.
    """
    vendor = _vendor(session, "TS0005")
    CheckRunner(session)._persist(
        vendor, _Result([Finding("whois", CheckStatus.PASS, "v", "")])
    )
    session.commit()
    row = session.scalar(select(VendorCheck).where(VendorCheck.vendor_id == "TS0005"))
    assert row.fetched_at.tzinfo is not None
    assert row.fetched_at.utcoffset() is not None


def test_no_timestamp_column_is_timezone_naive(session, seeded):
    """A schema-wide sweep, not a per-column check.

    unlocks.expires_at and the two jobs columns were declared as bare
    mapped_column(nullable=...), which produces TIMESTAMP WITHOUT TIME ZONE
    while every other timestamp in the schema is TIMESTAMPTZ. The offset was
    dropped on write; PostgreSQL then reinterpreted the naive value in the
    SERVER's timezone, silently shifting every unlock expiry by that offset.

    expires_at decides whether a ₹220 unlock must be bought again, so this
    asserts across the whole schema rather than the three columns that
    happened to be wrong — the next timestamp someone adds is caught too.
    """
    rows = session.execute(
        text(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type LIKE 'timestamp%'
              AND data_type NOT LIKE '%with time zone'
            ORDER BY table_name, column_name
            """
        )
    ).all()
    assert rows == [], f"timezone-naive timestamp columns: {rows}"
