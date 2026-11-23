"""A company that filed no accounts must not score for healthy ones.

WHAT WAS FOUND, 23 NOV 2026
---------------------------
The `fin` branch returned this when MCA held no accounts:

    return Finding(
        # r3 reads positive_net_worth from the payload, so an
        # absent filing cannot score as a healthy one.
        check_id, CheckStatus.PASS, "No financials filed",
        "The requested form type is not among those available ...",
    )

The comment was wrong, and wrong in the direction that costs points. The
Finding carried NO payload at all. `_fact` returns the `_NO_PAYLOAD`
sentinel for a result with no raw response, and every positive rule falls
back to the STATUS when it sees that — deliberately, because a manually
recorded result legitimately has no payload and must still be able to
score. The status here is PASS.

So rule r3, "Filed financials show positive net worth", **+15**, fired
for a company that had filed no financials whatsoever.

A gap reading as clean is this product's cardinal failure. A gap reading
as POSITIVE is the same failure with the sign flipped, and this one was
worth fifteen points on a hundred-point scale — enough to move a vendor a
whole band.

WHY THE SUITE WAS GREEN
-----------------------
`test_no_attention.py` asserts that r3 fires on a positive payload and
does not fire on a negative one, and that a bare PASS with no payload
still fires — which is the manual-entry fallback, and correct. Nothing
asserted what happens when the RUNNER itself produces a PASS with no
payload while the fact is absent. The rule was tested; the caller that
violated its contract was not.

THE FIX IS AT THE FINDING, NOT THE RULE
---------------------------------------
The sentinel means "nothing to read", so the honest remedy is to give it
something to read. `positive_net_worth: False` would assert the net worth
is negative, which is not known either — so the key carries None,
`bool(None)` is False, r3 does not fire, and nothing claims a figure.
"""

from __future__ import annotations

from app.catalog.risk import RULE_TESTS
from app.domain.types import CheckResult, CheckStatus
from app.providers import factsets

#: What the `fin` branch now stores when MCA holds no accounts.
NO_FILING = {
    "form_type": "AOC-4",
    "filed": False,
    "facts": {"positive_net_worth": None, "revenue": None},
}


def _r3(raw) -> bool:
    checks = {"fin": CheckResult("fin", CheckStatus.PASS, "v", "d", raw)}
    return RULE_TESTS["r3"](checks)


class TestR3ReadsTheFilingAndNotTheStatus:
    def test_no_financials_filed_does_not_score(self):
        """THE REGRESSION. This awarded +15."""
        assert _r3(NO_FILING) is False

    def test_a_positive_net_worth_still_scores(self):
        assert _r3({"facts": {"positive_net_worth": True}}) is True

    def test_a_negative_net_worth_still_does_not(self):
        assert _r3({"facts": {"positive_net_worth": False}}) is False

    def test_a_result_with_no_payload_at_all_still_falls_back(self):
        """THE FALLBACK MUST SURVIVE. A manually recorded result carries
        no provider payload, and an analyst who has read the accounts and
        marked the check PASS is entitled to the points. Removing the
        fallback to fix the bug above would break that, which is why the
        fix is at the Finding instead."""
        assert _r3(None) is True


class TestTheScreenSaysItToo:
    """A rule that no longer scores is half the fix. A reader scanning
    the report saw "No financials filed" in the same green as a company
    whose accounts had been read and were healthy, with no facts panel
    at all underneath it."""

    def _blob(self) -> dict:
        return factsets.no_financials("AOC-4")

    def test_there_is_a_facts_blob_now(self):
        blob = self._blob()
        assert blob["shape"] == "summary"

    def test_net_worth_is_a_dash_not_a_number(self):
        stat = next(s for s in self._blob()["stats"] if s["label"] == "Net worth")
        assert stat["value"] == "—"
        assert stat["tone"] == "neutral"

    def test_nothing_is_toned_good(self):
        """Green on a check that established nothing is the whole bug,
        rendered."""
        assert not any(s["tone"] == "good" for s in self._blob()["stats"])

    def test_the_note_says_what_is_not_established(self):
        note = self._blob()["note"].lower()
        assert "not a reading of a healthy balance sheet" in note
        assert "unestablished" in note

    def test_the_form_type_asked_for_is_named(self):
        """"No financials filed" is ambiguous between "this company files
        nothing" and "not under the form we asked for"."""
        assert "AOC-4" in factsets.no_financials("AOC-4")["note"]
        assert "MGT-7" in factsets.no_financials("MGT-7")["note"]


# =====================================================================
# THE TEST THAT WOULD HAVE CAUGHT IT
# =====================================================================
#
# Everything above asserts the RULE's contract, and the rule was never
# the thing that was broken — the caller was. `_dispatch` produced a
# Finding that violated the contract, and no test ran the two together.
#
# So this one executes the `fin` branch with a provider that holds no
# accounts, takes the Finding it actually returns, and scores THAT.

from app.config import Settings                      # noqa: E402
from app.services.runner import CheckRunner, Finding  # noqa: E402

CIN = "U46909MH2020PLC351339"


class FakeVendor:
    id = "V1"
    name = "Acme"
    legal_name = "ACME PRIVATE LIMITED"
    cin = CIN
    domain = None
    website = None
    gst = None
    selected: list[str] = []


class FileSureWithNoAccountsOnFile:
    """MCA holds no AOC-4 for this company. Not an error — an absence."""

    def latest_financials(self, cin, *, form_type="AOC-4", year=None,
                          scope="standalone"):
        return {}


def _fin_finding() -> Finding:
    runner = CheckRunner.__new__(CheckRunner)
    runner.session = None
    runner.settings = Settings(filesure_api_key="fs_test_key")
    runner.spend = None
    runner.filesure = FileSureWithNoAccountsOnFile()
    runner.ecourts = runner.whoisxml = runner.archive = None
    runner.finagg = runner.gridlines = runner.vision = None
    return runner._dispatch("fin", FakeVendor(), CIN, {}, None, None, {})


class TestTheFindingTheRunnerActuallyProduces:
    def test_it_does_not_score_for_positive_net_worth(self):
        """THE REGRESSION, end to end. +15 to a company with no accounts."""
        finding = _fin_finding()
        checks = {"fin": CheckResult("fin", finding.status, finding.value,
                                     finding.detail, finding.raw)}
        assert RULE_TESTS["r3"](checks) is False

    def test_it_carries_a_payload_at_all(self):
        """The sentinel that triggered the fallback. A Finding whose raw
        is None is indistinguishable from a manual entry."""
        assert _fin_finding().raw is not None

    def test_it_carries_a_facts_blob(self):
        """Without one the UI renders a bare green line and nothing else
        — which is how the report said 'fine' about a company it knew
        nothing about."""
        assert _fin_finding().facts is not None

    def test_the_detail_says_net_worth_is_not_established(self):
        assert "not established" in _fin_finding().detail.lower()
