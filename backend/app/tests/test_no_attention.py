"""VBC does not hold opinions about what a provider returned.

THE DECISION, 17 Nov 2026
-------------------------
"Attention" (CheckStatus.WARN) was removed because it asserted that
something a source returned was CONCERNING. Every threshold behind it
was chosen in this codebase:

    domain age < 2 years          reputation score < 80
    negative net worth            GST filed 1-3 months ago
    case status PENDING           any open charge
    MCA status not "Active"       archive not continuous
    a case listed for hearing     no director contact details

None of those came from a client, a standard, or the registry that
supplied the fact. Whether a two-year-old domain disqualifies a supplier
is the analyst's judgement and the client's policy. VBC fetches the
fact, shows it unaltered, and says plainly when it could not.

WHAT SURVIVED, AND WHY IT HAD TO
--------------------------------
Removing the opinion must not turn a GAP into a CLEARANCE. Two things
were never opinions and are now `NEEDS_CONFIRMATION`:

  * we cannot show the answer is about this subject — court cases
    matched on name alone, several CIN or DIN candidates, a GST status
    string we do not recognise;
  * the source returned nothing where something was sought — no DIN, no
    contact details, a refresh that never completed.

`test_unbuilt_checks.py` names four tests after this very rule
("...is_a_gap_not_a_clearance"). Collapsing those to PASS is the one
failure this product exists to prevent, with the sign flipped.

THE TRAP THIS FILE EXISTS TO CATCH
----------------------------------
Four risk rules awarded points for a GOOD outcome and tested it with
`_passed(check)`, which worked only while the check reported something
OTHER than PASS for the bad outcome:

    r1 +20  "MCA registered and active"        PASS unless struck off
    r2 +10  "Filings current"                  PASS unless none returned
    r3 +15  "positive net worth"               PASS unless negative
    r5 +10  "continuous presence, no outages"  PASS unless outages

The moment those checks began reporting PASS in every case, r1 would
have awarded +20 to a struck-off company and r3 +15 for a loss. A gap
reading as clean is this product's cardinal failure; adverse reading as
POSITIVE is the same failure, worth more points. They now read the
stored payload, as `_gst_flag` and `_court_adverse` already did.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.catalog.risk import RULE_TESTS
from app.domain.types import CheckResult, CheckStatus

RUNNER = pathlib.Path(__file__).resolve().parents[1] / "services" / "runner.py"


def _result(status: CheckStatus, value: str = "x", raw=None,
            check_id: str = "x") -> CheckResult:
    return CheckResult(check_id=check_id, status=status, value=value,
                       detail="", raw_response=raw)


class TestNothingEmitsAttentionAnyMore:
    def test_the_runner_contains_no_warn(self):
        """Grep-proof, so a merge cannot quietly reintroduce it."""
        source = RUNNER.read_text()
        assert "CheckStatus.WARN" not in source, (
            "A check is emitting Attention again. If it is a judgement "
            "about the vendor it does not belong here; if it is a gap or "
            "an unconfirmed identity, use NEEDS_CONFIRMATION."
        )

    def test_the_status_still_exists_for_stored_rows(self):
        """Rows written before 17 Nov 2026 carry 'warn' and must keep
        deserialising — and keep scoring exactly as they did."""
        assert CheckStatus("warn") is CheckStatus.WARN
        assert CheckStatus.WARN.is_adverse is True

    def test_needs_confirmation_is_adverse(self):
        """r8 and r9 read `is_adverse`. If this flipped, a duplicate
        vendor and a related-party overlap would silently stop scoring."""
        assert CheckStatus.NEEDS_CONFIRMATION.is_adverse is True

    def test_needs_confirmation_was_not_examined(self):
        """Twenty cases matched on a company name are candidates, not
        evidence about this vendor. Counting them as examined would let
        an unconfirmed match widen coverage it never provided."""
        assert CheckStatus.NEEDS_CONFIRMATION.was_examined is False


class TestTheRulesReadFactsNotStatuses:
    """Each of these fires on the PAYLOAD. A check that now returns PASS
    for both outcomes cannot be used as a proxy for the good one."""

    @pytest.mark.parametrize("rule,check,good,bad", [
        ("r1", "master", {"facts": {"status": "ACTIVE"}},
                         {"facts": {"status": "STRUCK OFF"}}),
        ("r2", "filings", {"rows": [{"formId": "AOC-4"}]}, {"rows": []}),
        ("r3", "fin", {"facts": {"positive_net_worth": True}},
                      {"facts": {"positive_net_worth": False}}),
        ("r5", "cdx", {"continuous": True}, {"continuous": False}),
    ])
    def test_a_positive_rule_reads_the_fact(self, rule, check, good, bad):
        passing = {check: _result(CheckStatus.PASS, raw=good)}
        failing = {check: _result(CheckStatus.PASS, raw=bad)}

        assert RULE_TESTS[rule](passing) is True
        assert RULE_TESTS[rule](failing) is False, (
            f"{rule} fired on a PASS carrying the ADVERSE fact — it is "
            f"reading the status, not the payload."
        )

    def test_an_open_charge_still_costs_points(self):
        """r7 is the only NEGATIVE rule that read the old status. An
        unsatisfied charge is a registry fact, not our opinion, and it
        has to keep scoring now that `charges` reports PASS."""
        charged = {"charges": _result(
            CheckStatus.PASS, raw={"open": [{"holder": "HDFC"}], "closed": []})}
        clear = {"charges": _result(
            CheckStatus.PASS, raw={"open": [], "closed": [{"holder": "SBI"}]})}

        assert RULE_TESTS["r7"](charged) is True
        assert RULE_TESTS["r7"](clear) is False


class TestAResultWithNoPayloadFallsBackToItsStatus:
    """A MANUALLY RECORDED result carries no provider payload at all —
    the Kaveri fixture's suspended GSTIN arrives exactly that way, and so
    does every row stored before a check kept its raw response.

    Reading "no payload" as "the fact is false" would have silently
    stopped r1, r2, r3, r5 and r7 scoring for all of them.
    """

    @pytest.mark.parametrize("rule,check", [
        ("r1", "master"), ("r2", "filings"), ("r3", "fin"), ("r5", "cdx"),
    ])
    def test_a_bare_pass_still_satisfies_a_positive_rule(self, rule, check):
        assert RULE_TESTS[rule]({check: _result(CheckStatus.PASS)}) is True

    @pytest.mark.parametrize("rule,check", [
        ("r1", "master"), ("r2", "filings"), ("r3", "fin"), ("r5", "cdx"),
    ])
    def test_a_bare_non_pass_does_not(self, rule, check):
        assert RULE_TESTS[rule](
            {check: _result(CheckStatus.NEEDS_CONFIRMATION)}) is False

    def test_a_legacy_warn_on_charges_still_costs_points(self):
        """Stored rows from before the change carry WARN and no payload.
        They scored -15 then and must score -15 now."""
        assert RULE_TESTS["r7"]({"charges": _result(CheckStatus.WARN)}) is True

    def test_a_missing_check_satisfies_nothing(self):
        for rule in ("r1", "r2", "r3", "r5", "r7"):
            assert RULE_TESTS[rule]({}) is False


class TestTheDispatcherStillDistinguishesTheThreeOutcomes:
    """The point of the change is NOT that everything is green."""

    def test_every_status_the_runner_can_emit(self):
        tree = ast.parse(RUNNER.read_text())
        emitted = {
            node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "CheckStatus"
        }
        assert "WARN" not in emitted
        # Still able to say "bad", "unconfirmed" and "we could not look".
        for needed in ("PASS", "FAIL", "NEEDS_CONFIRMATION", "UNAVAILABLE",
                       "SKIP", "SKIPPED_MISSING_INPUT", "NOT_CONFIGURED"):
            assert needed in emitted, f"{needed} is no longer reachable"
