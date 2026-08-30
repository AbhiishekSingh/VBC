"""Every normaliser must FAIL LOUDLY when it cannot read a real response.

This file exists because of a pattern, not a bug. Four adapter defects have
been found against live data — a WhoisXML date field, archive.org redirect
statuses, a FileSure XBRL prefix, a FileSure director flag — and all four
behaved identically: the HTTP call succeeded, the normaliser found nothing,
and the check reported clean. Nothing raised. Nothing logged. The defect was
invisible until a human read a payload by eye.

Every adapter in this codebase was written from a reference document, and
every time a document has been checked against live data it has been wrong.
Most endpoints have never been checked at all. So the tests below do not
assert that the adapters are correct — they cannot. They assert something
weaker and far more useful: that when an adapter is WRONG, it says so.

Each test reconstructs the shape of a response the adapter does not
understand and asserts ProviderParseGap. The first four reconstruct the
historical bugs, and each one fails on the pre-fix code.
"""

from __future__ import annotations

import pytest

from app.providers.archive import ArchiveProvider
from app.providers.base import ParseGuard, ProviderParseGap, has_content
from app.providers.filesure import (
    normalise_charges,
    normalise_directors,
    normalise_financials,
    normalise_master,
)
from app.providers.whoisxml import _summarise_history

# ---------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------


def test_zero_and_false_are_real_values():
    """A reputation score of 0 is the WORST score, not a missing one.

    Treating it as absent would report the most adverse possible finding as
    a coverage gap.
    """
    assert has_content(0) is True
    assert has_content(False) is True
    assert has_content(None) is False
    assert has_content("") is False
    assert has_content([]) is False
    assert has_content({}) is False


def test_an_empty_payload_is_not_a_gap():
    """Absence of data is a legitimate finding and must pass through.

    This is the half that keeps the guard honest. If it tripped on empty
    input it would turn every genuinely clean result into a false alarm,
    and it would be switched off within a week.
    """
    guard = ParseGuard("test")
    guard.expect("status", raw={}, parsed=None)
    guard.expect("rows", raw=[], parsed=[])
    guard.raise_if_gaps()  # must not raise


def test_all_gaps_are_reported_at_once():
    """One run surfaces every broken field, not one per redeploy."""
    guard = ParseGuard("test")
    guard.expect("alpha", raw={"a": 1}, parsed=None)
    guard.expect("beta", raw={"b": 2}, parsed=None)
    with pytest.raises(ProviderParseGap) as excinfo:
        guard.raise_if_gaps()
    assert "alpha" in str(excinfo.value)
    assert "beta" in str(excinfo.value)
    assert "2 field(s)" in str(excinfo.value)


# ---------------------------------------------------------------------
# The four historical bugs, each now caught
# ---------------------------------------------------------------------


def test_unknown_xbrl_taxonomy_is_a_gap_not_a_company_with_no_revenue():
    """Regression for the ind-as prefix bug.

    Before the guard this returned revenue=None, net_worth=None and a
    perfectly clean-looking result for a company whose financials had been
    filed, fetched and PAID FOR.
    """
    payload = {
        "profit_and_loss": [
            {"qname": "some-future-taxonomy:Turnover", "value": 999, "unit": "INR"}
        ],
    }
    with pytest.raises(ProviderParseGap, match="revenue / net worth"):
        normalise_financials(payload)


def test_renamed_whois_date_field_is_a_gap_not_a_domain_with_no_age():
    """Regression for the createdDateISO8601 bug.

    Ownership records present, no creation date parsed. Before the guard,
    every domain silently got age_years=None, so risk rule r4 could never
    fire against any vendor.
    """
    records = [{"registrarName": "Some Registrar", "createdDateSomethingNew": "2015-01-01"}]
    with pytest.raises(ProviderParseGap, match="created"):
        _summarise_history(records)


def test_renamed_director_flag_is_a_gap_not_a_clean_board():
    """Regression for the isDisqualified bug — the dangerous direction.

    If neither disqualification field name is present, the flag is not being
    read at all. Reporting that as "no directors disqualified" is a missed
    adverse finding, which nobody investigates because the check is green.
    """
    payload = {
        "masterData": {
            "directorData": [
                {"DIN": "1", "FirstName": "A", "LastName": "B",
                 "someFutureDisqualifiedField": "Y"}
            ]
        }
    }
    with pytest.raises(ProviderParseGap, match="disqualification flag"):
        normalise_directors(payload)


