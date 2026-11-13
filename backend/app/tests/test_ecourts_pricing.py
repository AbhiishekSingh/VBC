"""Every billable eCourts call carries a price, in both places.

THE BUG THIS CLOSES. The catalogue carried no `cost_paisa` for any
eCourts check, so Step 2 told the analyst the whole family was free,
while `config.py` held ₹1.50 and ₹99 for the spend guard. Two numbers
for one thing, and the one a person reads was the wrong one.

Not cosmetic. With the catalogue price at zero the History ledger sums
to zero, which is how three provider accounts ran dry in the same week
with nothing on any screen counting down. A ledger fed by zeros cannot
warn anybody about anything.

The figures: ₹0.60 search and ₹99 legal check are published; ₹1.50 for
a case detail came from a 402 the provider showed us.
"""

from __future__ import annotations

from app.catalog.checks import CHECKS, CHECKS_BY_ID
from app.config import Settings

#: Calls that spend money. The rest — enums, capabilities, court
#: structure, available dates, the legal-check list — are documented as
#: free and must stay at zero, or the quote overstates the run.
BILLABLE = {
    "courtsearch": 60,
    "courthearing": 60,
    "casedetail": 150,
    "courtorders": 150,
    "courtorderai": 150,
    "causelist": 60,
    "caserefresh": 75,
    "court": 9_900,
}

FREE = {"courtcaps", "courtenums", "courtstructure", "courtdates", "courtchecks"}


class TestTheCatalogueIsPriced:
    def test_every_billable_check_has_its_price(self):
        for check_id, paisa in BILLABLE.items():
            assert CHECKS_BY_ID[check_id].cost_paisa == paisa, check_id

    def test_the_free_ones_stay_free(self):
        """They describe the API, not the vendor, and the docs say they
        cost nothing. Pricing them would overstate every run."""
        for check_id in FREE:
            assert CHECKS_BY_ID[check_id].cost_paisa == 0, check_id

    def test_no_ecourts_check_is_silently_unpriced(self):
        """A new eCourts check added without a price would reopen the
        hole this closes — free on screen, billed in fact."""
        known = BILLABLE.keys() | FREE
        unaccounted = sorted(
            c.id for c in CHECKS if c.provider == "ecourts" and c.id not in known
        )
        assert unaccounted == [], (
            "these eCourts checks are in neither list, so nobody has said "
            "whether they bill: " + ", ".join(unaccounted)
        )


class TestTheGuardAndTheScreenAgree:
    def test_search_matches_the_published_rate(self):
        """₹0.60 PAYG. Was 150 — a 2.5x guess, and the provider's own
        402 reads "Required: ₹0.60"."""
        assert Settings().ecourts_search_paisa == 60
        assert CHECKS_BY_ID["courtsearch"].cost_paisa == 60

    def test_case_detail_matches_the_402_we_were_shown(self):
        assert Settings().ecourts_case_paisa == 150
        assert CHECKS_BY_ID["casedetail"].cost_paisa == 150

    def test_the_legal_check_is_priced_at_ninety_nine_rupees(self):
        """The most expensive call on the platform, and it logged as
        free."""
        assert Settings().ecourts_check_paisa == 9_900
        assert CHECKS_BY_ID["court"].cost_paisa == 9_900

    def test_the_guard_can_actually_refuse_now(self):
        """`guard_paid()` returns immediately at paisa <= 0. At zero it
        was not a guard at all — it could not refuse anything."""
        for check_id in BILLABLE:
            assert CHECKS_BY_ID[check_id].cost_paisa > 0, check_id
