"""A failed re-run may take the status. It may not take the evidence.

WHAT HAPPENED
-------------
`vendor_checks` is not one of the append-only tables — the immutability
triggers in migration 0002 cover `audit_log`, `vendor_scores`,
`catalog_versions` and `decisions`, and `immutability.sql` grants the
application UPDATE on `vendor_checks` deliberately. So `_persist` assigning
`row.raw_response = finding.raw` really does destroy what was there.

Fine while every run produced a payload. Not fine when a run FAILS: a
`ProviderError` finding carries `raw=None`, so a re-run that could not
reach the provider replaced a real response with nothing.

Seen live on 14 Sep 2026 — a `casedetail` re-run hit
`INSUFFICIENT_CREDITS: Required: ₹1.50, Available: ₹1.10` and the stored
payload went empty behind a score that had already been computed from it.

WHY IT MATTERS MORE THAN IT LOOKS
---------------------------------
`vendor_scores` IS immutable, and its docstring says the three version
columns "pin the evidence, the rules and the verdict policy". They pin the
catalog and the policy. NOTHING pinned the payload. An unchangeable score
over erasable evidence is worse than either alone, because it looks
defensible and is not.

THE TWO HALVES
--------------
Keeping the old payload is only half right. Showing it as though it were
today's answer would trade one wrong claim for another, so the preserved
facts carry a flag saying what they are.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain import facts as F
from app.domain.types import CheckStatus
from app.providers import factsets as fx
from app.services.runner import CheckRunner, Finding

YESTERDAY = datetime(2026, 9, 13, 11, 18, tzinfo=timezone.utc)

REAL_PAYLOAD = {"cnr": "HCBM010380062022", "orders": [{"filename": "order-1.pdf"}]}


class Row:
    """Just enough VendorCheck for the decision under test."""

    def __init__(self, raw=None, facts=None, fetched_at=YESTERDAY):
        self.raw_response = raw
        self.facts = facts
        self.fetched_at = fetched_at
        self.attempts = 1


def failed(status=CheckStatus.UNAVAILABLE, raw=None) -> Finding:
    return Finding("casedetail", status, "Check failed",
                   "ecourts: HTTP 402 — INSUFFICIENT_CREDITS", raw=raw)


# =====================================================================
# 1 · When the evidence is kept
# =====================================================================

class TestEvidenceIsKept:
    def test_a_failed_rerun_does_not_erase_a_real_payload(self):
        """The case this exists for, exactly as it happened."""
        assert CheckRunner._would_erase_evidence(Row(REAL_PAYLOAD), failed()) is True

    def test_a_payload_that_is_only_our_own_request_echo_counts_as_nothing(self):
        """What the screen showed after the credits failure: a dict holding
        the CIN we sent and a note saying it is not evidence."""
        echo = {"_note": "No payload was stored…", "checkId": "casedetail",
                "request": {"cin": "L17110MH1973PLC019786"}}
        assert CheckRunner._would_erase_evidence(Row(REAL_PAYLOAD), failed(raw=echo)) is True

    @pytest.mark.parametrize("status", [
        CheckStatus.UNAVAILABLE,
        CheckStatus.SKIPPED_MISSING_INPUT,
    ])
    def test_every_unexamined_status_preserves(self, status):
        assert CheckRunner._would_erase_evidence(Row(REAL_PAYLOAD), failed(status)) is True


# =====================================================================
# 2 · When it is correctly overwritten
#
# The half that decides whether this is a safeguard or a bug. Holding
# yesterday's answer over a real one would hide a change in the vendor,
# which is a worse failure than the one being fixed.
# =====================================================================

class TestEvidenceIsReplaced:
    def test_a_successful_rerun_overwrites(self):
        fresh = Finding("casedetail", CheckStatus.PASS, "Case found", "…",
                        raw={"cnr": "X", "orders": []})
        assert CheckRunner._would_erase_evidence(Row(REAL_PAYLOAD), fresh) is False

    def test_an_examined_check_that_returns_nothing_still_overwrites(self):
        """"No charges registered" is an ANSWER. A company that had a charge
        last month and has none today must show none today — keeping the old
        payload would conceal the very change an audit is looking for."""
        empty = Finding("charges", CheckStatus.PASS, "No charges", "…", raw={})
        assert CheckRunner._would_erase_evidence(Row(REAL_PAYLOAD), empty) is False

    def test_a_pending_receipt_overwrites(self):
        """Not evidence, but it carries the poll code that makes the next
        collection free. Losing it turns a paid job into a second charge."""
        pending = failed(raw={"code": "JOB-123", "_pending": True})
        assert CheckRunner._would_erase_evidence(Row(REAL_PAYLOAD), pending) is False

    def test_a_first_run_has_nothing_to_protect(self):
        assert CheckRunner._would_erase_evidence(None, failed()) is False

    def test_a_row_whose_payload_is_already_empty_is_not_protected(self):
        assert CheckRunner._would_erase_evidence(Row(None), failed()) is False
        assert CheckRunner._would_erase_evidence(Row({}), failed()) is False


# =====================================================================
# 3 · Kept evidence must not read as current
# =====================================================================

class TestStaleEvidenceSaysSo:
    def test_the_flag_goes_first(self):
        """Above the numbers it qualifies. A reader who scrolls to a table
        and stops has still been told."""
        facts = F.build(F.DETAIL, fields=[F.field("CNR", "HCBM010380062022")],
                        flags=[F.flag("info", "Something else", "…")])
        marked = fx.mark_superseded(facts, YESTERDAY)
        assert marked["flags"][0]["label"] == "This is the previous response, not today's"

    def test_it_names_the_date_the_evidence_is_from(self):
        marked = fx.mark_superseded(F.build(F.DETAIL, fields=[F.field("A", "b")]),
                                    YESTERDAY)
        assert "13 Sep 2026" in marked["flags"][0]["detail"]

    def test_it_tells_the_reader_what_to_do(self):
        marked = fx.mark_superseded(F.build(F.DETAIL, fields=[F.field("A", "b")]),
                                    YESTERDAY)
        assert "re-run the check before relying on it" in marked["flags"][0]["detail"]

    def test_it_is_a_caveat_not_an_adverse_finding(self):
        """Stale evidence says nothing bad about the vendor. `bad` would put
        a red mark against a company for a failure that was ours."""
        marked = fx.mark_superseded(F.build(F.DETAIL, fields=[F.field("A", "b")]),
                                    YESTERDAY)
        assert marked["flags"][0]["level"] == "warn"

    def test_repeated_failures_do_not_stack_the_same_flag(self):
        """Five failed re-runs must not produce five identical banners."""
        facts = F.build(F.DETAIL, fields=[F.field("A", "b")])
        for _ in range(5):
            facts = fx.mark_superseded(facts, YESTERDAY)
        labels = [f["label"] for f in facts["flags"]]
        assert labels.count("This is the previous response, not today's") == 1

    def test_the_original_facts_survive_intact(self):
        facts = F.build(F.DETAIL, fields=[F.field("CNR", "HCBM010380062022")])
        marked = fx.mark_superseded(facts, YESTERDAY)
        assert marked["fields"] == facts["fields"]
        assert marked["shape"] == facts["shape"]

    def test_a_row_with_no_facts_is_left_alone(self):
        assert fx.mark_superseded(None, YESTERDAY) is None

    def test_a_plain_timestamp_string_still_renders(self):
        """Belt and braces — `fetched_at` is a datetime, but a guard that
        raises inside the failure path would turn a preserved payload into
        a crashed run."""
        marked = fx.mark_superseded(F.build(F.DETAIL, fields=[F.field("A", "b")]),
                                    "2026-09-13T11:18:00Z")
        assert "2026-09-13" in marked["flags"][0]["detail"]


# =====================================================================
# 4 · Through the real _persist
#
# The predicate above is a pure function and easy to get right. The bug
# these tests caught was NOT in it: `row = existing or VendorCheck(...)`
# makes `row` the SAME OBJECT as `existing`, so `row.fetched_at = …` also
# moved `existing.fetched_at`, and the preserved flag reported today as the
# date of yesterday's evidence. Only a test through `_persist` sees that.
# =====================================================================

class FakeSession:
    """Enough of a Session for `_persist`, which now reads and inserts.

    `scalars(...).all()` answers the "how many results does this check
    already have" query; `scalar(...)` answers "is one of them primary".
    """

    def __init__(self, existing=None):
        self._existing = existing
        self.added = []

    def scalar(self, _stmt):
        # Stands in for "the id of the primary result, if there is one".
        return getattr(self._existing, "id", 1) if self._existing else None

    def scalars(self, _stmt):
        return self

    def all(self):
        return [self._existing] if self._existing else []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


class TestThroughPersist:
    """APPENDING MADE THIS GUARANTEE STRUCTURAL.

    These tests were written against a `_persist` that OVERWROTE one row
    per check, where a failed re-run would replace a real payload with
    nothing — observed live, a `casedetail` re-run hitting
    INSUFFICIENT_CREDITS and blanking the response behind an already
    computed score. The protection was a conditional branch that had to
    be got right.

    Results now accumulate: each run is its own row, and the earlier one
    is never written to. The payload cannot be erased because nothing
    touches it. What these tests assert is therefore the same promise,
    held a stronger way — and the failed run is recorded honestly, in a
    row of its own, instead of being half-merged into the old one.
    """

    def build(self, existing, finding):
        from app.services.runner import RunResult

        runner = CheckRunner.__new__(CheckRunner)      # no DB, no providers
        runner.session = FakeSession(existing)
        runner._inputs = lambda _v: {}
        result = RunResult(vendor_id="V1", spend=None)
        result.findings = [finding]

        vendor = type("V", (), {"id": "V1"})()
        runner._persist(vendor, result)
        return existing, runner.session.added

    def test_the_earlier_payload_is_untouched_by_a_failed_rerun(self):
        """Not preserved by a branch — untouched, because nothing writes
        to that row any more."""
        row = Row(REAL_PAYLOAD, facts=F.build(F.DETAIL,
                                              fields=[F.field("CNR", "HCBM…")]))
        before = row.fetched_at
        self.build(row, failed())
        assert row.raw_response == REAL_PAYLOAD
        assert row.fetched_at == before, (
            "the earlier result must keep its own date; it is evidence of "
            "when THAT response was obtained"
        )

    def test_the_failed_run_is_recorded_as_its_own_result(self):
        """It used to be half-merged into the previous row — that row's
        payload with this run's status. Two runs, two rows."""
        row = Row(REAL_PAYLOAD)
        _, added = self.build(row, failed())
        assert len(added) == 1
        assert added[0].raw_response is None
        assert added[0].status == failed().status.value

    def test_a_failed_rerun_does_not_become_the_result_that_counts(self):
        """The one that matters. A check with a real answer must not
        start being scored off a run that returned nothing."""
        row = Row(REAL_PAYLOAD)
        _, added = self.build(row, failed())
        assert added[0].is_primary is False

    def test_the_first_result_counts_without_being_asked(self):
        """A check with an answer and no primary would be plainly
        answered and silently unscored."""
        _, added = self.build(None, failed())
        assert added[0].is_primary is True

    def test_attempts_counts_the_runs_not_the_rows(self):
        row = Row(REAL_PAYLOAD)
        _, added = self.build(row, failed())
        assert added[0].attempts == 2


# =====================================================================
# 5 · The boundary this all rests on
# =====================================================================

class TestTheStatusBoundary:
    def test_only_unexamined_statuses_can_preserve(self):
        """`was_examined` is the same predicate that keeps UNAVAILABLE out
        of the SCAN score. If preservation ever applied to an examined
        status, a stale payload could sit behind a passing check — which is
        the failure mode this whole codebase is built to refuse."""
        row = Row(REAL_PAYLOAD)
        for status in CheckStatus:
            preserved = CheckRunner._would_erase_evidence(
                row, Finding("x", status, "v", "d", raw=None))
            # Exactly the inverse of `was_examined`, for every status in the
            # enum — including any added later.
            assert preserved is not status.was_examined, (
                f"{status.value}: examined={status.was_examined} "
                f"but preserved={preserved}"
            )