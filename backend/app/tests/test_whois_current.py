"""The plain WHOIS API — written against a real response, not the docs.

Wired on 11 Nov 2026 because the Domain Research Suite subscription
lapsed: `whois` and `rwhois` were returning 403 for insufficient credits
while this product answered 200 on the same key in the same minute. One
credit against WHOIS History's fifty.

IT IS NOT A REPLACEMENT, and most of what is asserted here exists to
keep that honest. History answers "has the registrant changed, and
when"; this answers "who holds it now, and how old is it". A screen that
let the second pass for the first would turn an absent finding into a
reassuring one.

Three quirks drive these tests, and every one of them came from reading
an actual response:

  * `estimatedDomainAge` is in DAYS. Read as years it is a thirty-fold
    error, in the direction of reassurance.
  * `registryData` carries no registrant; the populated block is at the
    top level, from the registrar.
  * `domainAvailability: "UNAVAILABLE"` means REGISTERED.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers.whoisxml import WhoisXmlProvider
from app.providers import factsets as fx
from app.tests.fixtures_whois import (
    WHOIS_LIVE,
    WHOIS_UNREGISTERED,
    WHOIS_YOUNG_AND_PRIVATE,
)


def _provider(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "whoisserver/WhoisService" in str(request.url)
        return httpx.Response(200, json=payload)

    return WhoisXmlProvider(
        settings=Settings(whoisxml_api_key="wx_x", allow_paid_calls=True,
                          http_max_retries=1, http_backoff_base_seconds=0.001),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


class TestTheParser:
    def test_age_is_read_as_days_not_years(self):
        """`estimatedDomainAge: 11022` is thirty years, not eleven
        thousand. Reading the unit wrong makes a new domain look
        ancient, which is the direction that does damage."""
        out = _provider(WHOIS_LIVE).whois_current("example-dairy.com")
        assert out["age_days"] == 11022

        blob = fx.whois_current(out)
        age = next(s for s in blob["stats"] if s["label"] == "Domain age")
        assert age["value"] == "30.2 yrs"

    def test_the_registrant_is_read_from_the_tier_that_has_one(self):
        """`registryData` has no registrant block at all. A parser
        reading the registry tier finds nothing on a domain whose
        holder is right there at the top level."""
        out = _provider(WHOIS_LIVE).whois_current("example-dairy.com")
        assert out["registrant_name"] == "EXAMPLE DAIRY COOPERATIVE"
        assert out["registrant_email"] == "registrant@example.invalid"
        assert out["registrant_country"] == "INDIA"

    def test_dates_and_registrar_survive(self):
        out = _provider(WHOIS_LIVE).whois_current("example-dairy.com")
        assert out["created"].startswith("1996-09-07")
        assert out["expires"].startswith("2027-09-06")
        assert out["registrar"] == "Example Registrar Ltd."
        assert out["name_servers"] == ["ns1.example-dns.com", "ns2.example-dns.com"]

    def test_UNAVAILABLE_means_registered(self):
        """The word collides head-on with this product's own
        vocabulary, where `unavailable` is a CheckStatus meaning "we
        could not examine this". Translated at the provider so the
        collision can never reach a screen."""
        registered = _provider(WHOIS_LIVE).whois_current("example-dairy.com")
        assert registered["registered"] is True

        free = _provider(WHOIS_UNREGISTERED).whois_current("example-nothing-here.com")
        assert free["registered"] is False

    def test_masking_is_carried_through_as_stated_by_the_source(self):
        out = _provider(WHOIS_LIVE).whois_current("example-dairy.com")
        assert out["masked"] is True
        assert out["data_error"] == "MASKED_WHOIS_DATA"


class TestWhatTheScreenIsTold:
    def test_the_lede_says_this_is_not_a_history(self):
        """The one misreading that matters: a snapshot presented where
        a reader expects ownership changes."""
        blob = fx.whois_current(
            _provider(WHOIS_LIVE).whois_current("example-dairy.com"))
        assert "today" in blob["lede"].lower()
        assert "changed hands" in blob["lede"] or "changed" in blob["lede"]

    def test_redaction_is_flagged_beside_the_registrant(self):
        """A registrant name arrives WITH MASKED_WHOIS_DATA, which is
        not a contradiction — the registrar's copy survived the
        registry's redaction. The reader is entitled to know the name
        is not registry-verified."""
        blob = fx.whois_current(
            _provider(WHOIS_LIVE).whois_current("example-dairy.com"))
        labels = [f["label"] for f in blob.get("flags") or []]
        assert any("redacted" in lbl.lower() for lbl in labels)

    def test_a_young_domain_is_flagged_and_NOT_called_adverse(self):
        """A company incorporated last year has a domain registered
        last year. The flag invites the comparison; it does not make
        the finding."""
        blob = fx.whois_current(
            _provider(WHOIS_YOUNG_AND_PRIVATE).whois_current("example-newco.in"))
        young = [f for f in blob["flags"] if "last year" in f["label"]]
        assert len(young) == 1
        assert young[0]["level"] == "warn"
        assert "incorporation date" in young[0]["detail"]

    def test_the_availability_word_never_reaches_the_fields(self):
        blob = fx.whois_current(
            _provider(WHOIS_LIVE).whois_current("example-dairy.com"))
        rendered = str(blob)
        assert "UNAVAILABLE" not in rendered
        assert any(f["label"] == "Registered now" and f["value"] == "Yes"
                   for f in blob["fields"])


class TestTheCheckItself:
    def test_it_is_in_the_catalog_at_one_credit(self):
        from app.catalog.checks import CHECKS_BY_ID

        check = CHECKS_BY_ID["dwhois"]
        assert check.credits == 1
        assert check.cost_paisa == 0
        assert check.provider == "whoisxml"

    def test_it_feeds_no_scan_parameter(self):
        """`whois` feeds S3. Two checks writing one parameter is a race
        whose winner depends on dispatch order, and the thing that moves
        is a client-facing number."""
        from app.catalog.checks import CHECKS_BY_ID

        assert CHECKS_BY_ID["dwhois"].feeds == ()
        assert "S3" in CHECKS_BY_ID["whois"].feeds

    def test_its_name_does_not_promise_history(self):
        from app.catalog.checks import CHECKS_BY_ID

        name = CHECKS_BY_ID["dwhois"].name.lower()
        assert "history" not in name
        assert "NOT a history" in CHECKS_BY_ID["dwhois"].note
