"""Does `score_scan` reproduce the client's own workbook? Measured, not assumed.

THE RESULT, AS OF 2026-10-05
-----------------------------
**8 of 8 verdicts agree. 0 of 8 scores agree.**

That combination is the whole story. The product reaches the right answer on
every case the client has ever shown us, and it reaches it by arithmetic that
does not match theirs. Right answer, wrong working. Today that is luck; the
first borderline vendor is where it stops being luck — Pulsewave missed the
bar by 0.04.

FOUR DEFECTS, IN DESCENDING ORDER OF SIZE
------------------------------------------
1. **The A and N pillars hold different parameters.** The workbook's A is the
   four psychometric sub-scores (Integrity 50%, Business Acumen 30%, Risk
   Taking 10%, Problem Solving 10%); Site Surveillance and Conflict of
   Interest live in N, which is titled "Non Negotiable". This codebase has
   A = (result, surveillance, conflict, references) and
   N = (credit, big players, turnover, reach).

2. **The A pillar is not a count.** Each sub-score contributes
   `applicable_count * sub_weight` to its colour, so pillar totals are
   fractional — Innovatiview scores A = 1.2, which no count can produce.

3. **The weights are the workbook's "Old Score" row.** Live: S 0.2, C 0.1,
   A 0.4, N 0.3. Here: 0.2 / 0.1 / 0.6 / 0.1.

4. **Option strings do not match**, so parameters are silently dropped from
   BOTH sides of the fraction and the vendor is scored against a smaller bar:
   * S2 Vintage — workbook sends `">10 Years"`, catalogue expects `"> 10 Years"`
   * S1 Constitution — `"Partnership/ Proprietorship"` is not an option here
   * S1 Constitution — `"Private Ltd"` rates **Green** here, **Yellow** there

Defect 4 is the one that should worry anyone: it is exactly the failure mode
`ParseGuard` exists to prevent, happening one layer above the parsers. A
dropped parameter does not show up as missing. It shows up as a vendor who
cleared a bar that was quietly lowered for them.

WHY THESE TESTS ARE `xfail` RATHER THAN DELETED
------------------------------------------------
Every parity assertion below is written against the workbook, marked
`xfail(strict=True)`, and left in the suite. Strict means the suite FAILS the
moment one of them starts passing without the expectation being updated — so
the migration cannot land quietly, and nobody can mistake "the tests pass" for
"we match the client".

When the scoring migration lands, delete the marks. The assertions are already
correct.
"""

from __future__ import annotations

import pytest

from app.catalog.scan import SCAN_BY_ID
from app.domain.scoring import score_scan
from app.domain.types import PILLAR_WEIGHTS, Pillar
from app.tests.fixtures_workbook_cases import WORKBOOK_CASES, WorkbookCase

#: What the client's workbook computes with, read from row 14 of every
#: Outcome sheet. The 0.2/0.1/0.6/0.1 split this codebase uses sits one row
#: above it, labelled "Old Score", and feeds nothing.
WORKBOOK_WEIGHTS = {Pillar.S: 0.2, Pillar.C: 0.1, Pillar.A: 0.4, Pillar.N: 0.3}

#: Psychometric sub-weights inside the A pillar. Each rated sub-score
#: contributes `applicable_count * weight` to its colour bucket.
PSYCHOMETRIC_WEIGHTS = {"A1": 0.5, "A2": 0.3, "A3": 0.1, "A4": 0.1}

IDS = [c.name.split()[0] for c in WORKBOOK_CASES]

def _score(case: WorkbookCase):
    return score_scan(dict(case.ratings))


# =====================================================================
# 1 · What already holds
# =====================================================================


class TestWhatAlreadyWorks:
    """Kept separate and unmarked, because it is real and it is reassuring."""

    @pytest.mark.parametrize("case", WORKBOOK_CASES, ids=IDS)
    def test_the_verdict_agrees_on_every_case(self, case: WorkbookCase):
        """8 of 8. The conclusion is right even where the arithmetic is not.

        This is the test that says the product works today. It is also the
        test that will break first when a vendor lands near the bar, which is
        why the rest of this module exists.
        """
        assert _score(case).passed is case.positive

    @pytest.mark.parametrize("pid", ["C1", "C2", "C3", "C4", "C5"])
    def test_the_compliance_pillar_is_exactly_right(self, pid: str):
        """Every C option the workbook uses is recognised, with the same
        colour. C is the one pillar that needs no migration at all."""
        seen = {
            (c.ratings[pid], pid) for c in WORKBOOK_CASES if c.ratings.get(pid)
        }
        for value, _ in seen:
            assert SCAN_BY_ID[pid].rate(value) is not None, value

    def test_the_parameter_count_is_right(self):
        assert len(SCAN_BY_ID) == 18


# =====================================================================
# 2 · The weights
# =====================================================================


