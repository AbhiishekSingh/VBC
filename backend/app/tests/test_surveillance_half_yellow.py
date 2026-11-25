"""An odd Yellow on a site visit is worth half a Green, not nothing.

WHAT WAS WRONG, AND FOR HOW LONG
--------------------------------
`score_surveillance` computed

    positives = G + Y // 2

The client's sheet does not floor. `Site Surveillance!H36`, read out of
three workbooks they sent on 25 Nov 2026:

    =IF(I8="red","Negative",
        IF( (M9 + (M10/2)) >= (0.6*M12), "Positive", "Negative"))

M9 Green · M10 Yellow · M12 applicable · I8 the premises gate. `M10/2`,
with no rounding, exactly as the SCAN sheet computes `=D8+(D9/2)`.

THE SAME DEFECT WAS FIXED IN SCAN ON 5 OCT 2026 and this copy was missed.
`test_scoring.py::test_an_odd_yellow_is_worth_half_a_green` pins the SCAN
side; nothing pinned this one, in either direction, so changing it broke
no test and leaving it broke no test either. That is the real failure —
a module with two implementations of one rule and an assertion on only
one of them.

WHY IT MATTERS MORE THAN HALF A POINT
-------------------------------------
The floor could decide the verdict, and only ever against the vendor:

    9 applicable · 5 Green · 1 Yellow · 3 Red
        floored  5   / 9 = 55.6%  ->  Negative
        client   5.5 / 9 = 61.1%  ->  Positive

And it does not stop at the site-visit screen. The result writes SCAN
parameter **N2**, in the 0.3 Non Negotiable pillar, so a wrongly-Negative
field result pulls the SCAN verdict down with it.

WHAT THIS FILE PINS
-------------------
The halving, in both directions; that the premises gate still overrides
everything; and that `>=` — not `>` — is the surveillance threshold. The
two sheets genuinely differ on that last point: SCAN's verdict is strictly
greater, this one is greater-or-equal, and reproducing each as written is
the whole job.
"""

from __future__ import annotations

import pytest

from app.catalog.surveillance import SURVEILLANCE_PARAMETERS
from app.domain.scoring import SURVEILLANCE_THRESHOLD_PCT, score_surveillance
from app.domain.types import Rating

#: An option of each colour, per parameter, taken from the catalog rather
#: than typed out — a test that hard-codes option spellings stops testing
#: the moment one is corrected.
BY_COLOUR = {
    p.id: {rating.value: option for option, rating in p.options}
    for p in SURVEILLANCE_PARAMETERS
}
GATE = SURVEILLANCE_PARAMETERS[0].id          # V1 Existence of Premises


def build(colours: dict[str, str]) -> dict[str, str | None]:
    """`{"V1": "G", "V5": "Y"}` -> the option strings the scorer expects.

    Every parameter not named is left Not Applicable, which drops it from
    both sides of the fraction.
    """
    out: dict[str, str | None] = {p.id: None for p in SURVEILLANCE_PARAMETERS}
    for pid, colour in colours.items():
        assert colour in BY_COLOUR[pid], f"{pid} has no {colour} option"
        out[pid] = BY_COLOUR[pid][colour]
    return out


def pick(n: int, colour: str, *, skip: set[str] = frozenset()) -> list[str]:
    """`n` parameter ids that actually offer `colour`."""
    ids = [p.id for p in SURVEILLANCE_PARAMETERS
           if colour in BY_COLOUR[p.id] and p.id not in skip]
    assert len(ids) >= n, f"only {len(ids)} parameters offer {colour}"
    return ids[:n]


def case(g: int, y: int, r: int) -> dict[str, str | None]:
    """A visit with `g` Green, `y` Yellow and `r` Red, premises intact.

    The gate is always Green here; its own behaviour is pinned separately.
    """
    colours = {GATE: "G"}
    used = {GATE}
    for colour, count in (("Y", y), ("R", r), ("G", g - 1)):
        for pid in pick(count, colour, skip=used):
            colours[pid] = colour
            used.add(pid)
    return build(colours)


