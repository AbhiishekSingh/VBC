"""An index stub must never become a paid case-detail lookup.

WHAT HAPPENED. A case search returned twenty rows carrying an
identifier and nothing else — no case type, no parties, no filing date.
Case detail was run against one of them and the provider answered
`404 CASE_NOT_FOUND`.

Two things were wrong with that, and the second is the expensive one:

  * the finding read as "this case does not exist", when the truth was
    "we sent a value that was never a case number";
  * eCourts bills on accepting the request, so the ₹1.50 was spent
    before the 404 came back.

A CNR has a shape — four letters then twelve digits — so neither
mistake needs the provider's help to catch.
"""

from __future__ import annotations

from app.providers.ecourts import CNR_SHAPE, _case_row, _cnr_in


class TestFindingTheCnr:
    def test_the_keyed_value_is_preferred(self):
        assert _cnr_in({"cnr": "DLHC010001232024"}) == "DLHC010001232024"

    def test_it_is_found_by_SHAPE_when_the_key_moves(self):
        """Not a guess at a field NAME — a CNR is recognised by what it
        is. Reading only `cnr` would send None to a paid endpoint the
        day that value moves."""
        assert _cnr_in({"id": "row-9", "caseNo": "DLHC010001232024"}) \
            == "DLHC010001232024"

    def test_case_and_padding_do_not_matter(self):
        assert _cnr_in({"cnr": " dlhc010001232024 "}) == "DLHC010001232024"

    def test_a_short_identifier_is_not_a_cnr(self):
        """Fifteen characters. The kind of near-miss that looks right in
        a table and fails at the endpoint."""
        assert _cnr_in({"cnr": "RPHC6365573206"}) is None

    def test_a_row_with_no_cnr_at_all_returns_none(self):
        assert _cnr_in({"id": 12, "title": "ACME LTD"}) is None

    def test_a_stub_row_parses_with_a_null_cnr(self):
        """Rather than carrying a value that cannot be looked up."""
        assert _case_row({"id": "row-9"})["cnr"] is None


class TestTheShapeItself:
    def test_a_real_cnr_matches(self):
        assert CNR_SHAPE.match("MHAH010012342020")

    def test_the_length_and_court_code_are_the_rule(self):
        """This asserted "four letters then twelve digits" until 13 Nov
        2026, written from the district-court examples in the docs. Two
        of its assertions — a court code shorter or longer than four
        letters — turned out to describe REAL CNRs, so they were deleted
        rather than fixed. See `test_tribunal_cnrs_are_real_cnrs`.
        """
        assert not CNR_SHAPE.match("MHAH01001234202")    # 15
        assert not CNR_SHAPE.match("MHAH0100123420201")  # 17
        assert not CNR_SHAPE.match("MH00010012342020")   # no court code
        assert not CNR_SHAPE.match("MHAH-10012342020")   # punctuated

    def test_tribunal_cnrs_are_real_cnrs(self):
        """CAPTURED FROM PRODUCTION, 13 Nov 2026. Both were returned by
        the live search, and the first resolved at `/case/{cnr}` with a
        full record.

        The old four-letter rule refused both BEFORE the call, reporting
        a valid NCLT or DRT matter as an index stub — worse than the 404
        the guard exists to prevent, because a refusal reads as our
        considered judgement rather than as a gap. Insolvency and
        debt-recovery matters are also exactly the ones a vendor check
        most wants to find.
        """
        assert CNR_SHAPE.match("NCLTCH0001872024")   # six-letter court code
        assert CNR_SHAPE.match("DRTM3OA006572016")   # letters and digits mixed
        assert CNR_SHAPE.match("DRTK2SA001092022")
        assert CNR_SHAPE.match("MPHC020051722014")   # the district shape still

    def test_lowercase_is_not_matched_raw(self):
        """The callers upper-case before matching; the pattern itself
        stays strict so nothing slips through a path segment."""
        assert not CNR_SHAPE.match("mhah010012342020")
