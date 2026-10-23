"""The catalog's `feeds` must match what the runner actually writes.

WHY THIS TEST EXISTS
--------------------
`CheckDefinition.feeds` is a CLAIM: "running this check fills these SCAN
parameters". `_write_auto_ratings` in app/api/routes.py is what actually
fills them. Nothing connected the two, so the October migration moved the
writes and left the claims behind:

    fin       feeds=("N3",)   -> N3 once meant "Turnover of the Vendor";
                                 it now means Conflict of Interest, and
                                 this check writes nothing at all.
    conflict  feeds=("A3",)   -> the runner writes N3. A3 is "Risk
                                 Taking", a psychometric dimension no
                                 automated check can fill.

Neither broke a score — scores come from the runner. Both broke the
screen: the "fills S1, S2" chips, and the "Automatable SCAN parameters"
tile on Step 2, which counted coverage the product does not have. A tile
that overstates coverage is the same class of error as a gap reading as a
clean result.

Parsed from the source rather than executed, because `_write_auto_ratings`
needs a session, a vendor and a RunResult to say anything. Crude, and it
catches the one thing that went wrong: a rating written under an id no
check declares, or declared by a check that never writes it.
"""

from __future__ import annotations

import ast
import pathlib
import re

from app.catalog.checks import CHECKS
from app.catalog.scan import SCAN_PARAMETERS

ROUTES = pathlib.Path(__file__).parents[1] / "api" / "routes.py"
PARAM_IDS = {p.id for p in SCAN_PARAMETERS}


def _written_by_runner() -> set[str]:
    """Every SCAN id passed to `_set_rating` in `_write_auto_ratings`."""
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_write_auto_ratings"),
        None,
    )
    assert func is not None, "_write_auto_ratings has been renamed or moved"

    written: set[str] = set()
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_set_rating"):
            continue
        # _set_rating(session, vendor_id, "<PARAM>", value, ...)
        if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
            written.add(str(node.args[2].value))
    return written


class TestFeedsAreTrue:
    def test_every_declared_feed_is_a_real_parameter(self):
        for check in CHECKS:
            for param_id in check.feeds:
                assert param_id in PARAM_IDS, (
                    f"{check.id} claims to fill {param_id}, which is not a "
                    f"SCAN parameter. Retired ids must be removed, not left "
                    f"pointing at whatever now holds the number."
                )

    def test_nothing_claims_a_parameter_the_runner_never_writes(self):
        written = _written_by_runner()
        # N2 is written by the surveillance endpoint, not by a check.
        written.add("N2")
        for check in CHECKS:
            for param_id in check.feeds:
                assert param_id in written, (
                    f"{check.id} declares feeds={check.feeds} but the runner "
                    f"never writes {param_id}. Step 2 counts this as "
                    f"automatable coverage the product does not have."
                )

    def test_every_auto_parameter_has_a_check_that_fills_it(self):
        """An AUTO parameter nothing fills is a promise with no source."""
        declared = {p for c in CHECKS for p in c.feeds}
        auto = {p.id for p in SCAN_PARAMETERS if p.source.value == "AUTO"}
        orphans = auto - declared
        assert not orphans, (
            f"AUTO parameters with no check behind them: {sorted(orphans)}. "
            f"Either a check should declare them, or they are HUMAN."
        )

    def test_the_two_that_were_wrong_stay_right(self):
        """Regression pins. Both were silently wrong for two weeks."""
        by_id = {c.id: c for c in CHECKS}
        assert by_id["conflict"].feeds == ("N3",), (
            "Director conflict writes N3. It declared A3 — a psychometric "
            "dimension no automated check can reach."
        )
        assert by_id["fin"].feeds == (), (
            "Filed financials writes no rating. It declared N3 from when "
            "N3 meant Turnover."
        )
