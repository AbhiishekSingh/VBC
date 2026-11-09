"""Many results per check, and exactly one that counts.

WHY THIS EXISTS
---------------
A check used to hold one result and a re-run overwrote it. That lost
the thing the work is actually made of: an analyst reads the director
list off MCA, takes each director's number, and runs the person checks
once per director — and the second run erased the first.

Results now accumulate. Exactly one per (vendor, check) is PRIMARY, and
that is the one SCAN, the risk score and the report read.

The three things that must hold, and each is a way this goes quietly
wrong:

  1. A check with results always has a primary. One without would be
     plainly answered and silently unscored, which is the exact failure
     this product exists to prevent.
  2. A new run does NOT steal primary. Promoting the newest would move a
     client-facing number every time somebody tried a different input,
     without anybody choosing it.
  3. Deleting the primary promotes, rather than leaving the check
     unscored — and what was deleted survives in the audit log, because
     the row does not.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, VendorCheck, Vendor
from app.domain.types import CheckStatus
from app.services.runner import CheckRunner, Finding, RunResult
from app.tests.conftest import DEFAULT_CLIENT_ID


def _vendor(session, vendor_id="RUN001", **kw):
    vendor = Vendor(id=vendor_id, client_id=DEFAULT_CLIENT_ID,
                    name="Run Test", selected=[], **kw)
    session.add(vendor)
    session.flush()
    return vendor


def _run(session, vendor, check_id, value, status=CheckStatus.PASS):
    runner = CheckRunner(session)
    result = RunResult(vendor_id=vendor.id, spend=runner.spend)
    result.findings = [Finding(check_id, status, value, "")]
    runner._persist(vendor, result)
    session.flush()
    return result


def _rows(session, vendor_id, check_id):
    return session.scalars(
        select(VendorCheck)
        .where(VendorCheck.vendor_id == vendor_id,
               VendorCheck.check_id == check_id)
        .order_by(VendorCheck.fetched_at, VendorCheck.id)
    ).all()


class TestResultsAccumulate:
    def test_a_rerun_adds_rather_than_replaces(self, session, seeded):
        vendor = _vendor(session)
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")
        _run(session, vendor, "ssl", "third")

        rows = _rows(session, vendor.id, "ssl")
        assert [r.value for r in rows] == ["first", "second", "third"]

    def test_the_first_result_counts_without_being_asked(self, session, seeded):
        """A check with an answer and no primary is plainly answered and
        silently unscored."""
        vendor = _vendor(session, "RUN002")
        _run(session, vendor, "ssl", "only")
        assert _rows(session, vendor.id, "ssl")[0].is_primary is True

    def test_a_later_run_does_NOT_steal_what_counts(self, session, seeded):
        """Promoting the newest would move a client-facing number every
        time somebody tried a different input, without anybody choosing
        it."""
        vendor = _vendor(session, "RUN003")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")

        rows = _rows(session, vendor.id, "ssl")
        assert [r.is_primary for r in rows] == [True, False]

    def test_every_run_counts_as_an_attempt(self, session, seeded):
        vendor = _vendor(session, "RUN004")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")
        assert [r.attempts for r in _rows(session, vendor.id, "ssl")] == [1, 2]

    def test_each_result_keeps_the_inputs_it_RAN_with(self, session, seeded):
        """`vendor_check_inputs` holds one value per key, so it reflects
        whatever was typed LAST. Four runs against four directors would
        otherwise all claim the fourth director's number."""
        from app.db.models import VendorCheckInput

        vendor = _vendor(session, "RUN005", domain="first.example")
        _run(session, vendor, "ssl", "run one")

        session.add(VendorCheckInput(vendor_id=vendor.id, check_id="ssl",
                                     key="domainName", value="second.example"))
        session.flush()
        _run(session, vendor, "ssl", "run two")

        rows = _rows(session, vendor.id, "ssl")
        assert rows[0].inputs.get("domainName") == "first.example"
        assert rows[1].inputs.get("domainName") == "second.example"

    def test_the_snapshot_includes_a_value_taken_from_the_vendor(
        self, session, seeded
    ):
        """A blank box whose value came off the vendor record is still
        what was sent, and "What was asked" showing nothing for a call
        that plainly had an argument is how an analyst stops trusting
        the panel."""
        vendor = _vendor(session, "RUN006", domain="meridian.example")
        _run(session, vendor, "ssl", "ran")
        assert _rows(session, vendor.id, "ssl")[0].inputs == {
            "domainName": "meridian.example"
        }


