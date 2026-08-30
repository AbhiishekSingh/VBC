"""Regression tests built from REAL FileSure responses.

Every payload below was captured from the live API, not written from the
reference document. That distinction is the whole point of this file: each
test here corresponds to a place where the documented shape and the actual
shape disagreed, and where the adapter had been reading the documented one.

Three of these were silent failures — no exception, no error status, just a
missing figure or an inverted boolean reaching a client-facing audit report.
"""

from __future__ import annotations

from app.providers.base import as_bool, is_blank
from app.providers.filesure import (
    normalise_directors,
    normalise_financials,
    normalise_form_id,
)

# ---------------------------------------------------------------------
# Real payloads
# ---------------------------------------------------------------------

#: GET /v1/companies/{cin}/extractions/AOC-4/2024 — abbreviated to the
#: triples under test, with the qnames and values exactly as returned.
REAL_EXTRACTION = {
    "filing_scope": "standalone",
    "period_start": "2023-04-01",
    "period_end": "2024-03-31",
    # NOT "in-ca:Schedule3IndAS" as documented.
    "taxonomy_id": "ind-as-2017",
    "profit_and_loss": [
        {"qname": "ind-as:RevenueFromOperations", "value": 66759700000, "unit": "INR"},
        {"qname": "ind-as:ProfitBeforeTax", "value": -5167900000, "unit": "INR"},
    ],
    "balance_sheet": [
        {"qname": "ind-as:Equity", "value": 16751400000, "unit": "INR"},
        {"qname": "in-ca:NetWorthOfCompany", "value": 16751400000, "unit": "INR"},
    ],
    "metadata": {
        "source": {
            "vpd_version": "v2",
            # NOT "dateOfFiling", and ISO rather than DD/MM/YYYY.
            "filingDate": "2024-12-01T00:00:00.000Z",
        },
        "entity_identifier": "L00000MH0000PLC000000",
        "company": "EXAMPLE LIMITED",
    },
}

#: A DIRECTOR PROFILE row (GET /v1/directors/{din}), which puts the flags
#: on the row itself. Company master nests the same facts inside
#: MCAUserRole instead — see test_filesure_master_live.py. Both shapes are
#: live, so the adapter reads both.
REAL_DIRECTOR_ROW = {
    "DIN": "05341082",
    "FirstName": "ASHA",
    "LastName": "SHARMA",
    "dateOfAppointment": "04/06/2013",
    # NOT "DirectorDisqualified": "true"/"false".
    "isDisqualified": "N",
    # Empty string, NOT null, for a director who is still serving.
    "cessationDate": "",
    "directorFlag": "Y",
    "MCAUserRole": ["Director"],
}


# ---------------------------------------------------------------------
# A) XBRL taxonomy prefix
# ---------------------------------------------------------------------


def test_ind_as_revenue_and_equity_are_read():
    """The documented prefix was "in-ca:"; the live filer uses "ind-as:".

    Reading only the documented prefix returned revenue=None and
    net_worth=None on a company with perfectly good filed financials — so
    SCAN N3 could never rate and risk rule r3 could never fire. Nothing
    errored; the finding simply went missing.
    """
    result = normalise_financials(REAL_EXTRACTION)
    assert result["revenue"] == 66759700000
    assert result["net_worth"] == 16751400000
    assert result["positive_net_worth"] is True


def test_figures_keep_the_verbatim_qname_for_citation():
    result = normalise_financials(REAL_EXTRACTION)
    equity = result["figures"]["ind-as:Equity"]
    assert equity["qname"] == "ind-as:Equity"
    assert equity["label"] == "Equity / net worth"


def test_equity_wins_over_net_worth_when_both_are_present():
    """Both appear, with the same value. Preference must be deterministic."""
    result = normalise_financials(REAL_EXTRACTION)
    assert result["net_worth"] == REAL_EXTRACTION["balance_sheet"][0]["value"]


