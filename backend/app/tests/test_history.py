"""The ledger: every API call, with what it cost, for whom.

Distinct from the audit log and asserted separately, because the two
answer different questions and only one of them can be summed. The audit
log says a result was set aside and why; this says the call still cost
₹5 and whose invoice it lands on.

The assertions that matter most are the two about money:

  * an ignored result is STILL COUNTED. Taking a finding out of the
    score does not refund the call, and a ledger that quietly dropped
    those rows would under-report the bill — the exact defect that
    retiring the delete was meant to close.

  * the totals are the sum of the rows returned. Computed a second way
    they could disagree with the list beneath them, and a page that
    argues with itself about money is worse than no page.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api import routes
from app.api import schemas as s
from app.db.models import Client, Vendor, VendorCheck
from app.domain.types import CheckStatus
from app.services.runner import CheckRunner, Finding, RunResult
from app.tests.conftest import DEFAULT_CLIENT_ID

pytestmark = pytest.mark.usefixtures("seeded")


def _actor():
    return type("U", (), {"email": "a.mehta@q1ssl.com"})()


def _history(**kw):
    """The endpoint, called directly.

    It takes its parameters as `Annotated[..., Query()] = None` rather
    than `= Query(None)` precisely so this works: the second spelling
    makes the DEFAULT the `Query` object, which is truthy, so every
    filter reads as supplied and a date filter raises on an object that
    cannot be sliced. FastAPI hides that when it routes a request.
    """
    return routes.list_history(**kw)


def _client(session, client_id, name):
    client = session.get(Client, client_id)
    if client is None:
        client = Client(id=client_id, name=name, legal_name=name)
        session.add(client)
        session.flush()
    return client


def _vendor(session, vendor_id, name="Ledger Test", client_id=DEFAULT_CLIENT_ID):
    vendor = Vendor(id=vendor_id, client_id=client_id, name=name, selected=[])
    session.add(vendor)
    session.flush()
    return vendor


def _run(session, vendor, check_id, value, cost=0):
    runner = CheckRunner(session)
    result = RunResult(vendor_id=vendor.id, spend=runner.spend)
    result.findings = [Finding(check_id, CheckStatus.PASS, value, "")]
    runner._persist(vendor, result)
    session.flush()
    row = session.scalars(
        select(VendorCheck)
        .where(VendorCheck.vendor_id == vendor.id,
               VendorCheck.check_id == check_id)
        .order_by(VendorCheck.id.desc())
        .limit(1)
    ).one()
    row.cost_paisa = cost
    session.flush()
    return row


class TestTheLedger:
    def test_one_row_per_call_with_the_vendor_and_the_client(
        self, session
    ):
        vendor = _vendor(session, "HIS001", name="Meridian Packaging")
        _run(session, vendor, "ssl", "valid", cost=500)

        out = _history(session=session)
        assert out.totalCalls == 1
        row = out.rows[0]
        assert row.vendorId == "HIS001"
        assert row.vendorName == "Meridian Packaging"
        assert row.clientId == DEFAULT_CLIENT_ID
        assert row.costPaisa == 500

    def test_the_check_is_named_from_the_catalog(self, session):
        """Not stored on the row: a renamed check should read by its
        current name everywhere, and the id travels beside it for anyone
        reconciling against the raw table."""
        vendor = _vendor(session, "HIS002")
        _run(session, vendor, "ssl", "valid")

        row = _history(session=session).rows[0]
        assert row.checkId == "ssl"
        assert row.checkName and row.checkName != "ssl"
        assert row.provider

    def test_an_ignored_call_is_still_counted(self, session):
        """A result taken out of the score was still a call that was
        paid for. This is the whole reason the ledger exists separately
        from the score."""
        vendor = _vendor(session, "HIS003")
        row = _run(session, vendor, "ssl", "valid", cost=500)

        routes.ignore_run(vendor.id, row.id, s.IgnoreIn(reason="wrong subject"),
                          session=session, actor=_actor())

        out = _history(session=session)
        assert out.totalCalls == 1
        assert out.totalCostPaisa == 500
        assert out.rows[0].ignoredAt is not None
        # The REASON travels too: "why is this call on my invoice" is the
        # question this row will be read with.
        assert out.rows[0].ignoreReason == "wrong subject"

    def test_the_totals_are_the_sum_of_the_rows(self, session):
        vendor = _vendor(session, "HIS004")
        _run(session, vendor, "ssl", "a", cost=500)
        _run(session, vendor, "ssl", "b", cost=500)
        _run(session, vendor, "whois", "c", cost=100)

        out = _history(session=session)
        assert out.totalCostPaisa == sum(r.costPaisa for r in out.rows)
        assert out.totalCalls == len(out.rows)
        assert out.totalCostPaisa == 1100

    def test_spend_is_rolled_up_per_client_and_per_vendor(self, session):
        _client(session, "CL900", "Other Client")
        mine = _vendor(session, "HIS005", name="Mine")
        theirs = _vendor(session, "HIS006", name="Theirs", client_id="CL900")
        _run(session, mine, "ssl", "a", cost=500)
        _run(session, theirs, "ssl", "b", cost=200)

        out = _history(session=session)
        by_client = {t.id: t.costPaisa for t in out.byClient}
        by_vendor = {t.id: t.costPaisa for t in out.byVendor}
        assert by_client[DEFAULT_CLIENT_ID] == 500
        assert by_client["CL900"] == 200
        assert by_vendor["HIS005"] == 500
        assert by_vendor["HIS006"] == 200
        # Dearest first — the reader is looking for where the money went.
        assert out.byClient[0].costPaisa >= out.byClient[-1].costPaisa

    def test_filtering_by_vendor_narrows_rows_and_totals_together(
        self, session
    ):
        """If the figure at the top were computed separately it could
        disagree with the list beneath it."""
        mine = _vendor(session, "HIS007", name="Mine")
        other = _vendor(session, "HIS008", name="Other")
        _run(session, mine, "ssl", "a", cost=500)
        _run(session, other, "ssl", "b", cost=900)

        out = _history(vendorId="HIS007", session=session)
        assert [r.vendorId for r in out.rows] == ["HIS007"]
        assert out.totalCostPaisa == 500

    def test_filtering_by_client_narrows_to_that_client(self, session):
        _client(session, "CL901", "Filtered Client")
        mine = _vendor(session, "HIS009", client_id=DEFAULT_CLIENT_ID)
        theirs = _vendor(session, "HIS010", client_id="CL901")
        _run(session, mine, "ssl", "a", cost=500)
        _run(session, theirs, "ssl", "b", cost=700)

        out = _history(clientId="CL901", session=session)
        assert out.totalCostPaisa == 700
        assert {r.vendorId for r in out.rows} == {"HIS010"}

    def test_rows_are_newest_first(self, session):
        vendor = _vendor(session, "HIS011")
        _run(session, vendor, "ssl", "older")
        _run(session, vendor, "ssl", "newer")

        values = [r.value for r in _history(session=session).rows]
        assert values == ["newer", "older"]

    def test_what_was_asked_travels_with_the_row(self, session):
        """On a check run once per director this is the only thing
        telling the rows apart — and on an invoice it is what a client
        would query."""
        vendor = _vendor(session, "HIS012")
        row = _run(session, vendor, "ssl", "valid")
        row.inputs = {"domain": "meridianpack.in"}
        session.flush()

        out = _history(session=session)
        assert out.rows[0].inputs == {"domain": "meridianpack.in"}

    def test_a_malformed_date_filter_narrows_nothing(self, session):
        """It should not 500. A filter nobody can type correctly is a
        filter that takes the page down."""
        vendor = _vendor(session, "HIS013")
        _run(session, vendor, "ssl", "valid", cost=500)

        out = _history(frm="not-a-date", to="??", session=session)
        assert out.totalCalls == 1
