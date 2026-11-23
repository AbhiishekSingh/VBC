"""A field the source did not send is not an adapter defect.

WHAT THIS FILE IS FOR
---------------------
On 18 Nov 2026 a ZEPTO board of 11 directors was discarded and the screen
said "Response not understood", because `normalise_directors` demanded a
disqualification field that MCA's company master does not carry at all.
The guard could not tell these two apart:

    the field was RENAMED      → adapter defect; void the check
    the source did not SEND it → a fact about the subject; report it

and it answered "defect" to both.

A sweep of every ParseGuard on 23 Nov found the same mistake in five more
places. They are listed below with what each one destroyed. Four of the
six were on the most material fact their check produces, and two of them
hid an ADVERSE finding behind what reads as our own bug — which is worse
than hiding a clean one, because nobody chases a result that looks broken
at our end.

    filesure.master  class_of_company   an LLP or FCIN has no class of
                                        company. Voided the MASTER, and
                                        `dirs`, `charges`, `filings` and
                                        `fin` are all read out of it and
                                        all SKIP when it is unavailable.
    filesure.charges amount             a charge registered without a
                                        disclosed amount voided the whole
                                        check, open charges and all.
    finagg.returns   filed returns      a GSTIN that had filed NOTHING —
                                        the most adverse fact this
                                        endpoint reports.
    gridlines.epfo   UAN                a person with no EPFO record.
    gridlines.employ employment history a UAN no employer has reported.
    runner `fin`     (not a guard)      "No financials filed" carried no
                                        payload, so r3 fell back to the
                                        STATUS and awarded +15 for
                                        "positive net worth" to a company
                                        that had filed none. Covered in
                                        `test_no_filing_does_not_score`.

THE RULE THESE TESTS HOLD
-------------------------
A ParseGuard may only fire on evidence that the fact IS in the payload —
the container arriving, or a key that NAMES the fact under a spelling we
do not read. "Our parsed value came out empty" is not that evidence.

Each case below is asserted in BOTH directions. A guard that stops
firing on a real rename is not a fix, it is the opposite bug, and the
dangerous direction is the one that fails silently.
"""

from __future__ import annotations

import pytest

from app.providers.base import ProviderParseGap, unread_keys_matching
from app.providers.filesure import normalise_charges, normalise_master


# =====================================================================
# The helper the fixes are built on
# =====================================================================

class TestTheVocabularyTest:
    """`unread_keys_matching` is the evidence the guards now use."""

    def test_a_key_we_read_is_not_a_rename(self):
        """`isDisqualified` contains "disqualif" too. A test that did not
        exclude the names we read would fire on every payload."""
        payload = {"MCAUserRole": [{"isDisqualified": "N"}]}
        assert unread_keys_matching(payload, "disqualif", ("isdisqualified",)) == []

    def test_a_key_we_do_not_read_is_found_and_named(self):
        payload = {"rows": [{"disqualificationStatus": "Y"}]}
        assert unread_keys_matching(payload, "disqualif", ("isdisqualified",)) \
            == ["disqualificationStatus"]

    def test_it_searches_at_any_depth(self):
        """A renamed field two objects down is still a renamed field."""
        payload = {"a": {"b": [{"c": {"chargeAmountInRupees": "500"}}]}}
        assert unread_keys_matching(payload, "amount", ("amount",)) \
            == ["chargeAmountInRupees"]

    def test_matching_ignores_case(self):
        assert unread_keys_matching({"ClassOfEntity": "LLP"}, "class", ()) \
            == ["ClassOfEntity"]

    def test_a_payload_that_never_mentions_it_yields_nothing(self):
        """THE WHOLE POINT. Silence is not drift."""
        payload = {"cin": "U1", "company": "ACME", "status": "Active"}
        assert unread_keys_matching(payload, "disqualif", ()) == []

    def test_a_list_at_the_root_is_walked(self):
        assert unread_keys_matching([{"amountPaid": 1}], "amount", ()) \
            == ["amountPaid"]

    def test_it_survives_scalars_and_none(self):
        for payload in (None, 3, "text", [], {}):
            assert unread_keys_matching(payload, "amount", ()) == []


# =====================================================================
# filesure.master — the worst of the six, because it gates four checks
# =====================================================================

def _master(common: dict) -> dict:
    return {"masterData": {"commonData": {
        "cin": "U46909MH2020PLC351339", "company": "ACME",
        "status": "Active", "date_of_incorporation": "2015-02-02",
        **common}}}


class TestTheCompanyMasterSurvivesAMissingClass:
    def test_an_entity_with_no_class_of_company_still_parses(self):
        """THE REGRESSION. `classOfCompany` is a Companies Act field and
        this check accepts an LLPIN and an FCIN as readily as a CIN."""
        result = normalise_master(_master({}))
        assert result["status"] == "Active"
        assert result["class_of_company"] in (None, "")

    def test_the_blast_radius_is_why_this_one_matters(self):
        """`dirs`, `charges`, `filings` and `fin` are read out of this
        payload. A gap here empties the whole MCA section of the report,
        and the reason given would be a descriptive field nobody scores."""
        payload = _master({})
        payload["masterData"]["directorData"] = [
            {"DIN": "08057013", "FirstName": "A", "LastName": "B",
             "MCAUserRole": [{"designation": "Director", "cessationDate": ""}]}
        ]
        assert normalise_master(payload)["status"] == "Active"

    def test_a_renamed_class_field_is_still_a_gap(self):
        with pytest.raises(ProviderParseGap, match="class_of_company"):
            normalise_master(_master({"entityClassification": "Private"}))

    def test_the_gap_names_what_it_found(self):
        with pytest.raises(ProviderParseGap) as excinfo:
            normalise_master(_master({"companyClassDescription": "Private"}))
        assert "companyClassDescription" in str(excinfo.value)

    def test_a_class_that_is_present_still_parses(self):
        assert normalise_master(_master({"class_of_company": "Private"})) \
            ["class_of_company"] == "Private"

    def test_an_absent_status_is_still_a_gap(self):
        """The narrowing is per-field. `status` is the headline fact and
        feeds r1; it stays guarded."""
        payload = _master({})
        del payload["masterData"]["commonData"]["status"]
        with pytest.raises(ProviderParseGap, match="status"):
            normalise_master(payload)


