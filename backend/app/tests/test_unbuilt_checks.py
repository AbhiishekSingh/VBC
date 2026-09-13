"""The five checks that were catalogued but never wired.

`dresolve`, `dcontact`, `download`, `frefresh` and `refresh` were selectable
in the UI and fell through to a generic "no runner is wired" SKIP — which the
findings screen renders as **Not applicable**. In an audit product that is the
wrong sentence: "does not apply to this vendor" and "we never built it" are
different facts, and the first is a clearance the second has not earned.

Two of them are also the most expensive calls in the system (₹150 and ₹5, both
with provider-side cooldowns that bill on request and serve the cache). So the
tests that matter most here are the ones proving money is NOT spent.

No database and no network: the provider is stubbed and the session is a
double, the same shape `test_pricing.py` uses.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.domain.types import CheckStatus
from app.providers.base import PaidCallRefused, Spend
from app.services.runner import CheckRunner, Finding


# =====================================================================
# Doubles
# =====================================================================

class FakeVendor:
    id = "V1"
    name = "Acme Traders"
    legal_name = "Acme Traders Private Limited"
    cin = "U21029MH2013PTC245119"
    domain = "acme.in"
    website = "https://acme.in"
    gst = None
    selected: list[str] = []


class FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *_args, **_kw):
        return self

    def one_or_none(self):
        return self._row


class FakeSession:
    """Returns one stored VendorCheck row, or none."""

    def __init__(self, row=None):
        self._row = row
        self.added: list = []

    def query(self, *_args):
        return FakeQuery(self._row)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


class FakeRow:
    def __init__(self, raw):
        self.raw_response = raw


class FakeFileSure:
    """Records every call so a test can assert money was not spent."""

    def __init__(self, **returns):
        self.calls: list[str] = []
        self._returns = returns

    def _record(self, name, value=None):
        self.calls.append(name)
        return self._returns.get(name, value)

    def resolve_director(self, query, *, limit=10):
        return self._record("resolve_director", [])

    def director_contact(self, din):
        return self._record("director_contact", {"email": None, "mobile": None})

    def ensure_director_unlocked(self, din):
        self.calls.append("ensure_director_unlocked")
        return {}, True

    def download_filing(self, cin, filing_id):
        return self._record("download_filing", b"")

    def refresh_filings(self, cin):
        return self._record("refresh_filings", {})

    def trigger_update(self, cin):
        return self._record("trigger_update", {"status": "pending"})

    def update_status(self, cin):
        return self._record("update_status", {"status": "completed"})

    def close(self):
        pass


def make_runner(session=None, **provider_returns) -> tuple[CheckRunner, FakeFileSure]:
    settings = Settings(filesure_api_key="fsk_test_x")
    runner = CheckRunner.__new__(CheckRunner)
    runner.session = session or FakeSession()
    runner.settings = settings
    runner.spend = Spend()
    provider = FakeFileSure(**provider_returns)
    runner.filesure = provider
    runner.whoisxml = runner.archive = runner.finagg = runner.ecourts = None
    return runner, provider


def dispatch(runner, check_id, inputs=None, prior=None, cin=FakeVendor.cin) -> Finding:
    return runner._dispatch(
        check_id, FakeVendor(), cin, inputs or {}, None, None, prior or {},
    )


def hours_ago(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=n)).isoformat()


def flags_of(finding: Finding) -> list[str]:
    return [f["label"] for f in (finding.facts or {}).get("flags", [])]


# =====================================================================
# The regression this file exists to prevent
# =====================================================================

def test_every_configured_check_has_a_runner():
    """A catalogued check with no runner records SKIP — "Not applicable" —
    which is a clearance it has not earned. This failed for five checks."""
    from app.catalog.checks import CHECKS
    import app.services.runner as runner_mod
    import inspect as _inspect

    source = _inspect.getsource(runner_mod)
    wired = set(re.findall(r'check_id == "([a-z]+)"', source))
    for group in re.findall(r"check_id in \(([^)]*)\)", source):
        wired |= set(re.findall(r'"([a-z]+)"', group))

    missing = [c.id for c in CHECKS if c.is_configured and c.id not in wired]
    assert not missing, f"catalogued but never built: {missing}"


# =====================================================================
# Money that must not be spent
# =====================================================================

class TestCooldownsRefuseBeforePaying:
    """Both refresh endpoints bill on REQUEST and serve the cache while they
    are cooling down. A cooldown read from the response is a cooldown
    discovered after the money is gone."""

    def test_company_update_is_refused_inside_the_48_hour_window(self):
        session = FakeSession(FakeRow({"_fetched_at": hours_ago(2)}))
        runner, provider = make_runner(session)
        with pytest.raises(PaidCallRefused) as exc:
            dispatch(runner, "refresh")
        assert "₹150" in str(exc.value)
        assert provider.calls == [], "the ₹150 call was made anyway"

    def test_company_update_runs_once_the_window_has_lifted(self):
        session = FakeSession(FakeRow({"_fetched_at": hours_ago(72)}))
        runner, provider = make_runner(
            session, trigger_update={"status": "completed"})
        finding = dispatch(runner, "refresh")
        assert finding.status is CheckStatus.PASS
        assert "trigger_update" in provider.calls

    def test_the_providers_own_cooldown_stamp_is_preferred(self):
        """`cooldownUntil` is what the source said. It beats our arithmetic."""
        until = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        session = FakeSession(FakeRow({"_fetched_at": hours_ago(99),
                                       "cooldownUntil": until}))
        runner, provider = make_runner(session)
        with pytest.raises(PaidCallRefused):
            dispatch(runner, "refresh")
        assert provider.calls == []

    def test_an_unparseable_cooldown_stamp_does_not_block_forever(self):
        """A corrupt stamp must not make the check permanently unrunnable."""
        session = FakeSession(FakeRow({"cooldownUntil": "not a date",
                                       "_fetched_at": hours_ago(99)}))
        runner, provider = make_runner(
            session, trigger_update={"status": "completed"})
        assert dispatch(runner, "refresh").status is CheckStatus.PASS

    def test_filings_refresh_is_refused_inside_its_six_hour_window(self):
        session = FakeSession(FakeRow({"_fetched_at": hours_ago(1)}))
        runner, provider = make_runner(session)
        with pytest.raises(PaidCallRefused) as exc:
            dispatch(runner, "frefresh")
        assert "₹5" in str(exc.value)
        assert provider.calls == []

    def test_a_first_run_is_never_blocked(self):
        runner, provider = make_runner(FakeSession(None),
                                       refresh_filings={"status": "queued"})
        assert dispatch(runner, "frefresh").status is CheckStatus.PASS


class TestBilledButNotRefreshed:
    def test_a_cached_refresh_is_not_reported_as_a_refresh(self):
        """`fromCache: true` means billed and served stale. Reporting that as
        success is how a report claims data is newer than it is."""
        runner, _ = make_runner(
            FakeSession(None),
            refresh_filings={"fromCache": True, "status": "ok"})
        finding = dispatch(runner, "frefresh")
        assert finding.status is CheckStatus.WARN
        assert finding.value == "Served from cache"
        assert "Billed, but nothing was refreshed" in flags_of(finding)

    def test_a_real_refresh_passes_clean(self):
        runner, _ = make_runner(FakeSession(None),
                                refresh_filings={"fromCache": False})
        finding = dispatch(runner, "frefresh")
        assert finding.status is CheckStatus.PASS
        assert not flags_of(finding)


class TestAsyncUpdateHonesty:
    def test_a_job_still_running_is_not_reported_as_refreshed(self):
        """The ₹150 call returns `pending` and the data is NOT fresh yet.
        Reading master data now returns the stale values just paid to
        replace."""
        settings_budget = 0.0
        runner, _ = make_runner(FakeSession(None),
                                trigger_update={"status": "pending"},
                                update_status={"status": "pending"})
        runner.settings = Settings(filesure_update_poll_budget_seconds=settings_budget)
        finding = dispatch(runner, "refresh")
        assert finding.status is CheckStatus.WARN
        assert "Charged and still running" in flags_of(finding)
        assert "re-run the company master check" in finding.detail.lower()

    def test_a_completed_job_says_so(self):
        runner, _ = make_runner(FakeSession(None),
                                trigger_update={"status": "completed"})
        finding = dispatch(runner, "refresh")
        assert finding.status is CheckStatus.PASS
        assert "Charged and still running" not in flags_of(finding)


# =====================================================================
# dresolve — the free red flag
# =====================================================================

class TestDirectorResolve:
    def test_an_implausible_board_count_is_flagged_but_not_adverse(self):
        """The mass-director pattern. A busy professional director and a
        rented signature look identical from a count, so this raises a flag
        and never a status."""
        runner, _ = make_runner(FakeSession(None), resolve_director=[
            {"din": "00001", "name": "A Nominee", "totalDirectorshipCount": 47},
        ])
        finding = dispatch(runner, "dresolve", {"dresolve": {"q": "A Nominee"}})
        assert "Unusually high directorship count" in flags_of(finding)
        assert finding.status is not CheckStatus.FAIL

    def test_an_ordinary_director_raises_nothing(self):
        runner, _ = make_runner(FakeSession(None), resolve_director=[
            {"din": "00002", "name": "R Sharma", "totalDirectorshipCount": 2},
        ])
        finding = dispatch(runner, "dresolve", {"dresolve": {"q": "R Sharma"}})
        assert finding.status is CheckStatus.PASS
        assert not flags_of(finding)

    def test_no_match_is_a_gap_not_a_clearance(self):
        runner, _ = make_runner(FakeSession(None), resolve_director=[])
        finding = dispatch(runner, "dresolve", {"dresolve": {"q": "Nobody"}})
        assert finding.status is CheckStatus.WARN
        assert "not a clearance" in finding.detail

    def test_a_blank_name_never_reaches_the_provider(self):
        runner, provider = make_runner(FakeSession(None))
        finding = dispatch(runner, "dresolve", {"dresolve": {"q": "  "}})
        assert finding.status is CheckStatus.SKIPPED_MISSING_INPUT
        assert provider.calls == []


# =====================================================================
# dresolve, against what the endpoint actually sends
#
# The fixtures above use `name` and `totalDirectorshipCount`, and passed
# for a year while the live check rendered a column of DINs beside four
# columns of dashes. The endpoint sends `fullName`, `status`, `companies`
# and `dinAllocationDate`. These tests use the real keys.
# =====================================================================

#: Trimmed from the live response for "Mukesh Dhirubhai Ambani" — four
#: DINs on one name, which is the whole reason this check exists.
AMBANI = [
    {"din": "00001691", "fullName": "MUKESH DHIRUBHAI AMBANI", "status": "Lapsed",
     "totalDirectorshipCount": 0, "companies": [],
     "matchScore": 1736172819525404700},
    {"din": "00001695", "fullName": "MUKESH DHIRUBHAI AMBANI", "status": "Approved",
     "totalDirectorshipCount": 10, "dinAllocationDate": "05/25/2006",
     "companies": ["SHIVANGI COMMERCIALS LLP", "RELIANCE INDUSTRIES LIMITED",
                   "JIO PLATFORMS LIMITED", "RELIANCE RETAIL VENTURES LIMITED",
                   "RELIANCE STRATEGIC BUSINESS VENTURES LIMITED"],
     "matchScore": 1736172819525404700},
    {"din": "02366382", "fullName": "MUKESH DHIRUBHAI AMBANI", "status": "Lapsed",
     "totalDirectorshipCount": 0, "companies": []},
    {"din": "07626087", "fullName": "MUKESH DHIRUBHAI AMBANI", "status": "Lapsed",
     "totalDirectorshipCount": 0, "companies": []},
]


def ambani_table():
    from app.providers.factsets import director_candidates
    return director_candidates(AMBANI)["table"]


def cell(table, din, key):
    return next(r[key] for r in table["rows"] if r["din"] == din)


class TestDirectorResolveRealKeys:
    def test_the_name_is_read(self):
        assert cell(ambani_table(), "00001695", "name") == "MUKESH DHIRUBHAI AMBANI"

    def test_the_companies_are_read(self):
        """The user's report, in one assertion: "it's not showing company's
        name … which is important thing". Four identical names and four
        DINs are not a result; the companies are what tells you which
        Mukesh Ambani this is."""
        assert "RELIANCE INDUSTRIES LIMITED" in cell(ambani_table(), "00001695", "companies")

    def test_a_long_list_is_truncated_with_a_count(self):
        """A conglomerate director holds dozens. The count column already
        says how many, so the cell shows the first few and how many more."""
        assert "and 1 more" in cell(ambani_table(), "00001695", "companies")

    def test_companies_may_arrive_as_objects(self):
        """Some accounts get `[{"name": …, "cin": …}]` instead of plain
        strings. Joining blind raised `TypeError: expected str instance,
        dict found` — and a parser that crashes is worse than the blank
        column it was written to fix, because the call has already been
        paid for and the whole check dies with it."""
        rich = [dict(c, companies=[{"name": n, "cin": "X"} for n in c["companies"]])
                for c in AMBANI]
        from app.providers.factsets import director_candidates
        table = director_candidates(rich)["table"]
        assert "RELIANCE INDUSTRIES LIMITED" in cell(table, "00001695", "companies")

    def test_the_lapsed_dins_are_named_as_lapsed(self):
        assert cell(ambani_table(), "00001691", "status") == "Lapsed"

    def test_the_allocation_date_is_read_as_month_day_year(self):
        """FileSure sends slashed dates MM/DD/YYYY. Read as DD/MM this
        would be the 5th of an impossible 25th month, or silently the
        wrong date on any day under 13."""
        assert cell(ambani_table(), "00001695", "allocated") == "25 May 2006"

    def test_the_one_active_din_is_called_out(self):
        """Three lapsed and one approved is an answerable question. Stated,
        not left for the reader to work out from the table."""
        from app.providers.factsets import director_candidates
        flags = director_candidates(AMBANI)["flags"]
        assert any("00001695" in f["label"] for f in flags)

    def test_the_callout_is_an_inference_not_an_identification(self):
        from app.providers.factsets import director_candidates
        flag = director_candidates(AMBANI)["flags"][0]
        assert "not an identification" in flag["detail"]
        assert flag["level"] == "info"

    def test_the_summary_line_names_a_company_too(self):
        """The one line that appears in the findings list without opening
        anything. It used to read "None 0, None 0, None 10"."""
        runner, _ = make_runner(FakeSession(None), resolve_director=AMBANI)
        finding = dispatch(runner, "dresolve",
                           {"dresolve": {"q": "Mukesh Dhirubhai Ambani"}})
        assert "SHIVANGI COMMERCIALS LLP" in finding.detail
        assert "None" not in finding.detail

    def test_the_summary_line_survives_object_companies(self):
        """Same coercion as the table, and the reason it lives at module
        level: two copies is how one of them ends up not fixed."""
        rich = [dict(c, companies=[{"name": n} for n in c["companies"]])
                for c in AMBANI]
        runner, _ = make_runner(FakeSession(None), resolve_director=rich)
        finding = dispatch(runner, "dresolve", {"dresolve": {"q": "M Ambani"}})
        assert "SHIVANGI COMMERCIALS LLP" in finding.detail

    def test_match_score_is_not_shown(self):
        """It comes back as 1736172819525404700 — identical on every
        candidate. Rendering it would put a number that looks like a
        ranking next to four rows it does not rank."""
        assert not any(c["key"] == "matchScore" for c in ambani_table()["columns"])


# =====================================================================
# dcontact — PII, and an unbounded bill
# =====================================================================

class TestDirectorContact:
    def _prior_dirs(self, n):
        return {"dirs": Finding("dirs", CheckStatus.PASS, raw={
            "directors": [{"din": f"{i:08d}"} for i in range(n)]})}

    def test_a_whole_board_lookup_is_capped(self):
        """Blank DIN means every director — a ₹50 unlock EACH plus the read.
        One ticked box must not become an unbounded bill."""
        runner, provider = make_runner(FakeSession(None))
        runner.settings = Settings(filesure_max_director_contacts=3)
        dispatch(runner, "dcontact", prior=self._prior_dirs(25))
        assert provider.calls.count("director_contact") == 3

    def test_the_email_is_masked_in_the_facts(self):
        """A working personal address is the most re-usable thing in the
        dossier. The unredacted value stays in raw_response."""
        runner, _ = make_runner(
            FakeSession(None),
            director_contact={"email": "amit.sharma@acme.in", "mobile": "98****3210"})
        finding = dispatch(runner, "dcontact", {"dcontact": {"din": "00001"}})
        rows = finding.facts["table"]["rows"]
        assert rows[0]["email"] == "a***@acme.in"
        # ...and the real one is still on file.
        assert finding.raw["contacts"][0]["email"] == "amit.sharma@acme.in"

    def test_the_masked_mobile_is_passed_through_as_the_source_sent_it(self):
        runner, _ = make_runner(
            FakeSession(None),
            director_contact={"email": None, "mobile": "98****3210"})
        finding = dispatch(runner, "dcontact", {"dcontact": {"din": "00001"}})
        assert finding.facts["table"]["rows"][0]["mobile"] == "98****3210"

    def test_no_contact_details_is_a_warn_not_a_pass(self):
        runner, _ = make_runner(FakeSession(None),
                                director_contact={"email": None, "mobile": None})
        finding = dispatch(runner, "dcontact", {"dcontact": {"din": "00001"}})
        assert finding.status is CheckStatus.WARN

    def test_no_din_available_skips_without_paying(self):
        runner, provider = make_runner(FakeSession(None))
        finding = dispatch(runner, "dcontact")
        assert finding.status is CheckStatus.SKIP
        assert provider.calls == []


# =====================================================================
# download — bytes that are not JSON
# =====================================================================

class TestFilingDownload:
    def test_the_document_is_stored_and_linked(self, tmp_path):
        """It used to record a size and a digest and throw the bytes away,
        so the row said "document retrieved" with nothing to open."""
        runner, _ = make_runner(FakeSession(None),
                                download_filing=b"%PDF-1.4 body" * 100)
        runner.settings = Settings(document_root=str(tmp_path))
        finding = dispatch(runner, "download", {"download": {"filingId": "flg_1"}})
        assert finding.status is CheckStatus.PASS
        assert len(finding.raw["sha256"]) == 64
        assert finding.raw["bytes"] == 1300
        assert finding.raw["stored"] is True
        # A link the panel can actually open.
        assert finding.facts["documents"][0]["href"] == finding.raw["url"]
        # ...and no "not retained" warning, because it was retained.
        assert not flags_of(finding)

    def test_a_full_disk_is_our_problem_not_the_vendor_s(self, tmp_path):
        """The check still passes and still reports what it found. Losing
        the file is housekeeping — it must not read as an adverse finding,
        and it must not fail a paid call that already succeeded."""
        runner, _ = make_runner(FakeSession(None),
                                download_filing=b"%PDF-1.4 body" * 100)
        runner.settings = Settings(
            document_root=str(tmp_path),
            document_min_free_bytes=10 ** 18,      # nothing will ever fit
        )
        finding = dispatch(runner, "download", {"download": {"filingId": "flg_1"}})
        assert finding.status is CheckStatus.PASS
        assert finding.raw["stored"] is False
        assert "Document is identified, not retained" in flags_of(finding)

    def test_the_same_document_twice_is_stored_once(self, tmp_path):
        """Content-addressed: re-running a check costs no extra disk."""
        body = b"%PDF-1.4 body" * 100
        for _ in range(2):
            runner, _ = make_runner(FakeSession(None), download_filing=body)
            runner.settings = Settings(document_root=str(tmp_path))
            dispatch(runner, "download", {"download": {"filingId": "flg_1"}})
        assert len(list(tmp_path.rglob("*.pdf"))) == 1

    def test_the_document_body_never_reaches_facts_or_raw(self):
        body = b"%PDF-1.4 SENSITIVE" * 200
        runner, _ = make_runner(FakeSession(None), download_filing=body)
        finding = dispatch(runner, "download", {"download": {"filingId": "flg_1"}})
        assert "SENSITIVE" not in str(finding.facts)
        assert "SENSITIVE" not in str(finding.raw)

    def test_an_empty_document_is_unavailable_not_a_missing_filing(self):
        runner, _ = make_runner(FakeSession(None), download_filing=b"")
        finding = dispatch(runner, "download", {"download": {"filingId": "flg_1"}})
        assert finding.status is CheckStatus.UNAVAILABLE

    def test_no_filing_selected_never_reaches_the_provider(self):
        runner, provider = make_runner(FakeSession(None))
        finding = dispatch(runner, "download")
        assert finding.status is CheckStatus.SKIPPED_MISSING_INPUT
        assert provider.calls == []


# =====================================================================
# All five produce facts
# =====================================================================

@pytest.mark.parametrize("check_id,inputs,prior,returns", [
    ("dresolve", {"dresolve": {"q": "R Sharma"}}, None,
     {"resolve_director": [{"din": "1", "name": "R Sharma",
                            "totalDirectorshipCount": 3}]}),
    ("dcontact", {"dcontact": {"din": "1"}}, None,
     {"director_contact": {"email": "a@b.in", "mobile": "98****1"}}),
    ("download", {"download": {"filingId": "f1"}}, None,
     {"download_filing": b"pdf"}),
    ("frefresh", None, None, {"refresh_filings": {"status": "queued"}}),
    ("refresh", None, None, {"trigger_update": {"status": "completed"}}),
])
def test_each_new_check_renders(check_id, inputs, prior, returns):
    runner, _ = make_runner(FakeSession(None), **returns)
    finding = dispatch(runner, check_id, inputs, prior)
    assert finding.facts, f"{check_id} produced no facts"
    assert finding.facts["shape"] in {
        "detail", "summary", "table", "document", "reference"}