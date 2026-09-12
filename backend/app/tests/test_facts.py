"""The facts layer — shape, formatting, flags, and what must never be in it.

These run against the same captured payload the adapter tests use, so a
change that breaks the parser breaks both. Nothing here talks to a provider.

The tests fall into three groups, and the third is the one that matters most:

1. The envelope is the shape the frontend contract declares.
2. Values are formatted once, in Python, so the two languages cannot drift.
3. A fact blob never carries a PAN, an unmasked contact, or a base64 blob —
   it is the tier a client-facing screen reads.
"""

from __future__ import annotations

import base64
import re
from datetime import date, timedelta

import pytest

from app.domain import facts as F
from app.providers import factsets as fx
from app.providers.filesure import (
    normalise_charges,
    normalise_directors,
    normalise_master,
)
from app.tests.fixtures_filesure_master import ZEPTO

VALID_SHAPES = {"detail", "summary", "table", "document", "reference", "none"}


def _all_strings(blob) -> list[str]:
    """Every string anywhere in a fact blob."""
    found: list[str] = []
    stack = [blob]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return found


# =====================================================================
# 1 · The envelope
# =====================================================================

class TestEnvelope:
    def test_every_blob_declares_a_shape_and_a_parser_version(self):
        blobs = [
            fx.master(normalise_master(ZEPTO)),
            fx.directors(normalise_directors(ZEPTO)),
            fx.charges(normalise_charges(ZEPTO)),
            fx.ssl({"present": True, "valid_to": "2030-01-01"}),
            fx.gst({"gstin": "27AAACR4849R1ZL", "status": "Active"}),
            fx.case_search({"count": 0, "results": [], "query": ["x"]}),
        ]
        for blob in blobs:
            assert blob["shape"] in VALID_SHAPES
            assert blob["parserVersion"] == F.PARSER_VERSION

    def test_empty_sections_are_omitted_not_sent_as_empty_lists(self):
        """A renderer checks for presence. ``[]`` would render an empty
        heading, which reads as "we looked and found nothing" on a section
        that was never populated at all."""
        blob = F.build(F.DETAIL, fields=[F.field("A", "b")])
        assert "stats" not in blob
        assert "table" not in blob
        assert "flags" not in blob

    def test_a_missing_value_is_kept_as_null_not_dropped(self):
        """A field that disappears when the provider omits it makes a partial
        response look complete."""
        blob = fx.master({"cin": "X", "status": None})
        labels = {f["label"]: f["value"] for f in blob["fields"]}
        assert "Status" in labels
        assert labels["Status"] is None

    def test_table_reports_the_provider_total_not_the_page_size(self):
        rows = [{"formId": f"F{i}"} for i in range(50)]
        blob = fx.filings(rows, {"total": 3209, "limit": 50})
        assert blob["table"]["totalRows"] == 3209
        assert len(blob["table"]["rows"]) == 50
        assert blob["table"]["truncated"] is True

    def test_an_empty_table_explains_what_empty_means_here(self):
        """"No rows" is not a finding. "No charges registered" is."""
        blob = fx.charges({"open": [], "closed": [], "open_total": 0, "closed_total": 0})
        assert blob["table"]["emptyNote"]
        assert "charges" in blob["table"]["emptyNote"].lower()

    def test_reference_checks_are_marked_as_reference(self):
        """Ten of the 47 checks describe the API, not the vendor. They must
        not render among the findings."""
        blob = fx.catalog("Court filters", ["caseType", "parties"])
        assert blob["shape"] == F.REFERENCE


# =====================================================================
# 2 · Formatting happens once, in Python
# =====================================================================

class TestFormatting:
    @pytest.mark.parametrize("rupees,expected", [
        (76934000, "₹7.69 Cr"),
        (500000, "₹5.00 L"),
        (1234, "₹1,234"),
        (None, None),
    ])
    def test_indian_money_scales(self, rupees, expected):
        assert F.crore(rupees) == expected

    def test_paisa_and_crore_are_different_functions_on_purpose(self):
        """Confusing the two is a factor-of-100 error in a money figure on a
        report, so they are named so that it cannot happen silently."""
        assert F.paisa(123456) == "₹1,234.56"
        assert F.crore(123456) == "₹1.23 L"

    @pytest.mark.parametrize("value,expected", [
        ("2015-02-02", "02 Feb 2015"),
        ("2015-02-02T11:30:00Z", "02 Feb 2015"),
        (None, None),
        ("not a date", "not a date"),
    ])
    def test_dates_become_readable_and_junk_passes_through(self, value, expected):
        assert F.human_date(value) == expected

    def test_yes_no_keeps_three_states(self):
        """"The provider said nothing" is a different fact from "no", and
        collapsing them is how an unexamined field starts reading clean."""
        assert F.yes_no(True) == "Yes"
        assert F.yes_no(False) == "No"
        assert F.yes_no(None) is None

    def test_master_dates_reach_the_blob_already_formatted(self):
        """WHAT the date is belongs to the adapter's own tests. This asserts
        only that no ISO string reaches a screen — five providers send five
        formats and a report must not show any of them."""
        blob = fx.master(normalise_master(ZEPTO))
        incorporated = next(f for f in blob["fields"] if f["label"] == "Incorporated")
        assert re.fullmatch(r"\d{2} [A-Z][a-z]{2} \d{4}", incorporated["value"])
        assert incorporated["format"] == "date"