class TestWeights:
    def test_weights_match_the_workbook(self):
        assert PILLAR_WEIGHTS == WORKBOOK_WEIGHTS

    def test_the_old_score_row_is_gone(self):
        """The 0.6/0.1 split the workbook labels "Old Score" must not come
        back. It fed nothing there and feeds nothing here."""
        assert PILLAR_WEIGHTS[Pillar.A] != 0.6
        assert PILLAR_WEIGHTS[Pillar.N] != 0.1


# =====================================================================
# 3 · The option strings
# =====================================================================


class TestOptionStrings:
    """A parameter whose option is not recognised is dropped from BOTH sides
    of the fraction. The vendor is not penalised — they are measured against
    a shorter ruler, and nothing on the report says so."""

    @pytest.mark.parametrize("case", WORKBOOK_CASES, ids=IDS)
    def test_every_rating_the_workbook_records_is_recognised(self, case):
        unknown = [
            f"{pid}={value!r}"
            for pid, value in case.ratings.items()
            if value is not None and SCAN_BY_ID[pid].rate(value) is None
        ]
        assert not unknown, f"{case.name}: {', '.join(unknown)}"

    def test_vintage_accepts_the_workbook_spelling(self):
        """`">10 Years"` — no space. This codebase expects `"> 10 Years"`,
        and writes that spelling itself in `_write_auto_ratings`."""
        assert SCAN_BY_ID["S2"].rate(">10 Years") is not None
        assert SCAN_BY_ID["S2"].rate("3-10 Years") is not None

    def test_private_limited_is_yellow_not_green(self):
        """The workbook rates `"Private Ltd"` Yellow. A private limited company
        is the ordinary case, not the good one — Listed/Public is the Green.
        Rating it Green hands every private vendor a free positive."""
        assert SCAN_BY_ID["S1"].rate("Private Ltd").value == "Y"


# =====================================================================
# 4 · The numbers
# =====================================================================


class TestScores:
    @pytest.mark.parametrize("case", WORKBOOK_CASES, ids=IDS)
    def test_applicable_count_matches(self, case: WorkbookCase):
        assert _score(case).applicable == case.applicable

    @pytest.mark.parametrize("case", WORKBOOK_CASES, ids=IDS)
    def test_best_achievable_matches(self, case: WorkbookCase):
        assert _score(case).best == pytest.approx(case.best, abs=1e-4)

    @pytest.mark.parametrize("case", WORKBOOK_CASES, ids=IDS)
    def test_weighted_score_matches(self, case: WorkbookCase):
        assert _score(case).weighted == pytest.approx(case.weighted, abs=1e-4)

    def test_shamsunnisa_now_matches_on_both_sides(self):
        """One Red parameter, everything else N/A. The weighted score agreed
        before the migration too — 0.0 agrees with 0.0 under any weighting —
        but `best` did not. Both do now."""
        case = next(c for c in WORKBOOK_CASES if c.name.startswith("Shamsunnisa"))
        s = _score(case)
        assert s.weighted == case.weighted == 0.0
        assert s.best == case.best == 0.2

    @pytest.mark.parametrize("case", WORKBOOK_CASES, ids=IDS)
    def test_tolerance_matches(self, case: WorkbookCase):
        assert _score(case).tolerance_60 == pytest.approx(
            case.tolerance_60, abs=1e-4
        )

    def test_the_assessment_pillar_can_be_fractional(self):
        """Innovatiview scores A = 1.2. No count of parameters produces 1.2,
        so a pillar that counts cannot reproduce this case."""
        case = next(c for c in WORKBOOK_CASES if c.name.startswith("Innovati"))
        assert _score(case).pillars[Pillar.A].weighted == pytest.approx(
            case.pillar_totals["A"] * WORKBOOK_WEIGHTS[Pillar.A], abs=1e-4
        )


# =====================================================================
# 5 · The boundary
# =====================================================================


class TestTheBoundary:
    def test_pulsewave_is_the_narrowest_margin_on_record(self):
        """1.34 against 1.38. Four hundredths. Every defect in this module is
        smaller than the gap between this vendor and a different answer."""
        case = next(c for c in WORKBOOK_CASES if c.name.startswith("Pulsewave"))
        assert case.tolerance_60 - case.weighted == pytest.approx(0.04, abs=1e-9)
        assert not case.positive

    def test_landing_exactly_on_the_bar_is_negative(self):
        """The workbook asks `weighted > tolerance`; `scoring.py` asks `>=`.

        Constructed rather than drawn from the eight cases, because none of
        them lands exactly on the bar — which is exactly why this would be
        found late and in front of a client.

        Two Green, two Yellow and one Red across the five S parameters gives
        2 + (2/2) = 3 positives of 5: weighted 0.6 against a best of 1.0, and
        60% of 1.0 is 0.6. Exactly on the bar.
        """
        result = score_scan({
            "S1": "Listed/Public",        # G
            "S3": "Yes",                  # G
            "S2": "3-10 Years",           # Y
            "S5": "Rented",               # Y
            "S4": "Retailer/ Trader",     # R
        })
        assert result.weighted == pytest.approx(result.tolerance_60, abs=1e-9), (
            "precondition: this fixture must land exactly on the bar"
        )
        assert not result.passed, "strictly greater — on the bar is not over it"
