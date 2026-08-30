"""Six defects, all found in ONE real company-master response.

The payload cost ₹5 and is worth far more than that. Everything asserted
here failed before it arrived — and every failure was silent except the two
the parse guards caught.

The company: ZEPTO LIMITED, CIN U46909MH2020PLC351339. Public, active,
incorporated 5 December 2020, with ₹730 crore of live secured charges
across nine lenders.
"""

from __future__ import annotations

import pytest

from app.providers.base import ProviderParseGap, as_int, parse_date
from app.providers.filesure import (
    normalise_charges,
    normalise_directors,
    normalise_master,
)
from app.tests.fixtures_filesure_master import ZEPTO


# =====================================================================
# 1 · Dates are MM/DD/YYYY, not DD/MM/YYYY
# =====================================================================


def test_slashed_dates_are_month_first():
    """The payload settles this itself.

    It carries both forms of the same three dates, and every pair agrees
    only if the first component is the MONTH.
    """
    company = ZEPTO["masterData"]["companyData"]
    common = ZEPTO["masterData"]["commonData"]

    assert parse_date(company["dateOfIncorporation"]) == common["date_of_incorporation"]
    assert parse_date(company["dateOfLastAGM"]) == common["agm_date"]
    assert parse_date(company["balanceSheetDate"]) == common["balance_sheet_date"]


def test_reading_the_incorporation_date_day_first_ages_the_company_wrongly():
    """"12/05/2020" is 5 December 2020, not 12 May 2020.

    Seven months, straight into SCAN S2 (vintage). A valid, plausible,
    silently wrong date is the worst kind — nothing ever flags it.
    """
    assert normalise_master(ZEPTO)["incorporated_on"] == "2020-12-05"


def test_the_order_is_inferred_per_value_not_fixed():
    """The same response is internally inconsistent.

    financialYear "31/03/2024" is day-first; "03/31/2025 00:00:00" is
    month-first. One fixed format cannot serve both.
    """
    assert parse_date("31/03/2024") == "2024-03-31"      # 31 can only be a day
    assert parse_date("03/31/2025 00:00:00") == "2025-03-31"
    assert parse_date("07/28/2022") == "2022-07-28"      # 28 can only be a day


# =====================================================================
# 2 · companyStatus does not exist
# =====================================================================


def test_status_comes_from_common_data():
    """There is NO "companyStatus" key in companyData.

    The status is commonData.status. Reading the documented name returned
    None on a live ACTIVE company, so risk rule r1 (+20) could never fire.
    """
    assert "companyStatus" not in ZEPTO["masterData"]["companyData"]
    assert normalise_master(ZEPTO)["status"] == "Active"


# =====================================================================
# 3 · paidUpCapital — capital U — and it is a string
# =====================================================================


def test_paid_up_capital_is_read_and_is_an_integer():
    """"paidupCapital" does not exist; "paidUpCapital" does, as a STRING."""
    company = ZEPTO["masterData"]["companyData"]
    assert "paidupCapital" not in company
    assert isinstance(company["paidUpCapital"], str)

    result = normalise_master(ZEPTO)
    assert result["paidup_capital"] == 63_015_969_430
    assert isinstance(result["paidup_capital"], int)
    assert result["authorised_capital"] == 207_000_000_000


def test_strings_that_look_like_money_convert():
    assert as_int("500000000") == 500_000_000
    assert as_int("") is None
    assert as_int(None) is None


# =====================================================================
# 4 · THE SERIOUS ONE — open charges read as satisfied
# =====================================================================


def test_an_open_charge_has_an_empty_string_not_null():
    """The premise of the bug, stated as a fact about the payload."""
    rows = ZEPTO["masterData"]["indexChargesData"]
    live = [r for r in rows if r["chargeStatus"] == "Open"]
    assert live, "fixture must contain open charges"
    for row in live:
        assert row["dateOfSatisfaction"] == "", "open charges carry '', not None"
        assert row["dateOfSatisfaction"] is not None


def test_open_charges_are_not_filed_as_satisfied():
    """The regression test for the worst output this system could produce.

    The old code classified on ``dateOfSatisfaction is None``. Since an open
    charge carries "" — which is not None — EVERY open charge was recorded
    as closed. A vendor with ₹260 crore of live secured debt would have
    shown "no open charges" on an audit report.
    """
    result = normalise_charges(ZEPTO)

    assert len(result["open"]) == 3
    assert len(result["closed"]) == 1
    assert result["open_total"] == 2_600_000_000

    holders = {c["holder"] for c in result["open"]}
    assert "HDFC BANK LIMITED" in holders
    assert "IDFC FIRST BANK LIMITED" in holders