# =====================================================================
# 3 · Flags — problems with the RESPONSE, not the vendor
# =====================================================================

class TestFlags:
    def test_a_different_company_is_flagged(self):
        """The failure this catches: a GSTIN one character wrong resolves
        cleanly and returns a real, active registration — belonging to
        somebody else. Status PASS, detail line clean, wrong company."""
        blob = fx.gst(
            {"gstin": "27AAACR4849R1ZL", "status": "Active", "is_active": True,
             "legal_name": "TATA CONSULTANCY SERVICES LIMITED"},
            subject="Reliance Industries Limited",
        )
        assert any(f["level"] == "bad" for f in blob["flags"])
        assert "TATA" in blob["flags"][0]["detail"]

    def test_the_same_company_spelled_differently_is_not_flagged(self):
        """A flag on every second vendor would be switched off within a week."""
        blob = fx.gst(
            {"gstin": "X", "status": "Active", "legal_name": "RELIANCE INDUSTRIES LTD"},
            subject="Reliance Industries Limited",
        )
        assert not blob.get("flags")

    def test_an_expired_certificate_is_flagged(self):
        blob = fx.ssl({"present": True, "trusted_ca": True,
                       "valid_to": "2024-09-13", "common_name": "corp.ril.com"})
        assert any("expired" in f["label"].lower() for f in blob["flags"])

    def test_a_certificate_for_another_host_is_flagged(self):
        blob = fx.ssl(
            {"present": True, "trusted_ca": True, "common_name": "corp.ril.com",
             "valid_to": (date.today() + timedelta(days=365)).isoformat()},
            domain="ril.com",
        )
        assert any("different host" in f["label"] for f in blob["flags"])

    def test_a_healthy_certificate_raises_nothing(self):
        blob = fx.ssl(
            {"present": True, "trusted_ca": True, "common_name": "ril.com",
             "valid_to": (date.today() + timedelta(days=200)).isoformat()},
            domain="ril.com",
        )
        assert not blob.get("flags")

    def test_results_carrying_only_a_cnr_are_called_what_they_are(self):
        """Twenty index stubs currently read as twenty cases found. That is
        the single most misleading thing this product could show."""
        stubs = [{"cnr": f"MH00{i}", "case_type": "UNKNOWN",
                  "petitioners": [], "respondents": [], "filing_date": None}
                 for i in range(20)]
        blob = fx.case_search({"count": 20, "results": stubs, "query": []})
        assert any("empty records" in f["label"] for f in blob["flags"])
        stat = {s["label"]: s["value"] for s in blob["stats"]}
        assert stat["Index stubs"] == "20"
        assert stat["Complete records"] == "0"

    def test_a_misspelled_search_term_is_flagged_as_a_likely_typo(self):
        """An exact-match registry returns nothing for a misspelled party,
        and nothing must never reach a report as no litigation."""
        blob = fx.case_search(
            {"count": 0, "results": [], "query": ["Relaince Industries Limited"]},
            subject="Reliance Industries Limited",
        )
        assert any("misspelling" in f["label"] for f in blob["flags"])

    def test_an_exact_search_term_is_not_flagged(self):
        blob = fx.case_search(
            {"count": 0, "results": [], "query": ["Reliance Industries Limited"]},
            subject="Reliance Industries Limited",
        )
        assert not blob.get("flags")

    def test_a_stale_archive_is_blamed_on_the_archive(self):
        blob = fx.timeline({"captures": 4, "ok_captures": 4, "redirects": 0,
                            "continuous": True, "last_capture": "2005-06-01"})
        flag = next(f for f in blob["flags"] if "stale" in f["label"].lower())
        assert "about the archive" in flag["detail"]

    def test_a_profile_that_contradicts_itself_is_surfaced_not_resolved(self):
        """Top-level ``disqualified: true`` with no row carrying the flag.
        The source disagrees with itself; a parser does not get to pick."""
        blob = fx.director_profiles([{
            "name": "NITA AMBANI", "disqualified": True,
            "companyData": [{"nameOfTheCompany": "X", "isDisqualified": "N"}],
        }])
        assert any("Contradictory" in f["label"] for f in blob["flags"])

    def test_fuzzy_archive_matches_are_labelled_as_candidates(self):
        blob = fx.mentions({"found": 3, "q": "RELIANCE",
                            "note": "Matching is approximate.",
                            "docs": [{"title": "Unrelated video"}]})
        assert any("approximate" in f["label"].lower() for f in blob["flags"])

    def test_nothing_compared_is_not_a_clean_result(self):
        blob = fx.inhouse({"matches": [], "compared_against": 0}, kind="conflict")
        assert any("Nothing was compared" in f["label"] for f in blob["flags"])

    def test_a_flag_never_implies_a_status(self):
        """Flags are advisory by construction: the envelope has no field a
        parser could use to change an outcome."""
        blob = fx.ssl({"present": True, "valid_to": "2024-01-01"})
        assert "status" not in blob
        for flag in blob["flags"]:
            assert set(flag) == {"level", "label", "detail"}


