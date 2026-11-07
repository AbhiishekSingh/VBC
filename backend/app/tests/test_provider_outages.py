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
            session, "whoisxml", product="whois",
            message="Access restricted. Reasons: insufficient credits balance",
            http_status=403, check_id="whois", vendor_id=None,
        )
        session.flush()

        open_now = provider_state.open_outages(session)
        assert set(open_now) == {("whoisxml", "whois")}
        assert open_now[("whoisxml", "whois")].http_status == 403

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
        provider_state.record_outage(session, "whoisxml", product="whois", message=message)
        session.flush()

        stored = provider_state.open_outages(session)[("whoisxml", "whois")]
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

        row = provider_state.open_outages(session)[("filesure", "")]
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

        assert provider_state.open_outages(session)[("finagg", "")].provider_message == "second"
        assert session.query(ProviderOutage).filter_by(provider="finagg").count() == 2


# =====================================================================
# 3. The block has to be able to end
# =====================================================================

class TestProbe:
    def test_a_fresh_outage_is_not_probed_immediately(self, session):
        provider_state.record_outage(session, "filesure", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)[("filesure", "")]
        assert provider_state.due_for_probe(outage) is False

    def test_a_stale_outage_is_probed(self, session):
        provider_state.record_outage(session, "filesure", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)[("filesure", "")]

        later = datetime.now(timezone.utc) + provider_state.PROBE_AFTER + timedelta(minutes=1)
        assert provider_state.due_for_probe(outage, now=later) is True

    def test_marking_a_probe_restarts_the_clock(self, session):
        provider_state.record_outage(session, "filesure", message="empty")
        session.flush()
        outage = provider_state.open_outages(session)[("filesure", "")]

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