def test_a_missing_qname_is_absent_rather_than_zero():
    """Missing data must never be reported as a figure of nil."""
    result = normalise_financials({"balance_sheet": [], "profit_and_loss": []})
    assert result["revenue"] is None
    assert result["net_worth"] is None
    assert result["positive_net_worth"] is False


def test_the_documented_in_ca_prefix_still_works():
    """Older payloads must not break while fixing the new shape."""
    result = normalise_financials(
        {"profit_and_loss": [
            {"qname": "in-ca:RevenueFromOperations", "value": 500, "unit": "INR"}
        ]}
    )
    assert result["revenue"] == 500


# ---------------------------------------------------------------------
# B) metadata.source shape
# ---------------------------------------------------------------------


def test_filing_date_is_read_from_the_real_field_name():
    """metadata.source.dateOfFiling does not exist in a real response."""
    result = normalise_financials(REAL_EXTRACTION)
    assert result["filed_on"] == "2024-12-01"


def test_taxonomy_is_reported_as_filed():
    result = normalise_financials(REAL_EXTRACTION)
    assert result["taxonomy"] == "ind-as-2017"


# ---------------------------------------------------------------------
# C) Director flags — the dangerous one
# ---------------------------------------------------------------------


def test_y_means_true():
    """as_bool("Y") returning False would read a DISQUALIFIED director as clean.

    This is the missed-adverse-finding direction: worse than a false flag,
    because nobody investigates a check that came back green.
    """
    assert as_bool("Y") is True
    assert as_bool("N") is False
    assert as_bool("false") is False
    assert as_bool("true") is True


def test_a_clean_director_reads_clean():
    [director] = normalise_directors({"masterData": {"directorData": [REAL_DIRECTOR_ROW]}})
    assert director["disqualified"] is False
    assert director["din"] == "05341082"
    assert director["name"] == "ASHA SHARMA"
    # MM/DD/YYYY — see test_slashed_dates_are_month_first.
    assert director["appointed_on"] == "2013-04-06"


def test_a_disqualified_director_is_flagged():
    row = dict(REAL_DIRECTOR_ROW, isDisqualified="Y")
    [director] = normalise_directors({"masterData": {"directorData": [row]}})
    assert director["disqualified"] is True


def test_the_documented_boolean_field_still_works():
    row = {"DIN": "05341082", "FirstName": "OLD", "LastName": "SHAPE",
           "DirectorDisqualified": "true"}
    [director] = normalise_directors({"masterData": {"directorData": [row]}})
    assert director["disqualified"] is True


# ---------------------------------------------------------------------
# D) cessationDate: "" means still serving
# ---------------------------------------------------------------------


def test_empty_cessation_date_means_still_serving():
    """"" is not None. An `is None` test reported every sitting director
    as having resigned."""
    assert is_blank("") is True
    assert is_blank(None) is True
    assert is_blank("2020-01-01") is False

    [director] = normalise_directors({"masterData": {"directorData": [REAL_DIRECTOR_ROW]}})
    assert director["still_serving"] is True
    assert director["ceased_on"] is None


def test_a_resigned_director_is_not_still_serving():
    row = dict(REAL_DIRECTOR_ROW, cessationDate="2022-09-30")
    [director] = normalise_directors({"masterData": {"directorData": [row]}})
    assert director["still_serving"] is False
    assert director["ceased_on"] == "2022-09-30"


# ---------------------------------------------------------------------
# E) Form IDs are spelled with spaces
# ---------------------------------------------------------------------


def test_form_id_spellings_compare_equal():
    assert normalise_form_id("ADT - 1") == normalise_form_id("ADT-1")
    assert normalise_form_id("adt 1") == normalise_form_id("ADT-1")
    assert normalise_form_id("AOC - 4") == normalise_form_id("AOC-4")
    assert normalise_form_id("MGT-7") != normalise_form_id("MGT-7A")
    assert normalise_form_id(None) == ""