# =====================================================================
# 4 · What must never be in a fact blob
# =====================================================================

class TestSafeToRender:
    def test_no_pan_reaches_the_facts(self):
        """PAN is in the normalised director rows and stays in raw_response,
        behind its own grants. This blob is what a client-facing screen
        reads."""
        rows = normalise_directors(ZEPTO)
        for row in rows:
            row["pan"] = "ABCDE1234F"
        blob = fx.directors(rows)
        assert "ABCDE1234F" not in " ".join(_all_strings(blob))

    def test_no_base64_blob_reaches_the_facts(self):
        """An order PDF is ~50 KB of base64. It is stored and linked, never
        inlined into a response the browser has to hold."""
        pdf = base64.b64encode(b"%PDF-1.4 fake" * 400).decode()
        blob = fx.orders("MH0001", [{"filename": "order.pdf", "pdf_base64": pdf,
                                     "markdown": "In the matter of..."}])
        text = " ".join(_all_strings(blob))
        assert pdf not in text
        assert blob["documents"][0]["sizeBytes"] > 0

    def test_long_text_is_excerpted_not_carried_whole(self):
        blob = fx.orders("MH0001", [{"filename": "o.pdf", "markdown": "x" * 10_000}])
        assert len(blob["documents"][0]["excerpt"]) <= 400

    def test_case_detail_never_emits_the_duplicated_camelcase_block(self):
        """The payload carries every field twice — flattened, and again
        inside ``court_case_data``. The screen must see one set."""
        blob = fx.case_detail({
            "cnr": "MH0001", "case_type": "CIVIL", "filing_date": "2020-01-01",
            "court_case_data": {"caseType": "SHOULD-NOT-APPEAR",
                                "filingDate": "SHOULD-NOT-APPEAR"},
        })
        assert "SHOULD-NOT-APPEAR" not in " ".join(_all_strings(blob))


# =====================================================================
# 5 · Re-parse is the whole point
# =====================================================================

class TestApiBoundary:
    """Facts have to SURVIVE the trip to the frontend.

    This is the original defect, and it is easy to recreate: the parser runs,
    the blob is written to `vendor_checks.facts`, and then the response
    schema quietly drops it because nobody added the field. Everything looks
    correct from the database side and the screen shows exactly what it
    showed before.
    """

    def test_the_response_schema_carries_facts(self):
        from app.api import schemas as s
        assert "facts" in s.CheckResultOut.model_fields

    def test_a_facts_blob_survives_serialisation(self):
        from app.api import schemas as s
        blob = fx.master(normalise_master(ZEPTO))
        out = s.CheckResultOut(
            checkId="master", status="pass", facts=blob, rawResponse={"a": 1},
        )
        assert out.model_dump()["facts"] == blob

    def test_the_serialiser_actually_passes_it(self):
        """The schema having the field is not enough — `_serialise` has to
        populate it. It defaults to None, so forgetting is silent."""
        import inspect as _inspect
        from app.api import routes

        source = _inspect.getsource(routes._serialise)
        assert "facts=row.facts" in source, (
            "_serialise builds CheckResultOut without facts; the parser's "
            "output would be written to the database and never sent"
        )

    def test_a_row_with_no_facts_still_serialises(self):
        """Old rows, unavailable checks, and every check whose parser is not
        written yet. The screen must fall back, not error."""
        from app.api import schemas as s
        out = s.CheckResultOut(checkId="pan", status="not_configured", facts=None)
        assert out.model_dump()["facts"] is None


class TestReparse:
    def test_facts_are_a_pure_function_of_the_payload(self):
        """Fixing a parse defect means re-running this over stored payloads
        instead of re-paying the provider. That only works if it is
        deterministic and needs nothing but the payload."""
        parsed = normalise_master(ZEPTO)
        assert fx.master(parsed) == fx.master(parsed)

    def test_a_parser_version_travels_with_every_blob(self):
        """So a defective vintage can be found and rebuilt."""
        assert fx.master(normalise_master(ZEPTO))["parserVersion"] == F.PARSER_VERSION
