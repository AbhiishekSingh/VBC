"""Case detail is split across more than one block, and we read one.

CAPTURED 13 Nov 2026, CNR NCLTCH0001872024, production key. The fixture
below is trimmed from that response; every key placement in it is where
the provider actually put it.

WHAT WENT WRONG. `case_detail` read `data.courtCaseData` and nothing
else. Roughly half the record is not in there:

    disposalType · disposalTypeRaw · caseNumber · courtName · district
    orderCount · hearingCount · judgmentCount · caseDurationDays
    caseCategoryFacetPath · iaCount

All of them returned None. Nothing noticed, because the ParseGuard
checked two things — `courtCaseData` existing, and `caseStatus` — and
both of those ARE in the block we read. A guard that only inspects the
half you already trust cannot tell you about the half you do not.

THE EXPENSIVE FIELD is `disposalType`. The comment beside it in
`ecourts.py` says why: "DISMISSED_AS_WITHDRAWN" and a conviction are
both DISPOSED, and only one of them is good news for a vendor. So the
screen said "DISPOSED" and stopped — which is not an answer to the
question a due-diligence report is asked.

ONE SAMPLE IS ONE SAMPLE. The captured response is an NCLT matter,
which is why its second block is named `tribunalCaseData`. A district or
High Court case may name it differently, or carry none. Hard-coding two
block names from a single capture is precisely how the `parties`
whitelist came to exist, so the merge is driven by a list plus a shape
test, and the tests below pin that behaviour rather than the two names.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers import ecourts as ec
from app.providers.base import ProviderParseGap

CNR = "NCLTCH0001872024"

#: The first block. Note what it does NOT contain.
COURT_CASE_DATA = {
    "cnr": CNR,
    "cnrCourtCode": "NCLTCH0",
    "caseType": "IA_IBC",
    "caseStatus": "DISPOSED",
    "filingNumber": "3305118001872024",
    "filingDate": "2024-01-11",
    "registrationNumber": "IA(I.B.C)/304/CHE/2024",
    "registrationDate": "2024-01-25",
    "decisionDate": "2024-02-08",
    "petitioners": ["CENTRAL BANK OF INDIA AND STATE BANK OF INDIA"],
    "respondents": ["CENTRAL BANK OF INDIA AND STATE BANK OF INDIA"],
    "state": "N/A",
    "firDetails": {},
    "interimOrders": [],
    "judgmentOrders": [],
}

#: The second block, holding everything the first one lacks.
TRIBUNAL_CASE_DATA = {
    "cnr": CNR,
    "caseNumber": "IA(I.B.C)/304/CHE/2024",
    "courtName": "NCLT Chennai",
    "district": "Chennai",
    "disposalType": "ALLOWED",
    "disposalTypeRaw": "Allowed",
    "caseTypeRaw": "Interlocutory Application (I.B.C)",
    "caseDurationDays": 28,
    "caseCategoryFacetPath": "Miscellaneous/Applications",
    "orderCount": 0,
    "judgmentCount": 0,
    "hearingCount": 0,
    "iaCount": 33,
    "caseStatus": "DISPOSED",
    "interlocutoryApplications": [
        {"particular": "Company Appeal (IBC)", "status": "Pending"},
        {"particular": "IA (Liq.) Progress Report", "status": "Disposed"},
    ],
}


def _payload(**over) -> dict:
    data = {
        "courtCaseData": dict(COURT_CASE_DATA),
        "tribunalCaseData": dict(TRIBUNAL_CASE_DATA),
        "entityInfo": {"cnr": CNR, "dateModified": "2026-07-03T04:25:23Z"},
        "files": {"files": []},
        "descriptions": {"enumLookup": {
            "caseType": {"IA_IBC": "Interlocutory Application (IBC)"},
            "courtCode": {"NCLTCH0": "NCLT - National Company Law Tribunal, "
                                     "Chennai, Tamil Nadu"},
        }},
    }
    data.update(over)
    return {"data": data}


def _provider(payload) -> ec.EcourtsProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    return ec.EcourtsProvider(
        Settings(ecourts_api_key="eci_live_test", allow_paid_calls=True),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _detail(payload=None):
    return _provider(payload or _payload()).case_detail(CNR)


class TestTheSecondBlockIsRead:
    def test_the_disposal_type_arrives(self):
        """THE ONE THAT MATTERS. Without it the finding reads "DISPOSED"
        and stops, which does not distinguish a withdrawal from a
        conviction."""
        out = _detail()
        assert out["disposal_type"] == "ALLOWED"
        assert out["disposal_type_raw"] == "Allowed"

    @pytest.mark.parametrize("field,expected", [
        ("case_number", "IA(I.B.C)/304/CHE/2024"),
        ("court_name", "NCLT Chennai"),
        ("district", "Chennai"),
        ("case_duration_days", 28),
        ("order_count", 0),
        ("hearing_count", 0),
        ("judgment_count", 0),
        ("case_category", "Miscellaneous/Applications"),
    ])
    def test_every_field_that_was_silently_none(self, field, expected):
        assert _detail()[field] == expected

    def test_the_ia_count_is_surfaced(self):
        """33 interlocutory applications on one matter is the difference
        between a dormant file and a live, heavily contested dispute. It
        was never on screen."""
        out = _detail()
        assert out["ia_count"] == 33
        assert len(out["interlocutory_applications"]) == 2

    def test_the_first_block_still_wins(self):
        """The merge may ADD fields; it must never silently change one.
        A later block overwrites only a blank."""
        payload = _payload()
        payload["data"]["tribunalCaseData"]["caseStatus"] = "PENDING"
        assert _detail(payload)["case_status"] == "DISPOSED"

    def test_a_blank_in_the_first_block_is_filled_from_the_second(self):
        payload = _payload()
        payload["data"]["courtCaseData"]["courtName"] = ""
        assert _detail(payload)["court_name"] == "NCLT Chennai"


class TestItDoesNotDependOnTwoKnownNames:
    """One sample is one sample. A District or High Court response may
    name its second block something else, and the merge must not quietly
    go back to reading half a record when it does."""

    def test_an_unknown_block_carrying_a_cnr_is_merged(self):
        payload = _payload()
        payload["data"].pop("tribunalCaseData")
        payload["data"]["someFutureCaseBlock"] = dict(TRIBUNAL_CASE_DATA)
        assert _detail(payload)["disposal_type"] == "ALLOWED"

    def test_a_block_with_no_cnr_is_left_alone(self):
        """`entityInfo`, `files` and `descriptions` are about the
        RESPONSE, not the matter. A same-named key in one of them must
        not leak into the case."""
        payload = _payload()
        payload["data"]["descriptions"]["courtName"] = "NOT A COURT"
        assert _detail(payload)["court_name"] == "NCLT Chennai"

    def test_one_block_alone_still_parses(self):
        """A response with no second block must degrade to the old
        behaviour, not crash."""
        payload = _payload()
        payload["data"].pop("tribunalCaseData")
        payload["data"]["courtCaseData"]["disposalType"] = "DISMISSED"
        out = _detail(payload)
        assert out["disposal_type"] == "DISMISSED"
        assert out["cnr"] == CNR


class TestDisposedWithoutATypeIsNotAnAnswer:
    def test_it_raises_rather_than_reporting_half_a_finding(self):
        """The failure mode this whole file documents: a confident
        "DISPOSED" with the fact that qualifies it missing. Better to
        report the adapter as unable to read the response than to print
        a disposal whose nature we silently dropped."""
        payload = _payload()
        payload["data"]["tribunalCaseData"].pop("disposalType")
        payload["data"]["tribunalCaseData"].pop("disposalTypeRaw")
        with pytest.raises(ProviderParseGap, match="disposal type"):
            _detail(payload)

    def test_a_pending_case_needs_no_disposal_type(self):
        """Nothing has been disposed of, so nothing is missing."""
        payload = _payload()
        payload["data"]["courtCaseData"]["caseStatus"] = "PENDING"
        for key in ("disposalType", "disposalTypeRaw"):
            payload["data"]["tribunalCaseData"].pop(key)
        payload["data"]["tribunalCaseData"]["caseStatus"] = "PENDING"
        out = _detail(payload)
        assert out["is_pending"] is True
        assert out["disposal_type"] is None

    def test_the_raw_spelling_alone_is_enough(self):
        payload = _payload()
        payload["data"]["tribunalCaseData"].pop("disposalType")
        assert _detail(payload)["disposal_type_raw"] == "Allowed"


class TestTheEvidenceTierStaysUnmerged:
    def test_court_case_data_is_what_the_provider_sent(self):
        """The evidence tier must remain the provider's bytes. Merging is
        OUR reading of them, and an analyst checking our working has to
        be able to tell the two apart."""
        out = _detail()
        assert "disposalType" not in out["court_case_data"]
        assert out["court_case_data"] == COURT_CASE_DATA

    def test_the_merged_view_is_available_separately(self):
        out = _detail()
        assert out["case_merged"]["disposalType"] == "ALLOWED"