def test_charge_status_is_trusted_over_the_date():
    """The payload states it outright; no inference needed."""
    for charge in normalise_charges(ZEPTO)["open"]:
        assert charge["status"] == "Open"
    for charge in normalise_charges(ZEPTO)["closed"]:
        assert charge["status"] == "Closed"


def test_charge_amounts_add_up_rather_than_concatenate():
    """"amount" is a STRING, and there is no "chargeAmount" field at all."""
    rows = ZEPTO["masterData"]["indexChargesData"]
    assert all(isinstance(r["amount"], str) for r in rows)
    assert all("chargeAmount" not in r for r in rows)

    result = normalise_charges(ZEPTO)
    assert isinstance(result["open_total"], int)


def test_a_company_with_no_charges_is_still_clean():
    """The negative case. Absence of charges is a real, common finding."""
    empty = {"masterData": {"indexChargesData": []}}
    result = normalise_charges(empty)
    assert result["open"] == [] and result["open_total"] == 0


# =====================================================================
# 5 · Director flags live inside MCAUserRole
# =====================================================================


def test_cessation_and_disqualification_are_read_from_the_role_entries():
    """Neither field is on the director row.

    The row carries only the older "DirectorDisqualified"; the live
    "isDisqualified" and "cessationDate" are inside MCAUserRole[].
    """
    row = ZEPTO["masterData"]["directorData"][0]
    assert "cessationDate" not in row
    assert "isDisqualified" not in row
    assert row["MCAUserRole"][0]["cessationDate"] == ""
    assert row["MCAUserRole"][0]["isDisqualified"] == "N"

    [manish, aadit] = normalise_directors(ZEPTO)
    assert manish["still_serving"] is True
    assert manish["disqualified"] is False
    assert manish["ceased_on"] is None


def test_a_director_disqualified_on_any_directorship_is_flagged():
    """One bad seat disqualifies the person, not just that seat."""
    import copy

    payload = copy.deepcopy(ZEPTO)
    payload["masterData"]["directorData"][0]["MCAUserRole"][0]["isDisqualified"] = "Y"
    [manish, _] = normalise_directors(payload)
    assert manish["disqualified"] is True


def test_middle_names_are_kept():
    [_, aadit] = normalise_directors(ZEPTO)
    assert aadit["name"] == "AADIT KAVIT PALICHA"


# =====================================================================
# 6 · MCA placeholder rows are not directors
# =====================================================================


def test_placeholder_rows_are_dropped():
    """A real payload carries filler that is not a person.

    Rows with DIN "", names ".", and dateOfAppointment "01/01/1900" are MCA
    padding. One row's "DIN" is actually a PAN. Counting them inflates the
    board — this company reports 6 directors across 15 rows.
    """
    rows = ZEPTO["masterData"]["directorData"]
    assert len(rows) == 4

    directors = normalise_directors(ZEPTO)
    assert len(directors) == 2
    assert all(d["din"].isdigit() and len(d["din"]) == 8 for d in directors)
    assert all(d["name"] != "." for d in directors)


def test_a_payload_of_only_placeholders_is_not_a_parse_failure():
    """No real directors is a finding, not a broken adapter."""
    payload = {"masterData": {"directorData": [
        {"DIN": "", "PAN": "", "FirstName": ".", "MiddleName": ".", "LastName": ".",
         "dateOfAppointment": "01/01/1900", "DirectorDisqualified": "N",
         "MCAUserRole": []},
    ]}}
    assert normalise_directors(payload) == []


# =====================================================================
# The guards must now stay quiet on this payload
# =====================================================================


def test_the_real_payload_no_longer_trips_any_guard():
    """It tripped two on arrival — status, and the charge amount."""
    for normaliser in (normalise_master, normalise_directors, normalise_charges):
        try:
            normaliser(ZEPTO)
        except ProviderParseGap as exc:  # pragma: no cover - failure path
            pytest.fail(f"{normaliser.__name__} still cannot read the live payload: {exc}")


def test_rename_history_survives():
    """ZEPTO was KIRANAKART TECHNOLOGIES. A rename is a finding in itself."""
    result = normalise_master(ZEPTO)
    assert result["name_history"]
    assert result["cin_history"]
