"""One analyst meets the error. Nobody after them does.

WHAT THIS IS GUARDING
---------------------
We buy data from four outside services on prepaid accounts. When one runs
dry, every check against it fails the same way. Without a shared record
each analyst discovers that separately: the first from a failed run, and
so does the tenth, each having waited on a call that could not succeed,
with a client on the other side of it.

So the FIRST refusal is recorded and the rest are refused locally, free
and instantly, with the provider's own sentence attached.

Four things have to hold, and each has already been wrong at least once
somewhere in this file's history:

  1. The account-level exceptions must be CAUGHT. `ProviderOutOfCredits`
     is a subclass of `ProviderRejected`, and its handler sat after its
     parent's from the day it was written, so it never ran once. An empty
     wallet reported "Provider rejected the call" — exactly the wording
     whose absence cost an hour on a 40-paisa eCourts shortfall.
  2. Only 401/402/403 count. A 404 is about the company, a 429 passes on
     its own, a 5xx is the provider's bad afternoon. Treating any of them
     as an account failure lets one bad CIN kill fourteen live checks.
  3. The stored message is the PROVIDER'S, verbatim. WhoisXML returns an
     empty balance, a revoked key and a blocked IP behind one 403; a
     fixed message of ours sends the wrong person to the wrong place two
     times in three.
  4. The block must be able to END. Once nothing calls a provider,
     nothing can find out it works again — so a topped-up account would
     stay dark until somebody edited the database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import AuditLog, ProviderOutage
from app.providers.base import (
    ProviderAccountBlocked,
    ProviderOutOfCredits,
    ProviderRejected,
    ProviderUnavailable,
)
from app.services import provider_state
from app.services.runner import _provider_of


# =====================================================================
# 1. The exceptions are reachable at all
# =====================================================================

class TestExceptionsAreReachable:
    """The handler order bug, pinned so it cannot come back."""

    def test_out_of_credits_is_a_provider_rejected(self):
        # The fact that makes ordering matter. If this ever stops being
        # true the combined handler below needs revisiting.
        assert issubclass(ProviderOutOfCredits, ProviderRejected)
        assert issubclass(ProviderAccountBlocked, ProviderRejected)

    def test_a_combined_handler_catches_both_before_the_parent(self):
        for exc in (ProviderOutOfCredits("empty"), ProviderAccountBlocked("403")):
            try:
                raise exc
            except (ProviderOutOfCredits, ProviderAccountBlocked) as caught:
                assert caught is exc
            except ProviderRejected:  # pragma: no cover - the bug
                pytest.fail(
                    f"{type(exc).__name__} was caught by the parent handler; "
                    f"the subclass branch is unreachable again."
                )

    def test_the_handlers_are_ordered_correctly_in_the_runner(self):
        """Read the source, because import order cannot prove this.

        The previous version of this bug survived a code review and a
        comment directly above it claiming the order was right.
        """
        import inspect

        from app.services import runner

        source = inspect.getsource(runner.CheckRunner._run_one)
        account = source.index("ProviderOutOfCredits")
        parent = source.index("except ProviderRejected")
        assert account < parent, (
            "the account-level handler must come BEFORE its parent class, "
            "or Python matches the parent and it never runs"
        )

    def test_the_status_rides_on_the_exception(self):
        """Not parsed back out of the message.

        The message is the PROVIDER'S text. Reading "403" out of it would
        make our handling depend on their wording, which changes without
        notice and is not always in English.
        """
        from app.providers.base import ProviderError

        assert ProviderAccountBlocked("refused", status=403).status == 403
        assert ProviderOutOfCredits("empty", status=402).status == 402
        assert ProviderError("something").status is None

    def test_account_blocked_is_not_transient(self):
        # A retry cannot fix an empty wallet, and retrying one is how a
        # single refusal becomes a hundred.
        assert ProviderAccountBlocked.transient is False


# =====================================================================
# 2. Recording, refreshing and clearing
# =====================================================================

class TestRecording:
    def test_first_refusal_opens_an_outage(self, session):
        provider_state.record_outage(
            session, "whoisxml",
            message="Access restricted. Reasons: insufficient credits balance",
            http_status=403, check_id="whois", vendor_id=None,
        )
        session.flush()

        open_now = provider_state.open_outages(session)
        assert set(open_now) == {"whoisxml"}
        assert open_now["whoisxml"].http_status == 403

    def test_the_providers_own_words_are_stored_verbatim(self, session):
        """Not paraphrased, not classified, not replaced with 'out of credits'.

        This exact sentence covers three different causes needing three
        different people. Losing it loses the only thing that says which.
        """
        message = (
            "Access restricted. Reasons: insufficient credits balance, "
            "incorrect API key, or your IP address is not added to the IP "
            "allowlist"
        )
        provider_state.record_outage(session, "whoisxml", message=message)
        session.flush()

        stored = provider_state.open_outages(session)["whoisxml"]
        assert stored.provider_message == message

    def test_eight_failing_checks_produce_one_row(self, session):
        for check in ("whois", "whoishist", "ssl", "revwhois", "reputation"):
            provider_state.record_outage(
                session, "whoisxml", message="Access restricted.", check_id=check,
            )
        session.flush()

        rows = session.query(ProviderOutage).filter_by(provider="whoisxml").all()
        assert len(rows) == 1
        assert rows[0].detected_on_check == "whois", "the FIRST check is kept"

    def test_a_changed_message_is_refreshed_not_ignored(self, session):
        """"insufficient balance" then "incorrect API key" is new information."""
        provider_state.record_outage(
            session, "filesure", message="Insufficient balance", http_status=402,
        )
        provider_state.record_outage(
            session, "filesure", message="API key revoked", http_status=401,
        )
        session.flush()

        row = provider_state.open_outages(session)["filesure"]
        assert row.provider_message == "API key revoked"
        assert row.http_status == 401
        assert session.query(ProviderOutage).count() == 1

        actions = [a.action for a in session.query(AuditLog).all()]
        assert "PROVIDER_OUTAGE_OPENED" in actions
        assert "PROVIDER_OUTAGE_CHANGED" in actions

    def test_clearing_keeps_the_row_as_history(self, session):
        provider_state.record_outage(session, "ecourts", message="Low balance")
        session.flush()

        assert provider_state.clear_outage(session, "ecourts") is True
        session.flush()

        assert provider_state.open_outages(session) == {}
        closed = session.query(ProviderOutage).filter_by(provider="ecourts").one()
        assert closed.cleared_at is not None, "cleared, not deleted"
        assert closed.provider_message == "Low balance", (
            "how long a provider was down and what it said is the question "
            "asked after a client complains"
        )

    def test_clearing_nothing_is_not_an_error(self, session):
        assert provider_state.clear_outage(session, "finagg") is False

    def test_a_provider_can_be_blocked_again_after_clearing(self, session):
        """The partial unique index allows many CLOSED rows, one open.

        A plain unique index would pass the first time and fail the
        second — in the code path that only runs when something is
        already wrong, which is the worst place for a latent error.
        """
        provider_state.record_outage(session, "finagg", message="first")
        session.flush()
        provider_state.clear_outage(session, "finagg")
        session.flush()
        provider_state.record_outage(session, "finagg", message="second")
        session.flush()

        assert provider_state.open_outages(session)["finagg"].provider_message == "second"
        assert session.query(ProviderOutage).filter_by(provider="finagg").count() == 2


# =====================================================================
# 3. The block has to be able to end
# =====================================================================

class TestProbe:
    def test_a_fresh_outage_is_not_probed_immediately(self, session):
        provider_state.record_outage(session, "filesure", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)["filesure"]
        assert provider_state.due_for_probe(outage) is False

    def test_a_stale_outage_is_probed(self, session):
        provider_state.record_outage(session, "filesure", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)["filesure"]

        later = datetime.now(timezone.utc) + provider_state.PROBE_AFTER + timedelta(minutes=1)
        assert provider_state.due_for_probe(outage, now=later) is True

    def test_marking_a_probe_restarts_the_clock(self, session):
        provider_state.record_outage(session, "filesure", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)["filesure"]

        later = datetime.now(timezone.utc) + provider_state.PROBE_AFTER + timedelta(minutes=1)
        assert provider_state.due_for_probe(outage, now=later) is True

        provider_state.mark_probed(session, outage, now=later)
        session.flush()
        assert provider_state.due_for_probe(outage, now=later) is False, (
            "a provider that stays down must be probed once per window, "
            "not by every run once the first window has passed"
        )

        much_later = later + provider_state.PROBE_AFTER + timedelta(minutes=1)
        assert provider_state.due_for_probe(outage, now=much_later) is True, (
            "and it must be probed again one window later, or topping up "
            "the balance would never be noticed"
        )


# =====================================================================
# 4. Which checks a block actually covers
# =====================================================================

class TestProviderMapping:
    @pytest.mark.parametrize(
        "check_id,expected",
        [
            ("master", "filesure"),
            ("whois", "whoisxml"),
        ],
    )
    def test_paid_checks_map_to_their_account(self, check_id, expected):
        assert _provider_of(check_id) == expected

    def test_in_house_checks_can_never_be_blocked(self):
        """They spend nothing and call nobody, so there is no account to refuse."""
        assert _provider_of("duplicate") is None

    def test_an_unknown_check_maps_to_nothing(self):
        assert _provider_of("no-such-check") is None


# =====================================================================
# 5. What must NOT open an outage
# =====================================================================

class TestWhatIsNotAnAccountFailure:
    """One bad CIN must not take fourteen working checks down."""

    def test_a_plain_rejection_is_not_account_level(self):
        assert not isinstance(ProviderRejected("404"), ProviderAccountBlocked)
        assert not isinstance(ProviderRejected("404"), ProviderOutOfCredits)

    def test_unavailable_is_not_account_level(self):
        assert not isinstance(ProviderUnavailable("502"), ProviderRejected)

    def test_only_401_402_403_are_account_statuses(self):
        from app.providers.base import ACCOUNT_LEVEL_STATUSES

        assert ACCOUNT_LEVEL_STATUSES == {401, 402, 403}
        for status in (400, 404, 422, 429, 500, 502, 503):
            assert status not in ACCOUNT_LEVEL_STATUSES


# =====================================================================
# 6. The runner, end to end
# =====================================================================

from app.db.models import Vendor  # noqa: E402
from app.domain.types import CheckStatus  # noqa: E402
from app.services.runner import CheckRunner, Finding, RunResult  # noqa: E402
from app.tests.conftest import DEFAULT_CLIENT_ID  # noqa: E402


def _vendor(session, vendor_id: str) -> Vendor:
    vendor = Vendor(id=vendor_id, client_id=DEFAULT_CLIENT_ID,
                    name="Outage Test", domain="example.com", selected=[])
    session.add(vendor)
    session.flush()
    return vendor


class TestRunnerHoldsBlockedProviders:
    def test_checks_on_a_blocked_provider_never_leave_the_building(
        self, session, seeded
    ):
        provider_state.record_outage(
            session, "whoisxml",
            message="Access restricted. Reasons: insufficient credits balance",
            http_status=403,
        )
        session.flush()

        runner = CheckRunner(session)
        result = RunResult(vendor_id="OU0001", spend=runner.spend)
        allowed = runner._hold_blocked_providers(["whois", "ssl", "master"], result)

        assert allowed == ["master"], "the FileSure check is untouched"
        held = {f.check_id for f in result.findings}
        assert held == {"whois", "ssl"}

    def test_the_held_check_says_what_the_provider_said(self, session, seeded):
        message = (
            "Access restricted. Reasons: insufficient credits balance, "
            "incorrect API key, or your IP address is not added to the IP "
            "allowlist"
        )
        provider_state.record_outage(session, "whoisxml", message=message)
        session.flush()

        runner = CheckRunner(session)
        result = RunResult(vendor_id="OU0002", spend=runner.spend)
        runner._hold_blocked_providers(["whois"], result)

        finding = result.findings[0]
        assert finding.status is CheckStatus.UNAVAILABLE
        assert message in finding.detail
        assert "NOT a clean result" in finding.detail, (
            "rule 4: something that was not examined must never look like "
            "something that came back clean"
        )

    def test_one_check_per_blocked_provider_is_let_through_as_a_probe(
        self, session, seeded
    ):
        """Otherwise the block is permanent and topping up fixes nothing."""
        provider_state.record_outage(session, "whoisxml", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)["whoisxml"]
        outage.last_probe_at = datetime.now(timezone.utc) - timedelta(hours=2)
        session.flush()

        runner = CheckRunner(session)
        result = RunResult(vendor_id="OU0003", spend=runner.spend)
        allowed = runner._hold_blocked_providers(["whois", "ssl", "master"], result)

        assert allowed == ["whois", "master"], (
            "exactly one probe for the blocked provider — and the FileSure "
            "check, which was never blocked, goes through untouched"
        )
        assert [f.check_id for f in result.findings] == ["ssl"]

    def test_nothing_is_held_when_no_provider_is_blocked(self, session, seeded):
        runner = CheckRunner(session)
        result = RunResult(vendor_id="OU0004", spend=runner.spend)
        checks = ["whois", "ssl", "master"]

        assert runner._hold_blocked_providers(checks, result) == checks
        assert result.findings == []


class TestRunOneTagsTheFinding:
    """`_run_one` must mark the finding, because `run` reads it later.

    If the tag is lost here, nothing downstream opens an outage and the
    whole mechanism is silently inert — which is exactly how the
    unreachable-handler bug behaved for as long as it existed.
    """

    @pytest.mark.parametrize(
        "exc,expected_status",
        [
            (ProviderOutOfCredits("filesure: out of credits", status=402), 402),
            (ProviderAccountBlocked("whoisxml: HTTP 403 — Access restricted", status=403), 403),
        ],
    )
    def test_an_account_refusal_is_tagged(
        self, session, seeded, monkeypatch, exc, expected_status
    ):
        vendor = _vendor(session, "OU0020")
        runner = CheckRunner(session)
        monkeypatch.setattr(
            CheckRunner, "_dispatch",
            lambda *a, **k: (_ for _ in ()).throw(exc),
        )

        finding = runner._run_one(
            "whois", vendor, None, {}, None,
            RunResult(vendor_id=vendor.id, spend=runner.spend),
        )

        assert finding.status is CheckStatus.UNAVAILABLE
        assert finding.account_blocked == str(exc)
        assert finding.account_blocked_status == expected_status

    def test_an_ordinary_rejection_is_not_tagged(
        self, session, seeded, monkeypatch
    ):
        """A 404 on one company is not an account failure."""
        vendor = _vendor(session, "OU0021")
        runner = CheckRunner(session)
        monkeypatch.setattr(
            CheckRunner, "_dispatch",
            lambda *a, **k: (_ for _ in ()).throw(
                ProviderRejected("whoisxml: HTTP 404 on /whois")
            ),
        )

        finding = runner._run_one(
            "whois", vendor, None, {}, None,
            RunResult(vendor_id=vendor.id, spend=runner.spend),
        )

        assert finding.account_blocked is None


class TestRunnerSettlesProviderState:
    def test_an_account_refusal_opens_the_outage_after_the_pool_joins(
        self, session, seeded
    ):
        vendor = _vendor(session, "OU0010")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(
            Finding(
                "whois", CheckStatus.UNAVAILABLE, "Provider account out of credits",
                "", account_blocked="insufficient credits balance",
                account_blocked_status=403,
            )
        )

        runner._settle_provider_state(vendor, result)
        session.flush()

        outage = provider_state.open_outages(session)["whoisxml"]
        assert outage.provider_message == "insufficient credits balance"
        assert outage.detected_on_vendor == vendor.id

    def test_a_successful_call_clears_an_open_outage(self, session, seeded):
        """What makes topping up a balance sufficient on its own."""
        provider_state.record_outage(session, "whoisxml", message="empty")
        session.flush()

        vendor = _vendor(session, "OU0011")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(Finding("whois", CheckStatus.PASS, "ok", ""))

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert provider_state.open_outages(session) == {}

    def test_a_refusal_in_the_same_run_beats_a_success(self, session, seeded):
        """The refusal is the newer fact about the account.

        A free or cached endpoint answering proves nothing about whether
        the paid wallet has money in it.
        """
        vendor = _vendor(session, "OU0012")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.extend([
            Finding("whois", CheckStatus.PASS, "ok", ""),
            Finding("ssl", CheckStatus.UNAVAILABLE, "", "",
                    account_blocked="insufficient credits balance"),
        ])

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert "whoisxml" in provider_state.open_outages(session)

    def test_an_ordinary_failure_opens_nothing(self, session, seeded):
        """A 404 on one company must not kill every check on that provider."""
        vendor = _vendor(session, "OU0013")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(
            Finding("whois", CheckStatus.UNAVAILABLE, "Provider rejected the call",
                    "HTTP 404", error="HTTP 404")
        )

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert provider_state.open_outages(session) == {}

    def test_a_parse_gap_neither_opens_nor_clears(self, session, seeded):
        """The provider answered; WE could not read it.

        Clearing on it would be wrong — a parse gap says nothing about
        the account — and opening on it would blame the provider for our
        own defect.
        """
        provider_state.record_outage(session, "whoisxml", message="empty")
        session.flush()

        vendor = _vendor(session, "OU0014")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(
            Finding("whois", CheckStatus.UNAVAILABLE, "Response not understood", "")
        )

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert "whoisxml" in provider_state.open_outages(session)

    def test_in_house_findings_are_ignored_entirely(self, session, seeded):
        vendor = _vendor(session, "OU0015")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(Finding("duplicate", CheckStatus.PASS, "ok", ""))

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert provider_state.open_outages(session) == {}
