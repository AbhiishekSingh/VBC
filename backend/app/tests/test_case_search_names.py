"""Searching several spellings of one party, and merging the hits.

WHY THIS EXISTS. Cause-list entries are typed by court clerks, so one
company appears as "Meridian Packaging Pvt Ltd", "Meridian Packaging
Private Limited" and "M/s Meridian Packaging" across different courts.
A single-string search finds one and reports the rest as absent — and
"no cases found" is the most reassuring sentence this product prints,
so it is the one that must never come out of a thin query.

Each spelling is a paid call, so the count of calls is asserted too: a
quiet doubling of spend is not an acceptable price for better recall.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers import factsets as fx
from app.providers.ecourts import EcourtsProvider


def _provider(pages: dict[str, list[dict]]):
    """One canned result list per party name searched."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "capabilities" in url:
            return httpx.Response(200, json={"data": {"fields": [
                "parties", "courtCodes", "filingDateFrom"]}})
        party = request.url.params.get("parties", "")
        calls.append(party)
        return httpx.Response(200, json={
            "data": {"results": pages.get(party, []), "total": len(pages.get(party, []))}
        })

    provider = EcourtsProvider(
        settings=Settings(ecourts_api_key="eci_live_x", allow_paid_calls=True,
                          http_max_retries=1, http_backoff_base_seconds=0.001),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return provider, calls


ROW_A = {"cnr": "MHAH010012342020", "caseNumber": "CS/1/2020"}
ROW_B = {"cnr": "MHAH010099992021", "caseNumber": "CS/99/2021"}


class TestMergingSpellings:
    def test_each_distinct_spelling_is_one_paid_call(self):
        provider, calls = _provider({"Short Co": [], "Short Co Private Limited": []})
        out = provider.case_search_names(["Short Co", "Short Co Private Limited"])
        assert calls == ["Short Co", "Short Co Private Limited"]
        assert out["calls"] == 2

    def test_a_repeated_spelling_is_not_bought_twice(self):
        """Case-insensitively. `name` and `legalName` are often the same
        string in different case, and paying twice for that would be a
        silent tax on every vendor."""
        provider, calls = _provider({"Acme Ltd": []})
        out = provider.case_search_names(["Acme Ltd", "acme ltd", "  Acme Ltd "])
        assert calls == ["Acme Ltd"]
        assert out["calls"] == 1

    def test_the_same_case_under_two_spellings_is_counted_once(self):
        """Deduplicated by CNR, the case's own identifier. Counting it
        twice would overstate exposure in the same breath as the wider
        search was meant to measure it honestly."""
        provider, _ = _provider({
            "Acme Ltd": [ROW_A],
            "Acme Private Limited": [ROW_A, ROW_B],
        })
        out = provider.case_search_names(["Acme Ltd", "Acme Private Limited"])
        assert out["count"] == 2
        assert {r["cnr"] for r in out["results"]} == {ROW_A["cnr"], ROW_B["cnr"]}

    def test_each_hit_records_which_spelling_found_it(self):
        provider, _ = _provider({
            "Acme Ltd": [ROW_A],
            "Acme Private Limited": [ROW_B],
        })
        out = provider.case_search_names(["Acme Ltd", "Acme Private Limited"])
        found = {r["cnr"]: r["matched_name"] for r in out["results"]}
        assert found[ROW_A["cnr"]] == "Acme Ltd"
        assert found[ROW_B["cnr"]] == "Acme Private Limited"

    def test_a_row_with_no_cnr_is_kept_rather_than_collapsed(self):
        """Nothing to deduplicate against. Dropping it would lose a hit;
        merging it with its neighbours would invent one."""
        provider, _ = _provider({
            "Acme Ltd": [{"caseNumber": "CS/5/2019"}, {"caseNumber": "CS/6/2019"}],
        })
        out = provider.case_search_names(["Acme Ltd"])
        assert out["count"] == 2

    def test_per_spelling_counts_are_reported(self):
        """The screen has to be able to say what the money bought."""
        provider, _ = _provider({
            "Acme Ltd": [ROW_A],
            "Acme Private Limited": [ROW_A, ROW_B],
        })
        out = provider.case_search_names(["Acme Ltd", "Acme Private Limited"])
        assert [s["name"] for s in out["searched"]] == [
            "Acme Ltd", "Acme Private Limited"]
        assert out["searched"][0]["hits"] == 1
        # One of the second query's two was already found.
        assert out["searched"][1]["hits"] == 2
        assert out["searched"][1]["new"] == 1

    def test_no_names_is_refused_rather_than_searching_nothing(self):
        provider, _ = _provider({})
        with pytest.raises(ValueError):
            provider.case_search_names(["", "   "])


class TestTheDriftFlag:
    """REGRESSION. The flag compared `" ".join(data["query"])` against the
    vendor name — and `query` is a dict, so that joined its KEYS. Every
    search compared the literal string "parties" to the legal name,
    scored near zero, and raised "Search term differs" every single time.
    A flag that always fires is one nobody reads, and the one search that
    really had drifted looked exactly like the forty that had not.
    """

    SUBJECT = "MERIDIAN PACKAGING PRIVATE LIMITED"

    def _flags(self, data):
        return [f["label"] for f in
                (fx.case_search(data, subject=self.SUBJECT).get("flags") or [])]

    def test_an_exact_search_raises_nothing(self):
        assert self._flags(
            {"names": [self.SUBJECT], "results": [], "count": 0}) == []

    def test_the_best_of_several_spellings_decides(self):
        """Searching a loose variant alongside the exact name is the
        whole point. It is only worth flagging when NONE is close."""
        assert self._flags({
            "names": ["Meridian Packaging", self.SUBJECT],
            "results": [], "count": 0,
        }) == []

    def test_a_real_drift_still_flags(self):
        flags = self._flags(
            {"names": ["Totally Different Co"], "results": [], "count": 0})
        assert any("differs" in f for f in flags)

    def test_an_older_payload_without_names_still_works(self):
        """Rows written before `names` existed carry the string under
        `query["parties"]`, and must not start flagging on re-render."""
        assert self._flags(
            {"query": {"parties": self.SUBJECT}, "results": [], "count": 0}) == []

    def test_the_dict_shape_the_PROVIDER_returns_is_read(self):
        """The shape that was broken in production.

        `case_search` returns `query` as a dict of filters, and the old
        code joined it — yielding the key "parties". These tests used a
        LIST, so the suite was green while every live search flagged.
        """
        assert self._flags({
            "query": {"parties": self.SUBJECT, "courtCodes": "MHAH01"},
            "results": [], "count": 0,
        }) == []

    def test_the_list_shape_the_OLD_TESTS_used_is_read(self):
        assert self._flags(
            {"query": [self.SUBJECT], "results": [], "count": 0}) == []

    def test_a_drift_is_caught_in_the_dict_shape_too(self):
        flags = self._flags({
            "query": {"parties": "Totally Different Co"},
            "results": [], "count": 0,
        })
        assert any("differs" in f for f in flags)
