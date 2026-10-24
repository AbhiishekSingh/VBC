"""The nightly balance check, and the one thing it must never do.

FileSure publishes the wallet balance on a FREE endpoint, so there is no
reason to learn that it is empty from a failed run in front of a client.
It is read once a night, and if the wallet is spent the checks are marked
unavailable before the office opens.

THE DANGEROUS CASE IS NOT AN EMPTY WALLET. It is a payload this adapter
cannot read. If FileSure renames the balance field, the job finds no
number — and a missing number is not a zero. Treating it as one would
take a working provider offline for every user, every night, over a
schema change. This project has already been bitten by exactly that shape
of bug once: WhoisXML documents `createdDateNormalized` and returns
`createdDateISO8601`, and reading only the documented name produced a
silent None that flowed into a score.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db.models import AuditLog
from app.providers.base import ProviderOutOfCredits, ProviderUnavailable
from app.services import balance_watch, provider_state


# =====================================================================
# Finding the number
# =====================================================================

class TestReadBalance:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"walletBalancePaisa": 4190}, 4190),
            ({"balancePaisa": 0}, 0),
            ({"wallet": {"balancePaisa": 125000}}, 125000),
            ({"account": {"walletBalancePaisa": 77}}, 77),
            ({"meta": {"walletBalanceAfterPaisa": 44190}}, 44190),
            ({"walletBalancePaisa": "12,500"}, 12500),
            ({"walletBalancePaisa": -300}, -300),
        ],
    )
    def test_the_balance_is_found_wherever_it_is(self, payload, expected):
        assert balance_watch.read_balance_paisa(payload) == expected

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"spendPaisa": 1200},
            {"walletBalancePaisa": None},
            {"walletBalancePaisa": "not a number"},
            {"walletBalancePaisa": True},
        ],
    )
    def test_an_unreadable_payload_returns_none_not_zero(self, payload):
        """None means "could not tell". Zero means "empty". Never confuse them."""
        assert balance_watch.read_balance_paisa(payload) is None


# =====================================================================
# What the job does with it
# =====================================================================

class _FakeFileSure:
    """Stands in for the provider. Records that it was closed."""

    def __init__(self, result):
        self._result = result
        self.closed = False

    def account_usage(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def close(self):
        self.closed = True


@pytest.fixture
def patched(monkeypatch):
    """Swap the provider for a fake and hand back the one that was built."""
    built: list[_FakeFileSure] = []

    def install(result):
        def factory(settings, spend=None):
            fake = _FakeFileSure(result)
            built.append(fake)
            return fake

        monkeypatch.setattr(
            balance_watch.fs_mod, "FileSureProvider", factory, raising=True
        )
        return built

    return install


def _settings(**over) -> Settings:
    base = {
        "filesure_api_key": "test-key",
        "filesure_balance_floor_paisa": 500,
        "filesure_balance_low_paisa": 50_000,
    }
    base.update(over)
    return Settings(**base)


class TestNightlyCheck:
    def test_a_healthy_balance_changes_nothing(self, session, patched):
        patched({"walletBalancePaisa": 250_000})
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "none"
        assert report["balancePaisa"] == 250_000
        assert provider_state.open_outages(session) == {}

    def test_an_empty_wallet_blocks_the_provider(self, session, patched):
        patched({"walletBalancePaisa": 0})
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "blocked"
        outage = provider_state.open_outages(session)["filesure"]
        assert outage.source == "balance_check"
        assert "₹0.00" in outage.provider_message, (
            "the message has to say what the balance actually is — "
            "'unavailable' alone tells nobody what to do about it"
        )

    def test_a_low_but_workable_balance_warns_and_nothing_more(
        self, session, patched
    ):
        patched({"walletBalancePaisa": 20_000})  # ₹200: under warn, over floor
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "low"
        assert provider_state.open_outages(session) == {}, (
            "₹200 still runs forty ordinary reads; blocking it would be "
            "an outage we caused ourselves"
        )
        actions = [a.action for a in session.query(AuditLog).all()]
        assert "PROVIDER_BALANCE_LOW" in actions

    def test_a_topped_up_wallet_clears_an_existing_block(self, session, patched):
        provider_state.record_outage(
            session, "filesure", message="Insufficient balance",
            source="balance_check",
        )
        session.flush()

        patched({"walletBalancePaisa": 300_000})
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "cleared"
        assert provider_state.open_outages(session) == {}

    def test_the_usage_endpoint_refusing_us_is_itself_the_answer(
        self, session, patched
    ):
        patched(ProviderOutOfCredits("filesure: wallet is empty"))
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "blocked"
        stored = provider_state.open_outages(session)["filesure"]
        assert stored.provider_message == "filesure: wallet is empty", (
            "verbatim — the provider's sentence, not a classification of it"
        )

    # --- the two cases that must NOT block --------------------------

    def test_an_unreadable_payload_never_blocks_a_working_provider(
        self, session, patched
    ):
        """A renamed field is a bug in us, not an empty wallet in them."""
        patched({"usage": [{"endpoint": "/v1/company", "calls": 412}]})
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "unreadable"
        assert provider_state.open_outages(session) == {}
        actions = [a.action for a in session.query(AuditLog).all()]
        assert "PROVIDER_BALANCE_UNREADABLE" in actions, (
            "silence is the failure mode this project keeps meeting; the "
            "job must say loudly that it could not tell"
        )

    def test_a_network_failure_never_blocks_a_working_provider(
        self, session, patched
    ):
        patched(ProviderUnavailable("timed out"))
        report = balance_watch.check_filesure(session, _settings())
        session.flush()

        assert report["action"] == "unknown"
        assert provider_state.open_outages(session) == {}, (
            "one bad minute on somebody else's network must not take "
            "FileSure down for the whole firm until tomorrow night"
        )

    def test_an_unreadable_payload_does_not_clear_an_existing_block(
        self, session, patched
    ):
        provider_state.record_outage(session, "filesure", message="Insufficient balance")
        session.flush()

        patched({"nothing": "useful"})
        balance_watch.check_filesure(session, _settings())
        session.flush()

        assert "filesure" in provider_state.open_outages(session), (
            "not knowing the balance is not evidence it was paid"
        )

    def test_no_key_set_is_skipped_rather_than_blocked(self, session, patched):
        patched({"walletBalancePaisa": 0})
        report = balance_watch.check_filesure(
            session, _settings(filesure_api_key="")
        )
        session.flush()

        assert report["action"] == "skipped"
        assert provider_state.open_outages(session) == {}

    def test_the_client_is_always_closed(self, session, patched):
        built = patched(ProviderUnavailable("timed out"))
        balance_watch.check_filesure(session, _settings())
        assert built[0].closed is True