# =====================================================================
# filesure.charges
# =====================================================================

def _charges(*rows: dict) -> dict:
    return {"masterData": {"indexChargesData": list(rows)}}


OPEN_CHARGE = {"chargeId": "100123456", "chargeHolderName": "HDFC BANK",
               "dateOfCreation": "01/01/2020", "dateOfSatisfaction": None}


class TestAChargeWithNoAmountIsStillACharge:
    def test_it_parses_rather_than_voiding_the_check(self):
        """THE REGRESSION. An open charge is the most material fact on
        this payload; discarding it because a figure was absent is the
        worst trade available."""
        result = normalise_charges(_charges(OPEN_CHARGE))
        assert len(result["open"]) == 1
        assert result["open"][0]["holder"] == "HDFC BANK"

    def test_the_absent_amount_is_none_not_zero(self):
        """Zero would be a figure. None is the absence of one, and
        `open_total` must not report ₹0 as the secured sum."""
        result = normalise_charges(_charges(OPEN_CHARGE))
        assert result["open"][0]["amount"] is None

    def test_a_renamed_amount_is_still_a_gap(self):
        row = dict(OPEN_CHARGE, chargeAmountInRupees="50000000")
        with pytest.raises(ProviderParseGap, match="amount"):
            normalise_charges(_charges(row))

    def test_the_second_spelling_this_adapter_reads_is_not_a_rename(self):
        """`chargeAmount` is a fallback the parser already handles."""
        row = dict(OPEN_CHARGE, chargeAmount="50000000")
        result = normalise_charges(_charges(row))
        assert result["open"][0]["amount"] == 50000000

    def test_no_charges_at_all_is_still_clean(self):
        assert normalise_charges(_charges())["open"] == []


# =====================================================================
# gridlines — the two person checks
# =====================================================================
#
# These are the same mistake on a living person rather than a company,
# and the consequence is the one most likely to be misread: a subject
# who is simply not in EPFO came back as "Response not understood",
# which an analyst reads as "try again later" rather than as an answer.

from app.tests.test_gridlines import _Recorder  # noqa: E402


def _envelope(inner: dict) -> dict:
    return {"data": {"code": "1", "message": "ok", **inner}}


class TestAPersonWithNoEpfoRecord:
    def test_a_response_with_a_name_but_no_UAN_still_parses(self):
        """THE REGRESSION. The guard demanded `uan` specifically, so a
        subject EPFO does not hold — which is most of the population —
        voided the check instead of answering it."""
        out = _Recorder(_envelope({"member_name": "A B", "uan_status": "NA"})) \
            .epfo_member("9820000000", consent="Y")
        assert out["uan"] is None
        assert out["name"] == "A B"

    def test_a_response_that_parses_nothing_is_still_a_gap(self):
        """The dangerous direction. An envelope with nothing in it but
        its own `code` and `message` is not an answer about anybody."""
        with pytest.raises(ProviderParseGap):
            _Recorder(_envelope({"someUnknownBlock": {"x": 1}})) \
                .epfo_member("9820000000", consent="Y")

    def test_a_UAN_that_is_present_is_still_read(self):
        out = _Recorder(_envelope({"uan": "101749428566"})) \
            .epfo_member("9820000000", consent="Y")
        assert out["uan"] == "101749428566"


class TestAUanWithNoEmploymentOnRecord:
    @pytest.mark.parametrize(
        "key", ["employment_history", "employments", "records",
                "employment_details"])
    def test_an_empty_list_is_an_answer_not_a_defect(self, key):
        """THE REGRESSION. A new registration, or a person no employer has
        yet reported. The LIST arriving is what proves the adapter
        understands the envelope — `rows` alone cannot say which happened.

        Parametrised over the key names because the bug hid behind one of
        them: `descend` collapses an envelope whose only block is
        `employment_data` down to the bare list, so `has_content(inner)`
        was already False there and the guard never fired. Testing that
        spelling alone would have proved nothing, and did, the first time
        this test was written.
        """
        out = _Recorder(_envelope({key: []})) \
            .employment_history("101749428566", consent="Y")
        assert out["employments"] == []

    def test_content_under_the_key_in_a_shape_we_cannot_read_still_gaps(self):
        """The dangerous direction, and the reason `_employment_container`
        requires a LIST: a dict there would be read as "no employment"."""
        with pytest.raises(ProviderParseGap):
            _Recorder(_envelope({"employment_data": {"somethingElse": {"x": 1}}})) \
                .employment_history("101749428566", consent="Y")

    def test_the_echoed_uan_is_not_mistaken_for_parsed_evidence(self):
        """`parsed["uan"]` falls back to the ARGUMENT, so it is truthy on
        every response including an empty one. A guard reading it could
        never fire again — the trap `_without_status` was written to
        escape, re-entered through a different door."""
        with pytest.raises(ProviderParseGap):
            _Recorder(_envelope({"unknownBlock": {"x": 1}})) \
                .employment_history("101749428566", consent="Y")

    def test_real_rows_are_still_read(self):
        out = _Recorder(_envelope({"employment_data": [
            {"establishment_name": "ACME", "date_of_joining": "2015-01-01"}]})) \
            .employment_history("101749428566", consent="Y")
        assert len(out["employments"]) == 1
