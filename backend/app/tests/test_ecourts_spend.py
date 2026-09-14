"""eCourts money: the guard, the log, and running out.

THREE THINGS WERE WRONG AT ONCE
-------------------------------
1. `ecourts_check_paisa`, `_search_paisa` and `_case_paisa` were all **0**.
2. The adapter never called `guard_paid` at all.
3. Four paid endpoints — orders, case refresh, cause list, hearings batch —
   recorded no spend whatever.

Either of the first two alone disarms the guard: `guard_paid` returns
immediately at `paisa <= 0`, and a guard that is never invoked cannot fire.
Together they meant `VBC_ALLOW_PAID_CALLS=false` did not stop a single
eCourts call, and every run reported ₹0.00 for work that billed.

Nothing caught it because the existing tests ran against a mock transport
and never asked to spend. These tests ask.

WHAT THE PRICES ARE
-------------------
* case detail — **₹1.50**, quoted by the provider in a 402
* legal check — **₹99** PAYG / ₹33 subscription, published
* search, orders, refresh — **unconfirmed**, assumed at parity with case
  detail. A close-but-wrong number keeps the guard armed; 0 disarms it.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers import ecourts as ec
from app.providers.base import PaidCallRefused, ProviderOutOfCredits

#: The real shape. `ParseGuard` refuses a case record with no status —
#: "we could not tell if it is live" must never read as "nothing to see".
CASE = {"data": {"courtCaseData": {
    "caseNumber": "WP/4368/2022",
    "courtName": "High Court of Bombay",
    "caseStatus": "PENDING",
}}}


def provider(handler, **kw):
    base = dict(ecourts_api_key="eci_live_test", allow_paid_calls=True,
                http_max_retries=1)
    base.update(kw)
    return ec.EcourtsProvider(
        Settings(**base), client=httpx.Client(transport=httpx.MockTransport(handler)))


def ok(payload=CASE):
    return lambda request: httpx.Response(200, json=payload)


# =====================================================================
# 1 · The guard actually guards now
# =====================================================================

class TestTheGuard:
    def test_a_paid_call_is_refused_when_paid_calls_are_off(self):
        """The whole defect in one assertion. This passed before only
        because the price was 0 and the guard was never called."""
        p = provider(ok(), allow_paid_calls=False)
        with pytest.raises(PaidCallRefused):
            p.case_detail("HCBM010380062022")

    def test_the_refusal_happens_before_the_request(self):
        """A guard that fires after the money is gone is a log line."""
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(200, json=CASE)

        p = provider(handler, allow_paid_calls=False)
        with pytest.raises(PaidCallRefused):
            p.case_detail("HCBM010380062022")
        assert calls == []

    @pytest.mark.parametrize("call", [
        lambda p: p.case_detail("HCBM010380062022"),
        lambda p: p.case_search(parties="RELIANCE INDUSTRIES LIMITED"),
        lambda p: p.order_markdown("HCBM010380062022", "order-1.pdf"),
        lambda p: p.order_ai("HCBM010380062022", "order-1.pdf"),
        lambda p: p.order_download("HCBM010380062022", "order-1.pdf"),
        lambda p: p.case_refresh("HCBM010380062022"),
        lambda p: p.causelist_search("RELIANCE"),
    ])
    def test_every_billed_endpoint_is_covered(self, call):
        """Not just the three that happened to record spend. Orders, refresh
        and cause list billed silently for weeks."""
        p = provider(ok(CASE), allow_paid_calls=False)
        with pytest.raises(PaidCallRefused):
            call(p)

    def test_a_free_endpoint_is_not_guarded(self):
        """Enums, capabilities, court structure and available dates cost
        nothing. Gating them would make a disabled wallet look like a
        broken integration."""
        p = provider(ok({"data": {"enums": {"caseStatus": []}}}),
                     allow_paid_calls=False)
        assert p.enums() == {"caseStatus": []}          # no raise


# =====================================================================
# 2 · The spend is recorded, and only on success
# =====================================================================

class TestRecording:
    def test_a_case_detail_records_its_real_price(self):
        p = provider(ok())
        p.case_detail("HCBM010380062022")
        assert p.spend.paisa == 150          # ₹1.50, quoted by the provider

    def test_an_order_records_a_charge(self):
        """Each order is a separate billed call — which is the entire
        reason `ecourts_max_orders` exists."""
        p = provider(ok({"data": {"markdown": "ORDER", "signed": True}}))
        p.order_markdown("HCBM010380062022", "order-1.pdf")
        assert p.spend.paisa == 150

    def test_a_failed_call_records_nothing(self):
        """The guard runs before the request; the record runs after it
        succeeds. A 500 must not appear in the ledger as money spent."""
        p = provider(lambda r: httpx.Response(500, json={"error": "boom"}))
        with pytest.raises(Exception):
            p.case_detail("HCBM010380062022")
        assert p.spend.paisa == 0

    def test_the_endpoint_is_named_in_the_ledger(self):
        """So a bill can be reconciled against which call ran."""
        p = provider(ok())
        p.case_detail("HCBM010380062022")
        assert p.spend.calls[0]["endpoint"] == "ecourts.case"

    def test_the_legal_check_carries_the_expensive_price(self):
        """₹99, and by far the largest single call in the product."""
        assert Settings().ecourts_check_paisa == 9_900

    def test_no_ecourts_price_is_left_at_zero(self):
        """Zero is not a neutral placeholder here — it silently disarms
        `guard_paid`. Any new eCourts price must be set to something."""
        s = Settings()
        for field in ("ecourts_check_paisa", "ecourts_search_paisa",
                      "ecourts_case_paisa", "ecourts_order_paisa"):
            assert getattr(s, field) > 0, field


# =====================================================================
# 3 · Running out of credits
#
# A 402 is neither a provider outage nor a finding about the vendor. It is
# an account problem, and the row has to say so — "Check failed · HTTP 402"
# sent an hour into diagnosing a forty-paisa shortfall.
# =====================================================================

class TestOutOfCredits:
    PAYLOAD = {"error": {"code": "INSUFFICIENT_CREDITS",
                         "message": "Insufficient credits. Required: ₹1.50, "
                                    "Available: ₹1.10"}}

    def test_a_402_raises_its_own_error(self):
        p = provider(lambda r: httpx.Response(402, json=self.PAYLOAD))
        with pytest.raises(ProviderOutOfCredits):
            p.case_detail("HCBM010380062022")

    def test_it_says_nothing_was_charged(self):
        """Because nothing was. A refused call must not leave anyone
        wondering whether they paid for it."""
        p = provider(lambda r: httpx.Response(402, json=self.PAYLOAD))
        with pytest.raises(ProviderOutOfCredits, match="nothing was charged"):
            p.case_detail("HCBM010380062022")

    def test_it_names_the_remedy(self):
        p = provider(lambda r: httpx.Response(402, json=self.PAYLOAD))
        with pytest.raises(ProviderOutOfCredits, match="Top the account"):
            p.case_detail("HCBM010380062022")

    def test_it_is_not_treated_as_transient(self):
        """Retrying an empty wallet three times with backoff wastes eight
        seconds to be told the same thing."""
        assert ProviderOutOfCredits.transient is False

    def test_the_quoted_price_is_logged(self, caplog):
        """A 402 is the one moment a provider states its own price out
        loud. Several of ours are inferred, and an inferred price is a
        number nobody revisits — so it goes to the log at WARNING."""
        p = provider(lambda r: httpx.Response(402, json=self.PAYLOAD))
        with caplog.at_level("WARNING"):
            with pytest.raises(ProviderOutOfCredits):
                p.case_detail("HCBM010380062022")
        assert any("150 paisa" in r.getMessage() for r in caplog.records)

    def test_the_batch_bills_per_cnr_not_per_call(self):
        """`causelist/cnr/batch` charges per distinct CNR. Billing it as one
        request understates a fifty-case portfolio check by 49 charges."""
        p = provider(ok({"data": [{"cnr": "A", "hasCauselist": True}]}))
        p.cnr_causelist_batch(["MHSO070008712017", "MHMT010018352022",
                               "MHGO010008032025"])
        assert p.spend.paisa == 3 * 150

    def test_the_same_cnr_twice_is_charged_once(self):
        """Deduplicated before sending. The same case twice in a list is
        the same case, and paying twice for it buys nothing."""
        p = provider(ok({"data": []}))
        p.cnr_causelist_batch(["MHSO070008712017", "MHSO070008712017"])
        assert p.spend.paisa == 150

    def test_an_empty_batch_costs_nothing_and_never_calls(self):
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(200, json={"data": []})

        p = provider(handler)
        assert p.cnr_causelist_batch([])["checked"] == 0
        assert p.spend.paisa == 0
        assert calls == []

    def test_a_402_with_no_price_in_it_does_not_break(self):
        """The parser is a convenience. It must never be the thing that
        turns a handled error into a crash."""
        p = provider(lambda r: httpx.Response(402, json={"error": "no balance"}))
        with pytest.raises(ProviderOutOfCredits):
            p.case_detail("HCBM010380062022")