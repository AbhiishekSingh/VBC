"""Unit prices, pinned to the account's own pricing table.

Effective 24 Aug 2026. These constants were previously GUESSED, and were
wrong on eleven of the fourteen billable endpoints — in both directions.

The dangerous direction was the company unlock: 22000 against a real 33000.
`ensure_unlocked` compared the CONSTANT against the configured cap, so a
₹250 cap did not stop a ₹330 charge. It asked "is 22000 > 25000?", answered
no, and spent the money. A spend guard reading a stale local number is worse
than no guard at all, because it is believed.

So these tests do two things: pin every price, and prove the cap is now
enforced against the price the API QUOTES rather than anything in this repo.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.providers import filesure as fs


def test_prices_match_the_pricing_table():
    """₹1 = 100 paisa. Effective 24 Aug 2026."""
    assert fs.CHEAP_PAISA == 5             # ₹0.05
    assert fs.READ_PAISA == 500            # ₹5.00
    assert fs.FILINGS_REFRESH_PAISA == 500     # ₹5.00
    assert fs.DIRECTOR_UNLOCK_PAISA == 5_000   # ₹50
    assert fs.COMPANY_UPDATE_PAISA == 15_000   # ₹150
    assert fs.COMPANY_UNLOCK_PAISA == 33_000   # ₹330 — NOT 22000


def test_the_extraction_drilldown_is_cheaper_than_one_master_read():
    """A surprising shape, and worth stating so nobody 'optimises' it away.

    All three extraction steps together cost ₹0.15. One master read costs
    ₹5 — thirty-three times more. Financials are the cheap part of this
    API; the identity reads are the expensive part.
    """
    drilldown = fs.CHEAP_PAISA * 3
    assert drilldown == 15
    assert drilldown < fs.READ_PAISA


def test_default_caps_admit_exactly_one_real_unlock():
    settings = Settings()
    # Must ADMIT the real price, or every unlock is refused and the feature
    # is silently dead.
    assert fs.COMPANY_UNLOCK_PAISA <= settings.company_unlock_paisa_cap
    # ...but not by so much that a large price rise slips through.
    assert settings.company_unlock_paisa_cap < fs.COMPANY_UNLOCK_PAISA * 1.2
    assert settings.max_run_spend_paisa >= fs.COMPANY_UNLOCK_PAISA


# ---------------------------------------------------------------------
# The cap must follow the QUOTED price, not the constant
# ---------------------------------------------------------------------


class _Provider(fs.FileSureProvider):
    """Stubs the free status call so no HTTP or key is needed."""

    def __init__(self, settings, quoted_price):
        self.settings = settings
        self.spend = fs.Spend()
        self._quoted = quoted_price
        self.unlocked_calls = 0

    def unlock_status(self, cin):
        return fs.UnlockStatus(
            unlocked=False, unlocked_at=None, expires_at=None,
            unlock_price_paisa=self._quoted,
        )

    def unlock_company(self, cin):
        self.unlocked_calls += 1
        return fs.UnlockStatus(True, "now", "later", self._quoted)


def test_a_quoted_price_above_the_cap_refuses_to_spend():
    """The regression test for the real defect.

    A price rise to ₹400 must stop the run. Under the old code the check
    read COMPANY_UNLOCK_PAISA and never noticed.
    """
    settings = Settings(company_unlock_paisa_cap=35_000)
    provider = _Provider(settings, quoted_price=40_000)   # ₹400

    with pytest.raises(RuntimeError, match="above the configured cap"):
        provider.ensure_unlocked("CIN123")
    assert provider.unlocked_calls == 0, "must not have spent anything"


def test_the_quoted_price_wins_over_the_local_constant():
    """Even when the constant would have passed the cap.

    Constant says 33000 (under the 35000 cap). API quotes 40000 (over it).
    The API is right and the call must be refused — this is exactly the
    case the old code got wrong.
    """
    settings = Settings(company_unlock_paisa_cap=35_000)
    assert fs.COMPANY_UNLOCK_PAISA < settings.company_unlock_paisa_cap

    provider = _Provider(settings, quoted_price=40_000)
    with pytest.raises(RuntimeError):
        provider.ensure_unlocked("CIN123")


def test_the_real_price_is_permitted():
    settings = Settings(company_unlock_paisa_cap=35_000)
    provider = _Provider(settings, quoted_price=33_000)
    status, paid = provider.ensure_unlocked("CIN123")
    assert paid is True
    assert provider.unlocked_calls == 1


def test_a_missing_quote_falls_back_to_the_local_table():
    """Not every response carries unlockPrice. The cap must still apply."""
    settings = Settings(company_unlock_paisa_cap=10_000)   # below ₹330
    provider = _Provider(settings, quoted_price=None)
    with pytest.raises(RuntimeError, match="local price table"):
        provider.ensure_unlocked("CIN123")


def test_an_already_unlocked_company_never_pays_again():
    """The free GET is the whole point: no second ₹330."""
    settings = Settings()

    class _Unlocked(_Provider):
        def unlock_status(self, cin):
            return fs.UnlockStatus(True, "2026-08-01", "2027-08-01", 33_000)

    provider = _Unlocked(settings, quoted_price=33_000)
    status, paid = provider.ensure_unlocked("CIN123")
    assert paid is False
    assert provider.unlocked_calls == 0


# ---------------------------------------------------------------------
# Nothing is selected on the analyst's behalf
# ---------------------------------------------------------------------


def test_no_check_is_forced_on():
    """`always=True` was on `ustatus` alone. It is now on nothing.

    A forced check is a choice made for the analyst, and this product's
    whole premise is that the analyst retains the decision layer. It was
    justified as a cost control — but the control lives in
    CheckRunner._ensure_unlock, not in the selection, so forcing the
    checkbox bought no safety at all.
    """
    from app.catalog.checks import CHECKS

    forced = [c.id for c in CHECKS if c.always]
    assert forced == [], f"these checks cannot be deselected: {forced}"


def test_an_empty_selection_expands_to_nothing():
    """No hidden prerequisite creeps in behind an empty selection."""
    from app.catalog.checks import expand_selection

    assert expand_selection([]) == []


def test_the_free_unlock_check_is_still_reachable_when_wanted():
    """Deselectable, not deleted. It is still in the catalog."""
    from app.catalog.checks import CHECKS_BY_ID

    ustatus = CHECKS_BY_ID["ustatus"]
    assert ustatus.cost_paisa == 0, "the status GET is free"
    assert ustatus.always is False