def test_reordered_cdx_columns_are_a_gap_not_a_timeline():
    """CDX rows are POSITIONAL.

    A column-order change would map timestamps onto status codes and produce
    a complete, plausible, entirely fictional outage timeline — worse than
    an error, because it reads as evidence.
    """
    provider = ArchiveProvider.__new__(ArchiveProvider)  # no HTTP needed
    rows = [
        ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
        # Two columns instead of seven: nothing positional can be trusted.
        ["in,example)/", "20240101000000"],
    ]

    class _Response:
        payload = rows

    provider.request = lambda *a, **k: _Response()  # type: ignore[method-assign]

    class _Settings:
        wayback_base_url = "https://web.archive.org"

    provider.settings = _Settings()  # type: ignore[assignment]

    with pytest.raises(ProviderParseGap, match="statuscode"):
        provider.timeline("example.com")


# ---------------------------------------------------------------------
# Endpoints whose live shape NOBODY HAS EVER SEEN
# ---------------------------------------------------------------------
#
# These are the ones the guard was really built for. We do not know what
# company master or charges actually return. These tests do not claim the
# adapters read them correctly — they claim that if the adapters do not, the
# result is a visible coverage gap rather than a clean report.


def test_renamed_master_block_is_a_gap():
    payload = {"masterData": {"companyData": {"someFutureStatusField": "Active"}}}
    with pytest.raises(ProviderParseGap, match="status"):
        normalise_master(payload)


def test_master_with_no_company_data_at_all_is_not_a_gap():
    """Nothing came back, so nothing failed to parse. The runner reports the
    emptiness on its own; the guard must stay quiet."""
    assert normalise_master({})["status"] is None


def test_renamed_charge_fields_are_a_gap_not_a_zero_rupee_charge():
    """An open secured charge read as ₹0 understates a vendor's obligations."""
    payload = {"masterData": {"indexChargesData": [{"someFutureAmountField": 5000000}]}}
    with pytest.raises(ProviderParseGap, match="amount"):
        normalise_charges(payload)


def test_a_company_with_genuinely_no_charges_passes_clean():
    """The single most important negative case in this file.

    "No charges filed" is a real, common, clean finding. If the guard
    flagged it, every unencumbered vendor would come back as a coverage gap
    and the guard would be disabled.
    """
    result = normalise_charges({"masterData": {"indexChargesData": []}})
    assert result["open"] == []
    assert result["open_total"] == 0


# ---------------------------------------------------------------------
# A paid response that cannot be read must be KEPT
# ---------------------------------------------------------------------


def test_the_gap_carries_the_payload_that_could_not_be_read():
    """Regression for a ₹5 lesson.

    The first time a parse gap fired against the live API it cost ₹5,
    reported the problem correctly — and threw the response away. The
    normaliser raised, the runner caught an exception with nothing attached,
    and the one artefact needed to fix the adapter was gone. The error text
    even claimed the response was "stored for inspection". It was not.

    A parse gap is the most valuable payload in the system: a response
    already PAID FOR that this code cannot read. Diagnosing it must never
    require buying the call again.
    """
    payload = {"masterData": {"companyData": {"someFutureStatusField": "Active"}}}
    with pytest.raises(ProviderParseGap) as excinfo:
        normalise_master(payload)

    assert excinfo.value.payload == payload, "the unreadable response must survive"


def test_every_normaliser_attaches_its_payload():
    """Not just master — a gap anywhere must keep its evidence."""
    cases = [
        (normalise_directors,
         {"masterData": {"directorData": [{"DIN": "1", "futureField": "x"}]}}),
        (normalise_charges,
         {"masterData": {"indexChargesData": [{"someFutureAmountField": 500}]}}),
        (normalise_financials,
         {"profit_and_loss": [{"qname": "future:Turnover", "value": 1, "unit": "INR"}]}),
    ]
    for normaliser, payload in cases:
        with pytest.raises(ProviderParseGap) as excinfo:
            normaliser(payload)
        assert excinfo.value.payload is not None, f"{normaliser.__name__} dropped its payload"


def test_the_runner_persists_the_unreadable_payload():
    """The finding must carry it through to vendor_checks.raw_response."""
    from app.domain.types import CheckStatus

    payload = {"masterData": {"companyData": {"someFutureStatusField": "Active"}}}
    gap = ProviderParseGap("filesure.master: unreadable", payload=payload)

    # The shape the runner's except-ProviderParseGap branch produces.
    from app.services.runner import Finding

    finding = Finding(
        "master", CheckStatus.UNAVAILABLE, "Response not understood",
        f"{gap} This is an adapter defect, not a finding about the vendor.",
        raw={"_parse_gap": str(gap), "_note": "...", "payload": gap.payload},
        error=str(gap),
    )
    assert finding.status is CheckStatus.UNAVAILABLE
    assert finding.raw["payload"] == payload
