"""One result that cannot be stored must not cost the other eleven.

WHAT HAPPENED, 18 NOV 2026
--------------------------
`_persist` added every row to one session and flushed at the end. A
`resolve` result carried `needs_confirmation`, a status the CHECK
constraint on `vendor_checks.status` did not permit, and the failure
did not stay local:

  * the bad INSERT was queued, not executed;
  * the NEXT check's "is one of these primary" SELECT triggered an
    autoflush;
  * the IntegrityError aborted the transaction;
  * every row from that run was lost — including the ones that had
    worked.

Eleven checks ran. Eleven provider calls were billed. Nothing was
saved, and the traceback pointed at the innocent SELECT that happened
to trigger the flush rather than at the row that could not be written.

That is this product's cardinal failure in its most expensive form:
work that was done and paid for, discarded, with nothing on any screen
saying so.

THE FIX IS STRUCTURAL, NOT A PATCH FOR THAT ONE STATUS
------------------------------------------------------
The constraint is corrected in migration 0013, but a constraint is only
one way a row can be refused — a value too long for its column, a
payload that will not serialise, a unique index, a disk that is full.
Any of them would have done the same thing.

So each row now goes in its own SAVEPOINT. A row that cannot be written
rolls back to it, the surrounding transaction stays usable, and every
other check still lands. The refused check is then written AGAIN as
UNAVAILABLE carrying the database's own message, because a result that
silently vanished is indistinguishable from a check nobody selected.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import CheckStatus
from app.services.runner import CheckRunner, Finding, RunResult, _db_reason


class FakeVendor:
    id = "V1"
    name = "Acme Traders"
    legal_name = "Acme Traders Private Limited"
    cin = "U21029MH2013PTC245119"
    domain = "acme.in"
    gst = None
    selected: list[str] = []


class Refusing:
    """A session that rejects rows for one named check.

    Models Postgres honestly in the one way that matters here: the
    SAVEPOINT either commits or rolls back, and a rollback leaves the
    session usable for the next row.
    """

    def __init__(self, refuse: set[str], refuse_always: bool = False):
        self.refuse = refuse
        self.refuse_always = refuse_always
        self.added: list = []
        self.committed: list = []
        self.savepoints = 0

    @contextmanager
    def begin_nested(self):
        self.savepoints += 1
        mark = len(self.added)
        try:
            yield self
            pending = self.added[mark:]
            for row in pending:
                check = getattr(row, "check_id", None)
                if check in self.refuse and (
                    self.refuse_always or getattr(row, "status", "") != "unavailable"
                ):
                    del self.added[mark:]          # rolled back
                    raise IntegrityError(
                        'INSERT INTO vendor_checks ...',
                        {},
                        Exception(
                            'new row for relation "vendor_checks" violates '
                            'check constraint "ck_vendor_checks_status_enum"'
                        ),
                    )
            self.committed.extend(pending)
        except IntegrityError:
            del self.added[mark:]
            raise

    def scalar(self, _stmt):
        return None

    def scalars(self, _stmt):
        return self

    def all(self):
        return []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


def _runner(session) -> CheckRunner:
    runner = CheckRunner.__new__(CheckRunner)
    runner.session = session
    return runner


def _finding(check_id: str, status=CheckStatus.PASS) -> Finding:
    return Finding(check_id, status, f"{check_id} value", "detail")


def _persist(session, *check_ids) -> RunResult:
    vendor = FakeVendor()
    result = RunResult(vendor_id=vendor.id)
    result.findings = [_finding(c) for c in check_ids]
    _runner(session)._persist(vendor, result)
    return result


def _stored(session) -> dict[str, str]:
    return {r.check_id: r.status for r in session.committed}


class TestOneBadRowDoesNotLoseTheRun:
    def test_every_other_check_is_still_written(self):
        """THE REGRESSION. Before the savepoints this stored nothing."""
        s = Refusing({"resolve"})
        _persist(s, "master", "dirs", "resolve", "filings", "ssl")

        stored = _stored(s)
        for ok in ("master", "dirs", "filings", "ssl"):
            assert stored.get(ok) == "pass", f"{ok} was lost with resolve"

    def test_the_checks_after_the_bad_one_survive(self):
        """The old failure surfaced on the NEXT check's query, so the
        rows most at risk are the ones that came after."""
        s = Refusing({"master"})
        _persist(s, "master", "dirs", "filings")
        assert set(_stored(s)) == {"master", "dirs", "filings"}

    def test_several_bad_rows_lose_only_themselves(self):
        s = Refusing({"resolve", "dprof"})
        _persist(s, "master", "resolve", "dirs", "dprof", "ssl")
        stored = _stored(s)
        assert stored["master"] == "pass"
        assert stored["dirs"] == "pass"
        assert stored["ssl"] == "pass"

    def test_a_clean_run_opens_one_savepoint_per_result(self):
        s = Refusing(set())
        _persist(s, "master", "dirs", "ssl")
        assert s.savepoints == 3
        assert len(s.committed) == 3


class TestTheRefusedCheckIsRecordedNotSwallowed:
    def test_it_is_written_again_as_unavailable(self):
        """A result that simply vanished would be indistinguishable
        from a check nobody selected — which is the one confusion this
        product exists to prevent."""
        s = Refusing({"resolve"})
        _persist(s, "master", "resolve")
        assert _stored(s)["resolve"] == "unavailable"

    def test_the_replacement_says_the_call_was_billed(self):
        s = Refusing({"resolve"})
        _persist(s, "resolve")
        row = next(r for r in s.committed if r.check_id == "resolve")
        assert "billed" in row.detail.lower()
        assert "not a finding about the vendor" in row.detail.lower()

    def test_the_replacement_carries_the_cost(self):
        """The money was spent whether or not the answer could be
        stored, and the ledger reads these rows."""
        vendor = FakeVendor()
        result = RunResult(vendor_id=vendor.id)
        result.findings = [
            Finding("resolve", CheckStatus.PASS, "v", "d", cost_paisa=150, credits=2)
        ]
        s = Refusing({"resolve"})
        _runner(s)._persist(vendor, result)

        row = next(r for r in s.committed if r.check_id == "resolve")
        assert row.cost_paisa == 150
        assert row.credits == 2

    def test_the_run_reports_what_it_could_not_store(self):
        s = Refusing({"resolve"})
        result = _persist(s, "master", "resolve")
        assert len(result.storage_errors) == 1
        assert "resolve" in result.storage_errors[0]

    def test_a_clean_run_reports_nothing(self):
        result = _persist(Refusing(set()), "master", "dirs")
        assert result.storage_errors == []

    def test_an_unstorable_placeholder_does_not_raise(self):
        """If even the UNAVAILABLE marker is refused there is nothing
        further to try — but the run must still finish, because the
        other checks' rows are already committed."""
        s = Refusing({"resolve"}, refuse_always=True)
        _persist(s, "master", "resolve", "dirs")
        stored = _stored(s)
        assert stored.keys() == {"master", "dirs"}


class TestTheReasonIsReadable:
    def test_it_keeps_the_first_line_only(self):
        """`IntegrityError.__str__` carries the whole failing INSERT and
        every parameter — fourteen kilobytes of JSON in the case that
        prompted this. That belongs in the log, not in an audit row."""
        exc = IntegrityError(
            "INSERT INTO vendor_checks (...) VALUES (...)",
            {"raw_response": "x" * 14000},
            Exception(
                'new row for relation "vendor_checks" violates check '
                'constraint "ck_vendor_checks_status_enum"\n'
                "DETAIL: Failing row contains (...)"
            ),
        )
        reason = _db_reason(exc)
        assert "violates check constraint" in reason
        assert "DETAIL" not in reason
        assert len(reason) <= 300

    def test_it_never_returns_empty(self):
        assert _db_reason(Exception(""))
