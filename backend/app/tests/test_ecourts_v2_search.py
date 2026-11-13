"""The v2 migration, asserted against RESPONSES ACTUALLY CAPTURED.

Every fixture below is trimmed from a real production response taken on
13 Nov 2026. Nothing here is a guess at a shape, because on this project
every parser written from a guess has cost a round trip — three of them
in the afternoon that produced this file.

WHAT WENT WRONG, in the order it was found.

1. `/search?parties=` STOPPED FILTERING. `parties` was whitelisted in
   `CONFIRMED_UNLISTED_FILTERS` on the strength of a 200 seen on
   2026-09-07. By November v1 neither honoured nor rejected it: it
   ignored the parameter and answered with page 1 of all 352,808,560
   cases in the national index, each row a hollow stub.

   The guard written for this fired only on an EMPTY result set. Twenty
   rows came back, so it passed. We had anticipated a bad filter
   returning nothing and got one returning everything.

2. `activeFilters` IS NOT THE SIGNAL. It was believed to be, briefly,
   during the investigation. A SUCCESSFUL v2 search — 100,273 real hits
   — also returns `activeFilters: []`, because the field echoes facet
   filters and never name parameters. A guard built on it would have
   rejected every good search.

   What distinguishes the two is the CONTENT: rows from a real name
   search name that party; rows from a corpus dump do not. That test
   depends on no provider field, so it survives the next API change.

3. `nameMatchMode` DEFAULTS TO `all`. VBC searches the MCA legal name by
   design, so it asks for "FLAMINGO INFINITE PRIVATE LIMITED" while the
   clerk typed "FLAMINGO INFINITE PVT LTD". Under `all` that is a miss,
   and the miss prints as "no cases found" — the most reassuring
   sentence this product can produce, from a query that could not have
   succeeded.

4. CASE DETAIL READ HALF THE RECORD. `disposalType`, `caseNumber`,
   `courtName`, `orderCount`, `hearingCount`, `judgmentCount`,
   `caseDurationDays` and `iaCount` are NOT in `courtCaseData`. They are
   in a second block beside it. The ParseGuard passed because the two
   things it checked both sat in the block we did read.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers import ecourts as ec
from app.providers.base import ProviderParseGap

SUBJECT = "FLAMINGO INFINITE PRIVATE LIMITED"

#: Capability catalogue, trimmed. Note what is NOT here: no `parties`,
#: and no name parameter in any field array at all — they are advertised
#: separately under `multiValueNameParams`, CAPITALISED, and the
#: capitalised spelling does not work.
CAPS = {"data": {
    "sortableFields": ["score", "filingDate", "cnr"],
    "facetableFields": ["caseType", "caseStatus", "courtCode", "stateCode"],
    "projectableFields": ["cnr", "petitioners", "respondents", "courtName"],
    "nameMatchModes": ["all", "any", "phrase", "fuzzy"],
    "multiValueNameParams": ["Litigants", "Petitioners", "Respondents"],
    "v2Search": {"searchPath": "/api/partner/v2/search"},
}}

#: ONE ROW OF THE 352-MILLION-CASE DUMP, verbatim. An identifier and
#: nothing else — which is also why case detail 404'd on these: they are
#: index placeholders with no case files behind them.
HOLLOW_ROW = {
    "id": "MPHC020051722014", "cnr": "MPHC020051722014",
    "caseType": "UNKNOWN", "caseStatus": "UNKNOWN",
    "filingNumber": "", "filingDate": None,
    "petitioners": [], "respondents": [], "judges": [],
    "courtCode": "MPHC02", "courtName": None,
    "orderCount": 0, "hearingCount": 0,
}

#: A REAL HIT from the control search, trimmed. The parties are what
#: make it recognisable as a genuine result.
REAL_ROW = {
    "id": "DRTM3OA006572016", "cnr": "DRTM3OA006572016",
    "caseType": "OA_DRT", "caseStatus": "DISPOSED",
    "filingDate": "2016-05-24", "decisionDate": "2020-11-07",
    "petitioners": ["FLAMINGO INFINITE PVT LTD"],
    "respondents": ["BANK OF INDIA"],
    "courtName": "DRT - Debt Recovery Tribunal, Mumbai-3, Maharashtra",
    "orderCount": 2, "hearingCount": 8,
}


def _settings(**kw) -> Settings:
    base = dict(ecourts_api_key="eci_live_test", allow_paid_calls=True)
    base.update(kw)
    return Settings(**base)


def _router(results, *, total=None, facet_mode="counted", seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/search/capabilities" in url:
            return httpx.Response(200, json=CAPS)
        if "/search" in url:
            if seen is not None:
                seen.append(request.url)
            return httpx.Response(200, json={"data": {
                "results": results,
                "totalHits": len(results) if total is None else total,
                "facetMode": facet_mode,
                # Empty on a SUCCESSFUL name search too. This is the
                # field that must not be used as the guard.
                "activeFilters": [],
                "query": None,
            }})
        raise AssertionError(url)
    return handler


def _provider(handler, **kw) -> ec.EcourtsProvider:
    return ec.EcourtsProvider(
        _settings(**kw), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


class TestTheRequest:
    def test_it_goes_to_v2(self):
        """v1 is deprecated AND broken for this use — it ignores an
        unknown name filter rather than rejecting it."""
        seen: list[httpx.URL] = []
        _provider(_router([REAL_ROW], seen=seen)).case_search(litigants=SUBJECT)
        assert "/v2/search" in str(seen[0])

    def test_the_name_goes_as_litigants(self):
        seen: list[httpx.URL] = []
        _provider(_router([REAL_ROW], seen=seen)).case_search(litigants=SUBJECT)
        assert seen[0].params.get("litigants") == SUBJECT

    def test_fuzzy_is_sent_by_default(self):
        """THE DEFAULT THAT MATTERS. The provider's own default is `all`,
        which cannot match a clerk's "PVT LTD" against an MCA "PRIVATE
        LIMITED" — and the miss reads as "no cases found"."""
        seen: list[httpx.URL] = []
        _provider(_router([REAL_ROW], seen=seen)).case_search(litigants=SUBJECT)
        assert seen[0].params.get("nameMatchMode") == "fuzzy"

    def test_the_caller_can_narrow_the_mode(self):
        seen: list[httpx.URL] = []
        _provider(_router([REAL_ROW], seen=seen)).case_search(
            litigants=SUBJECT, nameMatchMode="phrase")
        assert seen[0].params.get("nameMatchMode") == "phrase"

    def test_an_unknown_mode_is_refused_before_the_charge(self):
        with pytest.raises(ValueError, match="nameMatchMode"):
            _provider(_router([REAL_ROW])).case_search(
                litigants=SUBJECT, nameMatchMode="approximately")

    def test_a_filter_with_no_name_sends_no_mode(self):
        """`nameMatchMode` applies to name parameters. Sending it beside
        a pure facet query claims a match that was never made."""
        seen: list[httpx.URL] = []
        _provider(_router([REAL_ROW], seen=seen)).case_search(caseStatus="PENDING")
        assert "nameMatchMode" not in seen[0].params

    def test_parties_is_now_refused(self):
        """The whitelist is gone. `parties` reaches the capability check
        like any other unknown filter and is refused there — instead of
        being sent and silently ignored."""
        with pytest.raises(ValueError, match="parties"):
            _provider(_router([REAL_ROW])).case_search(parties=SUBJECT)


