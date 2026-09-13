"""Unlocking is asynchronous, and the run must not pretend otherwise.

`POST /v1/companies/{cin}/unlock` returns `202 Accepted` in milliseconds.
The documents it pays for arrive **ten to thirty minutes later**. FileSure's
own documentation is explicit:

    Filings + extractions endpoints start returning real data [only after
    the background refresh]. Until then they reply with the unlock-status
    JSON { unlocked: false, unlockPrice } or ... a 404 DOC_NOT_AVAILABLE.

So a run that unlocked a company and read its filings in the same request
got an empty answer, and reported it as **"No filings returned"** and
**"No financials filed"** — WARN findings about the vendor. A company with a
complete filing history and a company whose documents had not downloaded yet
produced identical rows.

That is the failure this product exists to prevent: a gap wearing the
clothes of a result. These tests hold that shut.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.types import CheckStatus
from app.providers import filesure as fs
from app.providers.base import ProviderParseGap, Spend
from app.services.runner import CheckRunner, Finding, RunResult


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


class _StatusProvider(fs.FileSureProvider):
    """Stubs the free status call so no HTTP and no key are needed."""

    def __init__(self, payload):
        self.settings = Settings()
        self.spend = Spend()
        self._payload = payload

    def _call(self, *_a, **_kw):
        class R:
            payload = {"data": self._payload}
        return R()

    def _data(self, response):
        return response.payload["data"]


def status_from(payload) -> fs.UnlockStatus:
    return _StatusProvider(payload).unlock_status("U1")


class Reached(Exception):
    """A stubbed provider was called — proof the gate let the check past."""


class Tripwire:
    """Every provider method raises, naming itself.

    A check that gets through the gate goes on to call its provider. Rather
    than letting that fail as an incidental AttributeError, this turns
    "reached the provider" into the assertion itself.
    """

    def __getattr__(self, name):
        def boom(*_a, **_kw):
            raise Reached(name)
        return boom


def runner_with(result: RunResult) -> CheckRunner:
    r = CheckRunner.__new__(CheckRunner)
    r.settings = Settings()
    r.spend = Spend()
    r.session = None
    r.filesure = r.whoisxml = r.archive = r.finagg = r.ecourts = Tripwire()
    return r


def dispatch(check_id: str, result: RunResult) -> Finding:
    return runner_with(result)._dispatch(
        check_id, FakeVendor(), FakeVendor.cin, {}, None, result, {},
    )


def assert_not_gated(check_id: str, result: RunResult) -> None:
    """The check was NOT short-circuited by the documents gate.

    It either reached its provider, or returned for a reason of its own —
    both mean the gate stayed out of the way. Only the gate's own Finding
    counts as a failure.
    """
    try:
        finding = dispatch(check_id, result)
    except Reached:
        return
    assert finding.value != "Documents not ready", (
        f"{check_id} was gated on the document refresh but does not need it"
    )


def stages(download_status: str | None, **others) -> dict:
    st = {k: {"status": v} for k, v in others.items()}
    if download_status is not None:
        st["documentDownloadV3"] = {"status": download_status}
    return {"unlocked": True, "unlockedAt": "2026-09-13T10:00:00Z",
            "expiresAt": "2027-09-13T10:00:00Z",
            "job": {"processingStages": st}}


# =====================================================================
# 1 · Reading the provider's progress signal
# =====================================================================

class TestProgressSignal:
    @pytest.mark.parametrize("state,running", [
        ("pending", True),
        ("in_progress", True),
        ("success", False),
    ])
    def test_the_documented_stage_values_are_understood(self, state, running):
        """`pending` → `in_progress` → `success` is the provider's own
        documented sequence for documentDownloadV3."""
        s = status_from(stages(state))
        assert s.download_status == state
        assert s.refresh_running is running
        assert s.documents_ready is (not running)

    def test_no_job_counts_as_ready(self):
        """A company unlocked last month carries no live job. Treating "no
        job" as "not ready" would block every returning vendor forever."""
        s = status_from({"unlocked": True, "expiresAt": "2027-01-01T00:00:00Z"})
        assert s.download_status is None
        assert s.refresh_running is False
        assert s.documents_ready is True

    def test_a_sandbox_unlock_has_no_job_and_does_not_block(self):
        s = status_from({"unlocked": True, "sandbox": True, "job": None})
        assert s.sandbox is True
        assert s.documents_ready is True

    def test_not_unlocked_is_never_ready(self):
        s = status_from({"unlocked": False, "unlockPrice": 33000})
        assert s.documents_ready is False

    def test_every_stage_is_kept_for_the_evidence_panel(self):
        s = status_from(stages("in_progress", extraction="pending",
                               masterData="success"))
        assert s.stages == {"documentDownloadV3": "in_progress",
                            "extraction": "pending", "masterData": "success"}

    def test_zip_urls_still_parse(self):
        """The behaviour that was already there must survive the change."""
        payload = stages("success")
        payload["job"]["processingStages"]["documentDownloadV3"]["zipFiles"] = [
            {"blob_url": "https://x/1.zip"}, {"blob_url": "https://x/2.zip"},
        ]
        assert status_from(payload).zip_urls == ["https://x/1.zip", "https://x/2.zip"]


