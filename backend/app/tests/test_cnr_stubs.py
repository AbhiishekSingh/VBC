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

    def test_four_letters_then_twelve_digits_is_the_rule(self):
        assert not CNR_SHAPE.match("MHAH01001234202")    # 15
        assert not CNR_SHAPE.match("MHAH0100123420201")  # 17
        assert not CNR_SHAPE.match("MHA0010012342020")   # 3 letters
        assert not CNR_SHAPE.match("MHAHA10012342020")   # 5 letters

    def test_lowercase_is_not_matched_raw(self):
        """The callers upper-case before matching; the pattern itself
        stays strict so nothing slips through a path segment."""
        assert not CNR_SHAPE.match("mhah010012342020")