class TestTheSubjectMatchGuard:
    def test_the_corpus_dump_is_a_parse_gap(self):
        """THE REGRESSION THIS FILE EXISTS FOR. Twenty well-formed rows,
        200 OK, and not one of them about the subject. Before the guard
        this reported as the vendor's litigation."""
        with pytest.raises(ProviderParseGap, match="was not applied"):
            _provider(
                _router([HOLLOW_ROW] * 20, total=352_808_560)
            ).case_search(litigants=SUBJECT)

    def test_other_parties_cases_are_a_parse_gap(self):
        """The dangerous version: rows that look entirely healthy and
        belong to somebody else."""
        stranger = {**REAL_ROW,
                    "petitioners": ["TATA CONSULTANCY SERVICES LIMITED"],
                    "respondents": ["UNION OF INDIA"]}
        with pytest.raises(ProviderParseGap, match="was not applied"):
            _provider(_router([stranger] * 5)).case_search(litigants=SUBJECT)

    def test_a_real_hit_passes(self):
        out = _provider(_router([REAL_ROW])).case_search(litigants=SUBJECT)
        assert out["count"] == 1

    def test_a_clerks_spelling_still_passes(self):
        """THE GUARD MUST NOT UNDO THE FUZZY SEARCH. Finding "FLAMINGO
        INFINITE PVT LTD" for "FLAMINGO INFINITE PRIVATE LIMITED" is the
        entire point; a guard that rejected it would convert every real
        result into a parse gap."""
        for spelling in ("M/s Flamingo Infinite Pvt. Ltd.",
                         "FLAMINGO INFINITE P LTD",
                         "Flamingo Infinite"):
            row = {**REAL_ROW, "petitioners": [spelling]}
            out = _provider(_router([row])).case_search(litigants=SUBJECT)
            assert out["count"] == 1, spelling

    def test_matching_on_private_limited_alone_is_not_a_match(self):
        """Millions of companies share those words. A row matching only
        on them has told us nothing about whether the filter ran."""
        row = {**REAL_ROW, "petitioners": ["SUNRISE TEXTILES PRIVATE LIMITED"],
               "respondents": ["ANOTHER TRADING PRIVATE LIMITED"]}
        with pytest.raises(ProviderParseGap):
            _provider(_router([row])).case_search(litigants=SUBJECT)

    def test_an_empty_result_is_not_a_parse_gap(self):
        """A company with no litigation is a real answer, and the guard
        must not turn it into an error — only rows that contradict the
        query do that."""
        out = _provider(_router([])).case_search(litigants=SUBJECT)
        assert out["count"] == 0

    def test_one_matching_row_vouches_for_the_page(self):
        """A fuzzy search legitimately returns near misses beside the
        real ones. The question is whether the page is about our subject
        at all, not whether every row is."""
        stranger = {**REAL_ROW, "petitioners": ["SOME OTHER CO"]}
        out = _provider(
            _router([stranger, REAL_ROW, stranger])
        ).case_search(litigants=SUBJECT)
        assert out["count"] == 3


class TestWhatComesBack:
    def test_the_total_is_read_from_totalHits(self):
        """v2 renamed it. Read under the v1 spellings it was always None,
        which showed as "unknown" rather than as a field we were looking
        for under the wrong name."""
        out = _provider(
            _router([REAL_ROW], total=100_273)
        ).case_search(litigants=SUBJECT)
        assert out["total"] == 100_273

    def test_a_truncated_total_says_so(self):
        """`facetMode: "full"` means the server stopped counting.
        Reporting a lower bound as a count overstates precision about
        how much litigation exists."""
        out = _provider(
            _router([REAL_ROW], total=100_273, facet_mode="full")
        ).case_search(litigants=SUBJECT)
        assert out["total_is_lower_bound"] is True

    def test_an_exact_total_is_not_flagged(self):
        out = _provider(
            _router([REAL_ROW], total=1, facet_mode="counted")
        ).case_search(litigants=SUBJECT)
        assert out["total_is_lower_bound"] is False

    def test_the_mode_used_travels_with_the_result(self):
        """How wide the net was is part of reading what it caught."""
        out = _provider(_router([REAL_ROW])).case_search(litigants=SUBJECT)
        assert out["name_match_mode"] == "fuzzy"