class TestRenameFailsLoudly:
    def test_a_renamed_stage_raises_rather_than_reporting_ready(self):
        """If documentDownloadV3 is renamed, `download_status` goes None and
        None means ready — so a rename would silently start reporting every
        refresh as finished. That is precisely how four adapter defects have
        already reached production. The guard makes it an error instead."""
        payload = stages(None, documentDownload="in_progress", extraction="pending")
        with pytest.raises(ProviderParseGap):
            status_from(payload)

    def test_a_job_with_no_stages_at_all_does_not_trip_the_guard(self):
        """Legitimate absence. The guard only fires when there IS stage
        content and the one we steer on is missing from it."""
        s = status_from({"unlocked": True, "job": {"processingStages": {}}})
        assert s.documents_ready is True


# =====================================================================
# 2 · The gate — what the analyst actually sees
# =====================================================================

class TestDocumentDependentChecks:
    @pytest.mark.parametrize("check_id", ["filings", "fin", "download"])
    def test_they_report_unavailable_not_absence(self, check_id):
        """Before this, `filings` said "No filings returned — MCA holds no
        filings matching this filter" and `fin` said "No financials filed".
        Both are findings about the vendor. Neither was true."""
        result = RunResult(vendor_id="V1", documents_ready=False,
                           refresh_stage="in_progress")
        f = dispatch(check_id, result)
        assert f.status is CheckStatus.UNAVAILABLE
        assert f.value == "Documents not ready"
        assert "NOT as a company with none" in f.detail

    def test_unavailable_cannot_become_a_positive(self):
        """UNAVAILABLE is excluded from `was_examined`, so a pending refresh
        can never contribute to SCAN or to the risk ledger. An empty PASS
        could have."""
        result = RunResult(vendor_id="V1", documents_ready=False)
        f = dispatch("filings", result)
        assert not f.status.was_examined

    def test_the_row_explains_that_it_will_change(self):
        result = RunResult(vendor_id="V1", documents_ready=False,
                           refresh_stage="pending")
        f = dispatch("fin", result)
        flag = f.facts["flags"][0]
        assert "10–30 minutes" in flag["detail"]
        assert "not charged again" in flag["detail"]

    def test_the_stage_is_named_so_progress_is_visible(self):
        result = RunResult(vendor_id="V1", documents_ready=False,
                           refresh_stage="in_progress")
        assert "in_progress" in dispatch("download", result).detail

    @pytest.mark.parametrize("check_id", ["master", "dirs", "charges", "gst"])
    def test_checks_that_do_not_need_documents_are_untouched(self, check_id):
        """Master data is cached and answers immediately — gating it would
        cost a paid call's worth of information for nothing."""
        assert_not_gated(check_id, RunResult(vendor_id="V1", documents_ready=False))

    def test_a_ready_run_behaves_exactly_as_before(self):
        result = RunResult(vendor_id="V1")          # documents_ready defaults True
        assert result.documents_ready is True
        assert_not_gated("filings", result)


# =====================================================================
# 3 · Deciding readiness during the unlock step
# =====================================================================

class TestUnlockStep:
    def test_a_fresh_unlock_is_known_not_ready_without_asking(self):
        """The docs say `data.job` is null immediately after the POST,
        because the job has not been registered yet. So a status call right
        after paying would return no job — which reads as READY. The fresh
        unlock is therefore treated as certain, not inferred."""
        result = RunResult(vendor_id="V1")
        runner = runner_with(result)
        runner._apply_refresh_state(status_from(stages("in_progress")), result)
        assert result.documents_ready is False
        assert result.refresh_stage == "in_progress"

    def test_a_finished_job_leaves_the_run_alone(self):
        result = RunResult(vendor_id="V1")
        runner_with(result)._apply_refresh_state(status_from(stages("success")), result)
        assert result.documents_ready is True

    def test_a_sandbox_status_never_blocks(self):
        result = RunResult(vendor_id="V1")
        runner_with(result)._apply_refresh_state(
            status_from({"unlocked": True, "sandbox": True, "job": None}), result)
        assert result.documents_ready is True

    def test_a_blocked_run_says_so_in_its_notes(self):
        result = RunResult(vendor_id="V1")
        runner_with(result)._apply_refresh_state(status_from(stages("pending")), result)
        assert any("UNAVAILABLE rather than absent" in n for n in result.notes)