class TestOnlyOneCounts:
    def test_two_primaries_are_refused_by_the_DATABASE(self, session, seeded):
        """Not by whoever remembers to check. SCAN, the risk score and
        the report all read "the primary result", and two of those is
        not a thing that can be rendered or defended."""
        from sqlalchemy.exc import IntegrityError

        vendor = _vendor(session, "RUN007")
        session.add(VendorCheck(vendor_id=vendor.id, check_id="ssl",
                                status="pass", is_primary=True))
        session.flush()
        session.add(VendorCheck(vendor_id=vendor.id, check_id="ssl",
                                status="pass", is_primary=True))
        with pytest.raises(IntegrityError):
            session.flush()

    def test_marking_one_clears_the_other(self, session, seeded):
        from app.api import routes

        vendor = _vendor(session, "RUN008")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")
        rows = _rows(session, vendor.id, "ssl")

        routes.mark_primary(vendor.id, rows[1].id, session=session,
                            actor=_actor())
        session.expire_all()
        assert [r.is_primary for r in _rows(session, vendor.id, "ssl")] \
            == [False, True]

    def test_the_change_is_written_to_the_audit_log_with_a_name(
        self, session, seeded
    ):
        """It moves a number a client sees, on a vendor that may already
        be scored. "Why did this finding change between Tuesday and
        Friday" has to have an answer."""
        from app.api import routes

        vendor = _vendor(session, "RUN009")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")
        rows = _rows(session, vendor.id, "ssl")

        routes.mark_primary(vendor.id, rows[1].id, session=session,
                            actor=_actor())
        entries = session.scalars(
            select(AuditLog).where(AuditLog.vendor_id == vendor.id)
        ).all()
        changed = [e for e in entries if e.action == "CHECK_PRIMARY_CHANGED"]
        assert len(changed) == 1
        assert changed[0].actor == "a.mehta@q1ssl.com"
        assert "second" in changed[0].detail
        assert "first" in changed[0].detail


class TestDeleting:
    def test_deleting_the_primary_PROMOTES_rather_than_unscoring(
        self, session, seeded
    ):
        """A check left with results and no primary is plainly answered
        and silently uncounted."""
        from app.api import routes

        vendor = _vendor(session, "RUN010")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")
        rows = _rows(session, vendor.id, "ssl")

        routes.delete_run(vendor.id, rows[0].id, session=session,
                          actor=_actor())
        session.expire_all()
        left = _rows(session, vendor.id, "ssl")
        assert len(left) == 1
        assert left[0].value == "second"
        assert left[0].is_primary is True

    def test_deleting_a_non_primary_leaves_the_primary_alone(
        self, session, seeded
    ):
        from app.api import routes

        vendor = _vendor(session, "RUN011")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")
        rows = _rows(session, vendor.id, "ssl")

        routes.delete_run(vendor.id, rows[1].id, session=session,
                          actor=_actor())
        session.expire_all()
        left = _rows(session, vendor.id, "ssl")
        assert [r.value for r in left] == ["first"]
        assert left[0].is_primary is True

    def test_the_last_result_can_go_and_the_check_reads_as_never_run(
        self, session, seeded
    ):
        from app.api import routes

        vendor = _vendor(session, "RUN012")
        _run(session, vendor, "ssl", "only")
        rows = _rows(session, vendor.id, "ssl")

        routes.delete_run(vendor.id, rows[0].id, session=session,
                          actor=_actor())
        session.expire_all()
        assert _rows(session, vendor.id, "ssl") == []

    def test_what_was_deleted_survives_in_the_audit_log(
        self, session, seeded
    ):
        """The row is going and the log is append-only, so the log is
        the only place it can survive."""
        from app.api import routes

        vendor = _vendor(session, "RUN013")
        _run(session, vendor, "ssl", "the one deleted")
        rows = _rows(session, vendor.id, "ssl")

        routes.delete_run(vendor.id, rows[0].id, session=session,
                          actor=_actor())
        entries = session.scalars(
            select(AuditLog).where(AuditLog.vendor_id == vendor.id)
        ).all()
        deleted = [e for e in entries if e.action == "CHECK_RESULT_DELETED"]
        assert len(deleted) == 1
        assert "the one deleted" in deleted[0].detail
        assert "it was the result that counted" in deleted[0].detail

    def test_a_run_belonging_to_another_vendor_is_a_404(
        self, session, seeded
    ):
        from fastapi import HTTPException

        from app.api import routes

        mine = _vendor(session, "RUN014")
        theirs = _vendor(session, "RUN015")
        _run(session, theirs, "ssl", "not yours")
        row = _rows(session, theirs.id, "ssl")[0]

        with pytest.raises(HTTPException) as caught:
            routes.delete_run(mine.id, row.id, session=session, actor=_actor())
        assert caught.value.status_code == 404


class TestWhatTheApiServes:
    def test_checks_holds_the_PRIMARY_not_the_newest(self, session, seeded):
        """The scoring engine takes this map. If it held the newest, the
        score would move on every re-run — which is exactly what marking
        exists to prevent."""
        from app.api import routes

        vendor = _vendor(session, "RUN016")
        _run(session, vendor, "ssl", "the one that counts")
        _run(session, vendor, "ssl", "a later try")

        out = routes._serialise(session, vendor)
        assert out.checks["ssl"].value == "the one that counts"
        assert out.checks["ssl"].isPrimary is True

    def test_runs_holds_every_result_newest_first(self, session, seeded):
        from app.api import routes

        vendor = _vendor(session, "RUN017")
        _run(session, vendor, "ssl", "first")
        _run(session, vendor, "ssl", "second")

        values = [r.value for r in routes._serialise(session, vendor).runs]
        assert values == ["second", "first"]

    def test_each_served_run_carries_its_own_inputs(self, session, seeded):
        from app.api import routes

        vendor = _vendor(session, "RUN018", domain="meridian.example")
        _run(session, vendor, "ssl", "ran")
        run = routes._serialise(session, vendor).runs[0]
        assert run.inputs == {"domainName": "meridian.example"}
        assert run.id is not None


def _actor():
    return type("U", (), {"email": "a.mehta@q1ssl.com"})()