class TestNothingIsEverHeld:
    """THE HOLD IS GONE, 7 Nov 2026, and these tests exist to keep it
    gone.

    What it did: a check whose provider had recently refused anybody was
    refused LOCALLY — free, instant, with that provider's own sentence
    attached — so that one analyst met the error and nobody after them
    waited on a call that could not succeed.

    Why it was removed, on the product owner's instruction, with live
    evidence behind it. Gridlines refused ONE of its five products
    (`FORBIDDEN_ACCESS: Credential does not have access to this
    product`, on address-lookup) while prefill, digital-footprint and
    fetch-uan all returned 200 in the same second. The hold turned that
    into five dead checks on every later run, and kept them dead,
    because nothing was left to discover that four of them worked.

    Narrowing the scope fixed that instance. It does not fix the shape
    of the mistake: a cache of "this will fail" is a PREDICTION, and
    this platform's whole argument is that a prediction must never stand
    in for an examination.

    The asymmetry settles it. A refused call is rejected BEFORE billing
    — 401, 402 and 403 all charge nothing — so the hold bought latency
    and paid for it in checks that could not recover on their own.

    Outages are still recorded and still shown. See
    `TestRunnerSettlesProviderState` below, which is unchanged.
    """

    def test_a_blocked_provider_does_not_stop_its_own_checks(
        self, session, seeded
    ):
        provider_state.record_outage(
            session, "whoisxml", product="whois",
            message="Access restricted. Reasons: insufficient credits balance",
            http_status=403,
        )
        session.flush()

        runner = CheckRunner(session)
        try:
            result = RunResult(vendor_id="OU0001", spend=runner.spend)
            allowed = runner._hold_blocked_providers(
                ["whois", "ssl", "reput", "master"], result)
        finally:
            runner.close()

        assert allowed == ["whois", "ssl", "reput", "master"]
        assert result.findings == [], (
            "nothing may be pre-refused: a provider that said no to "
            "somebody else is a prediction, not an examination"
        )

    def test_an_empty_wallet_does_not_stop_them_either(
        self, session, seeded
    ):
        """The hardest case for this decision, and still the right
        answer. A 402 charges nothing, so the cost of asking again is a
        round trip — and the cost of NOT asking is a check that stays
        dead after the invoice is paid."""
        provider_state.record_outage(
            session, "filesure", product="",
            message="out of credits", http_status=402,
        )
        session.flush()

        runner = CheckRunner(session)
        try:
            result = RunResult(vendor_id="OU0002", spend=runner.spend)
            allowed = runner._hold_blocked_providers(
                ["master", "dirs", "charges"], result)
        finally:
            runner.close()

        assert allowed == ["master", "dirs", "charges"]

    def test_the_run_path_does_not_call_the_hold_at_all(self):
        """Read the source. Leaving the call in place with a no-op
        behind it would be one edit away from coming back silently."""
        import inspect

        from app.services import runner as runner_mod

        source = inspect.getsource(runner_mod.CheckRunner.run)
        assert "_hold_blocked_providers" not in source
        assert "RUN_NO_HOLD" in source, (
            "the run must record that it held nothing, so the audit log "
            "says why every check was attempted"
        )

    def test_the_outage_record_itself_is_untouched(self, session, seeded):
        """Recording is the half that survives. `/api/providers` still
        reports what is refusing us and why, in the provider's own
        words, so somebody can go and pay the invoice — it is
        information for a person now, not a gate in front of a call."""
        provider_state.record_outage(
            session, "finagg", product="", message="Forbidden",
            http_status=403,
        )
        session.flush()
        assert provider_state.open_outages(session)[("finagg", "")]


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

        outage = provider_state.open_outages(session)[("whoisxml", "whois")]
        assert outage.provider_message == "insufficient credits balance"
        assert outage.detected_on_vendor == vendor.id

    def test_a_successful_call_clears_an_open_outage(self, session, seeded):
        """What makes topping up a balance sufficient on its own."""
        provider_state.record_outage(session, "whoisxml", product="whois", message="empty")
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
        # BOTH findings must be on the SAME pool for this to be the
        # conflict being tested. `whois` and `ssl` are different WhoisXML
        # products and can legitimately disagree — that is the point of
        # the change, not a contradiction.
        result.findings.extend([
            Finding("master", CheckStatus.PASS, "ok", ""),
            Finding("filings", CheckStatus.UNAVAILABLE, "", "",
                    account_blocked="out of credits"),
        ])

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert ("filesure", "") in provider_state.open_outages(session)

    def test_two_products_of_one_provider_can_disagree(self, session, seeded):
        """A 403 on one WhoisXML product and a 200 on another is NORMAL.

        It is what the live account actually did on 6 Nov 2026, and the
        two facts must be recorded independently rather than one
        overwriting the other.
        """
        vendor = _vendor(session, "OU0012b")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.extend([
            Finding("ssl", CheckStatus.PASS, "ok", ""),
            Finding("whois", CheckStatus.UNAVAILABLE, "", "",
                    account_blocked="Access restricted."),
        ])

        runner._settle_provider_state(vendor, result)
        session.flush()

        open_now = provider_state.open_outages(session)
        assert ("whoisxml", "whois") in open_now
        assert ("whoisxml", "ssl") not in open_now

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
        provider_state.record_outage(session, "whoisxml", product="whois", message="empty")
        session.flush()

        vendor = _vendor(session, "OU0014")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(
            Finding("whois", CheckStatus.UNAVAILABLE, "Response not understood", "")
        )

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert ("whoisxml", "whois") in provider_state.open_outages(session)

    def test_in_house_findings_are_ignored_entirely(self, session, seeded):
        vendor = _vendor(session, "OU0015")
        runner = CheckRunner(session)
        result = RunResult(vendor_id=vendor.id, spend=runner.spend)
        result.findings.append(Finding("duplicate", CheckStatus.PASS, "ok", ""))

        runner._settle_provider_state(vendor, result)
        session.flush()

        assert provider_state.open_outages(session) == {}


# =====================================================================
# 7. AN ENTITLEMENT REFUSAL MUST NOT TAKE DOWN WHAT STILL ANSWERS
# =====================================================================

