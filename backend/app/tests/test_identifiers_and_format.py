"""Who can be audited, how much of their record is read, and how it reads.

Four fixes, one theme: the code was narrower than the API it calls.

1. `idType` was pinned to `"cin"`, so the provider applied CIN validation to
   every identifier and an LLP — which has an LLPIN, not a CIN — came back
   `400 INVALID_CIN`. LLPs and foreign companies could not be audited at all.
2. The catalog offered a cin/name dropdown. `"name"` is not a value the API
   accepts, and the adapter ignored the field anyway.
3. `limit` defaulted to 50 against a maximum of 200, and `page` was never
   wired. One call costs ₹5 whatever the limit, so this paid full price for a
   quarter of one page. Reliance has 3,209 filings.
4. Summary lines were built with raw f-strings while the panel below them
   used the formatters — one screen showing "Incorporated 1973-05-08" above
   "08 May 1973".
"""

from __future__ import annotations

import re

import pytest

from app.config import Settings
from app.providers import filesure as fs
from app.providers import factsets as fx
from app.providers.base import Spend


class Recorder(fs.FileSureProvider):
    """Captures the request instead of making it."""

    def __init__(self):
        self.settings = Settings()
        self.spend = Spend()
        self.calls: list[tuple] = []

    def _call(self, method, path, *, paisa=0, params=None, **_kw):
        self.calls.append((method, path, params))

        class R:
            payload = {"data": {"cin": "X"}}
        return R()

    def _data(self, response):
        return response.payload["data"]


# =====================================================================
# 1 · Who can be audited
# =====================================================================

class TestIdentifierType:
    def test_no_id_type_is_sent_by_default(self):
        """THE fix. The provider's docs: "Optional. Tighter validation when
        set; auto-detect when omitted." Sending nothing is what lets an
        LLPIN through — pinning "cin" is what blocked it."""
        p = Recorder()
        p.company_master("ACK-2998")
        _, path, params = p.calls[0]
        assert path == "/v1/companies/ACK-2998"
        assert not params, f"idType should not be sent, got {params}"

    @pytest.mark.parametrize("ident", [
        "U21029MH2013PTC245119",   # CIN
        "ACK-2998",                # LLPIN — a real LLP identifier
        "F01234",                  # FCIN — foreign company
    ])
    def test_every_mca_identifier_reaches_the_provider_untouched(self, ident):
        """No local format guessing. MCA issues three kinds and the endpoint
        takes all three; deciding here which look valid would re-create the
        bug in a new place."""
        p = Recorder()
        p.company_master(ident)
        assert p.calls[0][1] == f"/v1/companies/{ident}"

    @pytest.mark.parametrize("kind", ["cin", "llpin", "fcin", "LLPIN", " Cin "])
    def test_a_caller_can_still_opt_into_strict_validation(self, kind):
        p = Recorder()
        p.company_master("X", kind)
        assert p.calls[0][2] == {"idType": kind.strip().lower()}

    def test_an_unknown_id_type_is_refused_without_a_call(self):
        """The provider answers `400 INVALID_ID_TYPE` — which costs a call to
        find out. "name" is the specific value the old dropdown offered."""
        p = Recorder()
        with pytest.raises(ValueError, match="not an identifier type"):
            p.company_master("X", "name")
        assert p.calls == [], "a call was made for an identifier type we know is invalid"

    def test_the_catalog_no_longer_offers_a_value_the_api_rejects(self):
        from app.catalog.checks import CHECKS_BY_ID
        opts = next(p for p in CHECKS_BY_ID["master"].params
                    if p.key == "idType").options
        assert "name" not in opts
        assert set(opts) - {"Auto-detect"} <= set(fs.FileSureProvider.ID_TYPES)


# =====================================================================
# 2 · How much of the record is read
# =====================================================================

class TestFilingsPaging:
    def test_the_catalog_asks_for_the_provider_maximum(self):
        """One call is ₹5 whether it returns 50 rows or 200. The old default
        of 50 paid full price for a quarter of the data."""
        from app.catalog.checks import CHECKS_BY_ID
        params = {p.key: p for p in CHECKS_BY_ID["filings"].params}
        assert params["limit"].default == "200"

    def test_page_is_reachable_at_all(self):
        """Filings are paginated and `page` was never wired, so page 1 was
        the only page that existed. Reliance has 3,209 filings."""
        from app.catalog.checks import CHECKS_BY_ID
        assert "page" in {p.key for p in CHECKS_BY_ID["filings"].params}

    def test_the_provider_accepts_a_page(self):
        import inspect
        assert "page" in inspect.signature(fs.FileSureProvider.filings).parameters


# =====================================================================
# 3 · How it reads
# =====================================================================

class TestListedFlag:
    @pytest.mark.parametrize("raw,shown", [
        ("Y", "Yes"), ("N", "No"), ("y", "Yes"), ("n", "No"),
        (True, "Yes"), (False, "No"), (None, None), ("", None),
    ])
    def test_mca_single_letter_flags_become_words(self, raw, shown):
        assert fx._yn(raw) == shown

    def test_n_does_not_become_yes(self):
        """The failure this guards: MCA sends "N" as a STRING, and every
        non-empty string is truthy. A plain boolean conversion renders a
        company that is NOT listed as "Yes"."""
        assert fx._yn("N") == "No"

    def test_an_unrecognised_value_is_shown_not_guessed(self):
        assert fx._yn("Unknown") == "Unknown"

    def test_the_listed_field_renders_as_a_word(self):
        blob = fx.master({"cin": "X", "listed": "Y"})
        listed = next(f for f in blob["fields"] if f["label"] == "Listed")
        assert listed["value"] == "Yes"


class TestSummaryLineFormatting:
    """The summary line and the panel below it must not disagree."""

    def test_no_summary_line_formats_money_or_dates_by_hand(self):
        """Every one of these was an f-string doing its own division or
        printing an ISO date, directly above a panel that formatted the same
        value properly."""
        src = open("app/services/runner.py").read()
        # the dispatch body only — the run-complete audit line legitimately
        # reports spend in paisa
        body = src[src.index("def _dispatch"):src.index("def _prior_raw")]
        assert "10_000_000" not in body, "money is still being divided inline"
        assert not re.search(r"\{facts\[.period_end.\]\}", body)
        assert not re.search(r"\{latest\.get\('dateOfFiling'\)\}", body)
