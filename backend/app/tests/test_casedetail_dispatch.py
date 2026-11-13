"""The case-detail branch of `_dispatch`, EXECUTED.

WHAT HAPPENED
-------------
`cefb999` added a guard so an index stub could never become a paid
lookup:

    if not CNR_SHAPE.match(str(cnr).strip().upper()):

`runner.py` imports the provider as `ec_mod`, so the bare name does not
resolve. Every single case detail raised

    NameError: name 'CNR_SHAPE' is not defined

and the catch-all in `_run_one` recorded it as "Unexpected error" with
no payload. Three runs against three different CNRs, all dead, and the
screen blamed the provider.

WHY THE SUITE WAS GREEN
-----------------------
`test_cnr_stubs.py` has nine tests. Every one of them imports
`CNR_SHAPE` and `_cnr_in` FROM `app.providers.ecourts` and asserts on
them there. The regex was never in doubt. The line that calls it was
never run.

`test_input_fallback.py` shows the same shape more starkly: it lifts
the reader out of `_dispatch` into a local `make_get` and tests the
copy. A test that re-implements the code under test cannot catch a
NameError in the original.

So the rule this file exists to hold: the guard protecting a paid call
must be exercised THROUGH the dispatcher, with a provider attached, on
a CNR that is expected to pass. A test that only proves the regex works
proves nothing about whether anything calls it.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.types import CheckStatus
from app.services.runner import CheckRunner, Finding

VALID_CNR = "MPHC020051722014"


class FakeVendor:
    id = "V1"
    name = "Flamingo Infinite"
    legal_name = "FLAMINGO INFINITE PRIVATE LIMITED"
    cin = "U21029MH2013PTC245119"
    domain = None
    website = None
    gst = None
    selected: list[str] = []


class FakeECourts:
    """Records what it was asked for, so "was the provider reached?" is
    a question the test can answer rather than infer."""

    def __init__(self, payload: dict | None = None):
        self.calls: list[str] = []
        self.payload = payload or {}

    def case_detail(self, cnr: str) -> dict:
        self.calls.append(cnr)
        return {
            "cnr": cnr,
            "case_number": "WP/1234/2024",
            "case_status": "PENDING",
            "disposal_type_raw": None,
            "case_type_sub": "Writ Petition",
            "case_type_label": "WP",
            "acts_and_sections": "Art. 226",
            "court_name": "Madhya Pradesh High Court",
            "filing_date": "2024-03-11",
            "order_count": 2,
            "hearing_count": 5,
            "judgment_count": 0,
            "is_pending": True,
            "petitioners": ["FLAMINGO INFINITE PRIVATE LIMITED"],
            "respondents": ["STATE OF MADHYA PRADESH"],
            **self.payload,
        }


def make_runner(ecourts=None) -> CheckRunner:
    runner = CheckRunner.__new__(CheckRunner)
    runner.session = None
    runner.settings = Settings(ecourts_api_key="ec_test_key")
    runner.spend = None
    runner.ecourts = ecourts
    runner.filesure = runner.whoisxml = runner.archive = None
    runner.finagg = runner.gridlines = runner.vision = None
    return runner


def dispatch(runner, inputs: dict | None = None, prior: dict | None = None) -> Finding:
    return runner._dispatch(
        "casedetail", FakeVendor(), FakeVendor.cin,
        {"casedetail": inputs or {}}, None, None, prior or {},
    )


class TestAValidCnrReachesTheProvider:
    def test_the_guard_does_not_raise_on_a_well_formed_cnr(self):
        """THE REGRESSION. This raised NameError at the guard, before the
        provider was ever called — so the assertion that matters is not
        the status but that `case_detail` was reached at all."""
        ec = FakeECourts()
        finding = dispatch(make_runner(ec), {"cnr": VALID_CNR})

        assert ec.calls == [VALID_CNR]
        assert finding.status is not CheckStatus.UNAVAILABLE

    def test_a_pending_matter_warns(self):
        finding = dispatch(make_runner(FakeECourts()), {"cnr": VALID_CNR})
        assert finding.status is CheckStatus.WARN
        assert "PENDING" in finding.value

    def test_a_disposed_matter_passes(self):
        ec = FakeECourts({"is_pending": False, "case_status": "DISPOSED",
                          "disposal_type_raw": "DISMISSED_AS_WITHDRAWN"})
        finding = dispatch(make_runner(ec), {"cnr": VALID_CNR})

        assert finding.status is CheckStatus.PASS
        # The disposal TYPE carries the finding — "disposed" alone covers
        # both a withdrawal and a conviction.
        assert "DISMISSED_AS_WITHDRAWN" in finding.value

    def test_both_sides_of_the_matter_are_named(self):
        finding = dispatch(make_runner(FakeECourts()), {"cnr": VALID_CNR})
        assert "FLAMINGO INFINITE PRIVATE LIMITED" in finding.detail
        assert "STATE OF MADHYA PRADESH" in finding.detail

    def test_padding_and_case_are_tolerated(self):
        """An analyst pasting from a search result brings whitespace."""
        ec = FakeECourts()
        dispatch(make_runner(ec), {"cnr": f"  {VALID_CNR.lower()}  "})
        assert ec.calls, "a paddable CNR was refused by the guard"


class TestAStubIsRefusedBeforeTheCharge:
    """eCourts bills on accepting the request, so the refusal has to
    happen on our side of the wire."""

    @pytest.mark.parametrize("stub", [
        "row-9",                 # an index id
        "DLHC01000123202",       # fifteen digits — the near-miss
        "DLHC0100012320241",     # seventeen
        "12345678901234567890",  # no letters
        "ABCD-0100-0123-2024",   # punctuated
    ])
    def test_the_provider_is_never_called(self, stub):
        ec = FakeECourts()
        finding = dispatch(make_runner(ec), {"cnr": stub})

        assert ec.calls == [], f"{stub!r} was sent to a paid endpoint"
        assert finding.status is CheckStatus.SKIPPED_MISSING_INPUT
        assert "not a case number" in finding.detail.lower()

    def test_no_cnr_at_all_is_skipped_not_failed(self):
        """Nothing to look up is not the same as a lookup that failed —
        and an empty input must not read as a clean result either."""
        ec = FakeECourts()
        finding = dispatch(make_runner(ec), {})

        assert ec.calls == []
        assert finding.status is CheckStatus.SKIPPED_MISSING_INPUT


class TestTheCnrComesFromTheSearchWhenNoneIsTyped:
    def test_the_first_cnr_of_the_search_is_used(self):
        ec = FakeECourts()
        prior = {"courtsearch": Finding(
            "courtsearch", CheckStatus.WARN, "2 cases", "",
            raw={"results": [{"cnr": VALID_CNR}, {"cnr": "DLHC010001232024"}]},
        )}
        dispatch(make_runner(ec), {}, prior)
        assert ec.calls == [VALID_CNR]

    def test_a_typed_cnr_beats_the_search_result(self):
        """The analyst picking a specific row is the whole point of the
        add-more dialog."""
        ec = FakeECourts()
        prior = {"courtsearch": Finding(
            "courtsearch", CheckStatus.WARN, "1 case", "",
            raw={"results": [{"cnr": "DLHC010001232024"}]},
        )}
        dispatch(make_runner(ec), {"cnr": VALID_CNR}, prior)
        assert ec.calls == [VALID_CNR]