class TestProductScopedRefusals:
    """Observed live on 7 Nov 2026, one Gridlines run, one key, one
    second:

        /profile-api/mobile/address-lookup      403
        /epfo-api/fetch-uan                     200
        /profile-api/mobile/prefill             200
        /profile-api/mobile/digital-footprint   200

    with the body `FORBIDDEN_ACCESS: Credential does not have access to
    this product`. Recorded account-wide, that single refusal held all
    five person checks on every later run — the platform causing a
    wider outage than the one it exists to prevent. Same failure the
    WhoisXML pool split was built to stop, not applied here until it
    happened in production.
    """

    def test_a_403_is_scoped_to_the_product_that_was_refused(self):
        from app.services.runner import _outage_scope

        assert _outage_scope("personaddr", 403) == ("gridlines", "personaddr")

    def test_an_empty_wallet_still_blocks_the_whole_account(self):
        """A 402 really does affect every product, and discovering that
        five times over is the failure the shared record exists for."""
        from app.services.runner import _outage_scope

        assert _outage_scope("personaddr", 402) == ("gridlines", "")
        assert _outage_scope("prefill", 401) == ("gridlines", "")

    def test_whoisxml_is_untouched_by_this(self):
        """Its 403 covers an empty balance, a revoked key AND a blocked
        IP — all genuinely account-wide — so it is deliberately not in
        the product-scoped set and keeps its pools the other way."""
        from app.services.runner import _outage_scope

        assert _outage_scope("whois", 403) == ("whoisxml", "whois")
        assert _outage_scope("ssl", 403) == ("whoisxml", "ssl")

    def test_the_refused_product_is_the_only_check_covered(self):
        from app.services.runner import _checks_in_scope

        assert _checks_in_scope("gridlines", "personaddr") == ["personaddr"]

    def test_an_account_wide_gridlines_outage_still_covers_all_five(self):
        from app.services.runner import _checks_in_scope

        assert set(_checks_in_scope("gridlines", "")) == {
            "prefill", "footprint", "personaddr", "epfomember", "emphistory",
        }

    def test_the_refused_check_IS_still_held(self):
        """The other half. Scoping it narrowly must not mean nothing
        holds it — a check that cannot run has to be refused locally,
        free, rather than paying to be told again."""
        from app.services.runner import _hold_scopes

        assert ("gridlines", "personaddr") in _hold_scopes("personaddr")
        assert ("gridlines", "") in _hold_scopes("personaddr")

    def test_the_scope_still_decides_WHAT_IS_REPORTED(self, session, seeded):
        """Scoping survives the removal of the hold, for a different
        job. Nothing is blocked from running any more, but
        `/api/providers` still has to name the checks a refusal covers
        so Step 2 and the Step 3 dialog warn on exactly the right rows —
        and not on four that are answering."""
        provider_state.record_outage(
            session, "gridlines", product="personaddr",
            message="gridlines: HTTP 403 — FORBIDDEN_ACCESS: Credential "
                    "does not have access to this product.",
            http_status=403,
        )
        session.flush()

        outage = provider_state.open_outages(session)[("gridlines", "personaddr")]
        assert outage.http_status == 403
        from app.services.runner import _checks_in_scope

        assert _checks_in_scope("gridlines", "personaddr") == ["personaddr"]

    def test_a_refusal_on_one_product_never_stops_the_other_four(
        self, session, seeded
    ):
        """The case that prompted all of this, asserted end to end."""
        provider_state.record_outage(
            session, "gridlines", product="personaddr",
            message="FORBIDDEN_ACCESS", http_status=403,
        )
        session.flush()

        five = ["prefill", "footprint", "personaddr", "epfomember",
                "emphistory"]
        runner = CheckRunner(session)
        try:
            result = RunResult(vendor_id="OU0100", spend=runner.spend)
            allowed = runner._hold_blocked_providers(five, result)
        finally:
            runner.close()

        # ALL FIVE, the refused one included: it is allowed to try again,
        # which is the only way anybody ever learns the entitlement was
        # granted.
        assert allowed == five
        assert result.findings == []