class TestTheHalving:
    def test_one_yellow_is_half_a_green(self):
        """THE REGRESSION. This was 1.0 under the floor."""
        s = score_surveillance(case(g=1, y=1, r=0))
        assert s.G == 1 and s.Y == 1
        assert s.positives == 1.5

    def test_three_yellows_are_one_and_a_half(self):
        s = score_surveillance(case(g=0 + 1, y=3, r=0))
        assert s.Y == 3
        assert s.positives == pytest.approx(1 + 1.5)

    def test_an_even_yellow_count_is_unchanged(self):
        """The floor and the halving agree here, which is why the defect
        survived — most real visits have an even Yellow count or none."""
        s = score_surveillance(case(g=2, y=2, r=0))
        assert s.positives == 3.0

    def test_positives_is_a_float_now(self):
        """It was typed `int`, and an int field holding 5.5 is the kind of
        thing that gets silently truncated somewhere downstream."""
        assert isinstance(score_surveillance(case(g=1, y=1, r=0)).positives, float)


class TestItDecidesVerdicts:
    def test_the_case_the_client_formula_settles(self):
        """9 applicable, 5 Green, 1 Yellow, 3 Red.

        5 / 9 = 55.6% and Negative under the floor.
        5.5 / 9 = 61.1% and Positive as the client computes it.
        """
        s = score_surveillance(case(g=5, y=1, r=3))

        assert s.applicable == 9
        assert (s.G, s.Y, s.R) == (5, 1, 3)
        assert s.positives == 5.5
        assert s.pct == 61.1
        assert s.passed is True
        assert s.verdict == "Positive"

    def test_the_result_reaches_scan_as_n2(self):
        """The reason this is worth more than half a point: a wrongly
        Negative field result writes N2 in the 0.3 pillar."""
        assert score_surveillance(case(g=5, y=1, r=3)).scan_value == "Positive"

    def test_a_genuinely_thin_visit_still_fails(self):
        """The fix must not turn the threshold into a formality. Four
        Green, one Yellow, seven Red is 4.5 / 12 = 37.5%."""
        s = score_surveillance(case(g=4, y=1, r=7))
        assert s.pct == 37.5
        assert s.passed is False


class TestTheThresholdIsGreaterOrEqual:
    """SCAN's verdict is strictly `>`; this one is `>=`. The client's two
    sheets differ and both are reproduced as written, so landing exactly
    on 60% passes here and would fail there."""

    def test_landing_exactly_on_sixty_passes(self):
        s = score_surveillance(case(g=6, y=0, r=4))
        assert s.pct == 60.0
        assert s.passed is True

    def test_the_threshold_is_the_configured_one(self):
        assert SURVEILLANCE_THRESHOLD_PCT == 60.0


class TestThePremisesGateStillOverrides:
    def test_no_premises_fails_whatever_the_rest_score(self):
        """`IF(I8="red","Negative", ...)` — the gate is tested before the
        arithmetic, so a perfect visit to a site that does not exist is
        still Negative."""
        colours = {GATE: "R"}
        for pid in pick(11, "G", skip={GATE}):
            colours[pid] = "G"
        s = score_surveillance(build(colours))

        assert s.gate_failed is True
        assert s.pct >= 60.0, "the arithmetic alone would have passed"
        assert s.passed is False
        assert s.scan_value == "Negative"

    def test_the_gate_parameter_is_the_premises_one(self):
        gate = [p for p in SURVEILLANCE_PARAMETERS if p.hard_gate]
        assert len(gate) == 1
        assert gate[0].id == "V1"
        assert "Premises" in gate[0].label


class TestAgainstTheClientFormulaDirectly:
    """`=IF(I8="red","Negative", IF((M9+(M10/2))>=(0.6*M12), …))`,
    evaluated independently and compared across the whole space of
    plausible visits. A worked example can be made to agree by accident;
    a sweep cannot."""

    @staticmethod
    def workbook(s) -> bool:
        if s.gate_failed:
            return False
        if not s.applicable:
            return False
        return (s.G + s.Y / 2) >= 0.6 * s.applicable

    @pytest.mark.parametrize("g", range(1, 7))
    @pytest.mark.parametrize("y", range(0, 5))
    @pytest.mark.parametrize("r", range(0, 5))
    def test_every_combination_agrees(self, g, y, r):
        if g + y + r > len(SURVEILLANCE_PARAMETERS):
            pytest.skip("more parameters than exist")
        s = score_surveillance(case(g=g, y=y, r=r))
        assert s.passed is self.workbook(s), (
            f"{s.G}G {s.Y}Y {s.R}R of {s.applicable}: VBC says "
            f"{s.verdict}, the workbook formula says "
            f"{'Positive' if self.workbook(s) else 'Negative'}"
        )
