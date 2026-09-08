"""eCourtsIndia adapter — the confidence gate and the double-charge guard.

Two properties are defended here, and both are about not doing harm.

A litigation match is only allowed to score when the provider says it is
confident the subject is actually this vendor. Court records attach to
names, names collide, and a −15 applied to the wrong company is the kind of
mistake an audit product cannot defend afterwards.

And a check that runs past its poll budget must not be paid for twice. The
job is queued and charged on submit, so the code has to survive the timeout.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.domain.types import CheckResult, CheckStatus
from app.providers import ecourts as ec
from app.providers.base import NotConfigured, ProviderParseGap


def _settings(**kw) -> Settings:
    base = dict(
        ecourts_api_key="eci_live_test",
        ecourts_base_url="https://webapi.ecourtsindia.com/api/partner",
        ecourts_poll_budget_seconds=0.3,
        ecourts_poll_interval_seconds=0.01,
    )
    base.update(kw)
    return Settings(**base)


def _provider(handler, **kw) -> ec.EcourtsProvider:
    return ec.EcourtsProvider(
        _settings(**kw), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


NAME = "MERIDIAN PACKAGING PRIVATE LIMITED"


def _report(band="LOW", confidence=90.0, matches=0):
    return {
        "data": {
            "schema_version": "legal-check.v1",
            "code": "LC-A1B2C3D",
            "status": "completed",
            "model": "eCI-1.2",
            "engine_version": "1.0",
            "client_ref_no": "V0001",
            "subject": {"subject_type": "company", "name": NAME},
            "risk_band": band,
            "identity_confidence": confidence,
            "matches": [{"cnr": f"DLHC0100012{i}2024"} for i in range(matches)],
        }
    }


def _router(*, status_seq=("completed",), report=None):
    """Serves submit → status (in sequence) → report."""
    seen = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert request.headers["authorization"] == "Bearer eci_live_test"

        if request.method == "POST" and url.endswith("/legal-check"):
            assert request.headers.get("idempotency-key")
            return httpx.Response(200, json={"data": {"code": "LC-A1B2C3D",
                                                      "status": "queued"}})
        if "/report" in url:
            return httpx.Response(200, json=report or _report())
        if "/legal-check/" in url:
            i = min(seen["status"], len(status_seq) - 1)
            seen["status"] += 1
            return httpx.Response(200, json={"data": {
                "code": "LC-A1B2C3D", "status": status_seq[i],
                "current_stage": "court_search",
                "progress": {"completed": 2, "total": 5},
            }})
        raise AssertionError(f"unexpected request {url}")

    return handler


# ---------------------------------------------------------------------
# The confidence gate
# ---------------------------------------------------------------------


def test_confident_high_band_is_adverse():
    data = _provider(_router(report=_report("HIGH", 92.0, matches=3))).run_legal_check(
        subject_name=NAME, idempotency_key="k", client_ref_no="V0001",
    )
    assert data["risk_band"] == "HIGH"
    assert data["confident"] is True
    assert data["match_count"] == 3


def test_low_confidence_is_never_confident_however_bad_the_band():
    """The whole point. A HIGH band on a weak identity match is probably a
    different company with a similar name, and must not score."""
    data = _provider(_router(report=_report("HIGH", 41.0, matches=9))).run_legal_check(
        subject_name=NAME, idempotency_key="k", client_ref_no="V0001",
    )
    assert data["risk_band"] == "HIGH"
    assert data["confident"] is False


def test_risk_rule_r13_respects_the_gate():
    from app.catalog.risk import RULE_TESTS

    confident = {"court": CheckResult("court", CheckStatus.FAIL,
                                      raw_response={"risk_band": "HIGH",
                                                    "confident": True})}
    weak = {"court": CheckResult("court", CheckStatus.WARN,
                                 raw_response={"risk_band": "HIGH",
                                               "confident": False})}
    assert RULE_TESTS["r13"](confident) is True
    assert RULE_TESTS["r13"](weak) is False


def test_low_band_does_not_score_even_when_confident():
    from app.catalog.risk import RULE_TESTS

    clean = {"court": CheckResult("court", CheckStatus.PASS,
                                  raw_response={"risk_band": "LOW",
                                                "confident": True})}
    assert RULE_TESTS["r13"](clean) is False


def test_min_score_floor_is_recorded_with_the_result():
    """A score computed under one confidence floor is not comparable to one
    computed under another, so the floor is part of the evidence."""
    data = _provider(_router()).run_legal_check(
        subject_name=NAME, idempotency_key="k", client_ref_no="V0001", min_score=40,
    )
    assert data["min_score_applied"] == 40
    assert data["schema_version"] == "legal-check.v1"


# ---------------------------------------------------------------------
# Not paying twice
# ---------------------------------------------------------------------


def test_pending_check_raises_with_the_code():
    """A job that outlives the poll budget is paid for and still running.
    Losing the code means paying again for the same answer."""
    with pytest.raises(ec.LegalCheckPending) as exc:
        _provider(_router(status_seq=("running",))).run_legal_check(
            subject_name=NAME, idempotency_key="k", client_ref_no="V0001",
        )
    assert exc.value.code == "LC-A1B2C3D"
    # Must remain catchable as an unavailable source, not a crash.
    from app.providers.base import ProviderUnavailable
    assert isinstance(exc.value, ProviderUnavailable)


def test_resume_never_submits_again():
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted.append(str(request.url))
        if "/report" in str(request.url):
            return httpx.Response(200, json=_report())
        return httpx.Response(200, json={"data": {"code": "LC-A1B2C3D",
                                                  "status": "completed"}})

    data = _provider(handler).run_legal_check(
        subject_name=NAME, idempotency_key="k", client_ref_no="V0001",
        existing_code="LC-A1B2C3D",
    )
    assert data["resumed"] is True
    assert not posted, "resuming must not submit — that is a second charge"


def test_submit_sends_an_idempotency_key():
    """Without it, an HTTP-layer retry starts a second paid job."""
    keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            keys.append(request.headers.get("idempotency-key"))
        return httpx.Response(200, json={"data": {"code": "LC-1", "status": "queued"}})

    _provider(handler).submit_legal_check(
        subject_name=NAME, idempotency_key="vbc-V0001-court", client_ref_no="V0001",
    )
    assert keys == ["vbc-V0001-court"]


# ---------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------


def test_missing_risk_band_is_a_parse_gap_not_a_clean_report():
    broken = {"data": {"code": "LC-A1B2C3D", "status": "completed",
                       "subject": {"name": NAME}}}
    with pytest.raises(ProviderParseGap):
        _provider(_router(report=broken)).run_legal_check(
            subject_name=NAME, idempotency_key="k", client_ref_no="V0001",
        )


def test_failed_job_is_unavailable_not_clean():
    from app.providers.base import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        _provider(_router(status_seq=("failed",))).run_legal_check(
            subject_name=NAME, idempotency_key="k", client_ref_no="V0001",
        )


def test_blank_subject_name_never_reaches_the_provider():
    called = []

    def handler(request):
        called.append(1)
        return httpx.Response(200, json={"data": {"code": "x"}})

    with pytest.raises(ValueError):
        _provider(handler).submit_legal_check(
            subject_name="  ", idempotency_key="k", client_ref_no="V0001",
        )
    assert not called


def test_no_token_is_not_configured():
    with pytest.raises(NotConfigured):
        ec.EcourtsProvider(Settings(ecourts_api_key="")).models()


# ---------------------------------------------------------------------
# Case Search — the empty-result trap
# ---------------------------------------------------------------------


CAPS = {"data": {
    "sortableFields": ["score", "filingDate", "decisionDate"],
    "facetableFields": ["caseType", "caseStatus", "courtCode", "stateCode"],
    "filterableFields": ["parties", "advocates", "courtCodes", "filingDateFrom"],
}}


def _search_router(results, caps=CAPS):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/search/capabilities" in url:
            return httpx.Response(200, json=caps)
        if "/search" in url:
            return httpx.Response(200, json={"data": {"results": results}})
        raise AssertionError(url)
    return handler


def test_search_returns_parties_so_the_side_is_visible():
    """Which side the vendor was on is the whole difference between a
    company recovering a debt and one being wound up."""
    rows = [{
        "cnr": "DLHC010001232024", "caseType": "RFA", "caseStatus": "PENDING",
        "filingDate": "2024-01-15", "nextHearingDate": "2024-03-15",
        "judges": ["Justice A.K. Sharma"],
        "petitioners": ["ABC Private Limited"],
        "respondents": ["XYZ Corporation"],
    }]
    data = _provider(_search_router(rows)).case_search(parties="ABC Private Limited")
    assert data["count"] == 1
    assert data["results"][0]["petitioners"] == ["ABC Private Limited"]
    assert data["results"][0]["respondents"] == ["XYZ Corporation"]


def test_unknown_filter_is_refused_by_default():
    """The published parameter list was truncated. A filter the server
    silently ignores widens or empties the result set invisibly."""
    with pytest.raises(ValueError) as exc:
        _provider(_search_router([])).case_search(madeUpField="x")
    assert "capability catalog" in str(exc.value)


def test_empty_results_from_an_unverified_filter_is_not_clean():
    """THE important one. An empty result from a malformed query and an
    empty result from a litigation-free company look identical from the
    outside, and only one of them may reach a report as good news."""
    with pytest.raises(ProviderParseGap):
        _provider(_search_router([]), ecourts_strict_search=False).case_search(
            notAKnownField="ABC Private Limited",
        )


def test_empty_results_from_a_verified_filter_is_a_real_answer():
    data = _provider(_search_router([])).case_search(parties="NOBODY LIMITED")
    assert data["count"] == 0
    assert data["unverified_filters"] == []


# ---------------------------------------------------------------------
# The rest of the surface
# ---------------------------------------------------------------------


def test_cnr_is_validated_before_it_becomes_a_url_path():
    called = []

    def handler(request):
        called.append(1)
        return httpx.Response(200, json={"data": {}})

    with pytest.raises(ValueError):
        _provider(handler).case_detail("../../etc/passwd")
    assert not called


def test_causelist_unknown_string_becomes_none():
    """The provider returns the literal "UNKNOWN". Left alone it passes
    every truthiness test and prints as a court name."""
    rows = [{"id": 1, "court": "UNKNOWN", "courtDescription": "UNKNOWN",
             "courtType": "DISTRICT_COURT", "listType": "CRIMINAL"}]

    def handler(request):
        return httpx.Response(200, json={"data": {"query": "ram", "results": rows}})

    data = _provider(handler).causelist_search("ram", state="JH")
    assert data["results"][0]["court"] is None
    assert data["results"][0]["courtType"] == "DISTRICT_COURT"


def test_bulk_refresh_keeps_the_invalid_list():
    """Three outcomes, not two — dropping `invalid` loses the only sign of
    a bad input."""
    def handler(request):
        return httpx.Response(200, json={"data": {
            "refreshed": ["DLHC010024442025"], "queued": [],
            "invalid": ["NOTAVALIDCNR"],
        }})

    data = _provider(handler).bulk_refresh(["DLHC010024442025", "DLHC010351552024"])
    assert data["invalid"] == ["NOTAVALIDCNR"]


def test_order_markdown_distinguishes_null_from_empty():
    """`markdownContent` may be null when conversion failed. That is not
    the same as an order with no text."""
    def handler(request):
        return httpx.Response(200, json={"data": {"pdfBase64": "JVBER...",
                                                  "markdownContent": None}})

    data = _provider(handler).order_markdown("DLHC010001232024", "order-1.pdf")
    assert data["markdown_available"] is False


def test_order_ai_is_flagged_as_provider_model_output():
    """Scope decision #1 is 'no LLM anywhere'. This endpoint returns
    model-generated analysis from the provider's side — usable, but it must
    be distinguishable from registry fact in the report."""
    def handler(request):
        return httpx.Response(200, json={"data": {
            "cnr": "DLHC010631472005", "extractedText": "## IN THE HIGH COURT",
            "aiAnalysis": {"foundational_metadata": {"core_case_identifiers": {
                "case_type": "Regular First Appeal",
                "case_sub_type": "Specific Performance Of Contract Matters",
            }}},
        }})

    data = _provider(handler).order_ai("DLHC010631472005", "order-5.pdf")
    assert data["provider_model_generated"] is True
    assert data["case_sub_type"] == "Specific Performance Of Contract Matters"


def test_court_structure_keeps_high_courts_and_supreme_court():
    """High courts arrive AS DISTRICTS and the Supreme Court AS A STATE.
    Filtering on the assumption that a district is a district drops both."""
    def handler(request):
        return httpx.Response(200, json=[
            {"state": "DL", "stateName": "Delhi"},
            {"state": "SC", "stateName": "India"},
        ])

    rows = _provider(handler).court_structure()
    assert any(r["state"] == "SC" for r in rows)


def test_hearing_batch_counts_only_listed_cases():
    def handler(request):
        return httpx.Response(200, json={"data": [
            {"cnr": "JHBO010001232024", "hasCauselist": True,
             "nextListing": {"listingFor": "EVIDENCE"}},
            {"cnr": "DLND020047882015", "hasCauselist": False},
        ]})

    data = _provider(handler).cnr_causelist_batch(
        ["JHBO010001232024", "DLND020047882015"])
    assert data["listed_count"] == 1
    assert data["checked"] == 2


def test_electoral_endpoints_are_absent():
    """Three exist. None are implemented: electoral roll data is personal
    data about private individuals, gathered for another purpose, and no
    SCAN parameter or risk rule reads it."""
    public = {n for n in dir(ec.EcourtsProvider) if not n.startswith("_")}
    assert not {"electoral_roll_search", "epic_lookup",
                "electoral_capabilities"} & public


# ---------------------------------------------------------------------
# The ten checks added on top of the core three
# ---------------------------------------------------------------------


def test_order_files_prefers_judgments_over_interim():
    """When the fetch is capped, the caller should get the orders that
    decided something, not the procedural ones."""
    from app.services.runner import _order_files

    names = _order_files({
        "interim_orders": [{"filename": "interim-9.pdf"}],
        "judgment_orders": [{"filename": "judgment-1.pdf"}],
    })
    assert names[0] == "judgment-1.pdf"


def test_order_files_strips_a_url_down_to_its_filename():
    from app.services.runner import _order_files

    names = _order_files({
        "judgment_orders": [{"orderUrl": "https://x/y/case/order-5.pdf"}],
    })
    assert names == ["order-5.pdf"]


def test_order_fetch_is_capped():
    """A case can carry dozens of orders and each fetch is a paid call.
    Uncapped, one ticked box becomes an unbounded bill."""
    from app.config import Settings

    assert Settings().ecourts_max_orders == 3


def test_case_detail_counts_orders_without_fetching_them():
    def handler(request):
        return httpx.Response(200, json={"data": {"courtCaseData": {
            "caseNumber": "202400248072016",
            "caseTypeSub": "Criminal Procedure Code.",
            "courtName": "Chief Metropolitan Magistrate, New Delhi, PHC",
            # Required: the guard refuses a case record with no status,
            # because "we could not tell if it is live" must not read as
            # "nothing to see here".
            "caseStatus": "PENDING",
            "judgmentOrders": [{"filename": "j1.pdf"}],
            "interimOrders": [{"filename": "i1.pdf"}, {"filename": "i2.pdf"}],
        }}})

    data = _provider(handler).case_detail("DLHC010001232024")
    assert len(data["judgment_orders"]) == 1
    assert len(data["interim_orders"]) == 2
    assert data["case_type_sub"] == "Criminal Procedure Code"
    assert data["is_pending"] is True


def test_first_cnr_comes_from_the_search_results():
    from app.services.runner import Finding, _first_cnr
    from app.domain.types import CheckStatus as CS

    prior = {"courtsearch": Finding("courtsearch", CS.WARN, raw={
        "results": [{"cnr": None}, {"cnr": "DLHC010001232024"}]})}
    assert _first_cnr(prior) == "DLHC010001232024"
    assert _first_cnr({}) is None


def test_admin_checks_feed_nothing():
    """Reference data is not evidence about a vendor. These must not touch
    a SCAN parameter or a risk rule."""
    from app.catalog.checks import check

    for cid in ("courtcaps", "courtenums", "courtstructure", "courtdates",
                "caserefresh", "courtchecks"):
        definition = check(cid)
        assert definition.admin is True, cid
        assert definition.feeds == (), cid


def test_case_refresh_is_reported_as_queued_not_done():
    """202 Accepted. Reporting it as complete would have an analyst reading
    stale data believing it was just refreshed."""
    def handler(request):
        return httpx.Response(202, json={"data": {
            "cnr": "DLHC010001232024", "status": "QUEUED",
            "message": "Case refresh request queued",
            "estimatedTime": "5-10 seconds",
        }})

    data = _provider(handler).case_refresh("DLHC010001232024")
    assert data["status"] == "QUEUED"
    assert data["estimated_time"] == "5-10 seconds"


# ---------------------------------------------------------------------
# Against a REAL payload (CNR DLND020047882015, fetched 2026-09-06)
#
# Every one of these asserts something the reference examples got wrong or
# did not show. This is the payload that proved the adapter needed fixing.
# ---------------------------------------------------------------------


REAL = {
    "data": {
        "courtCaseData": {
            "caseNumber": "202400248072016",
            "district": "New Delhi", "state": "DL",
            "courtCode": 2, "cnrCourtCode": "DLND02",
            "caseTypeSub": "Criminal Procedure Code. - ---",
            "courtName": "Chief Metropolitan Magistrate, New Delhi, PHC",
            "firDetails": {"policeStation": "South Avenue"},
            "caseType": "CC", "caseStatus": "DISPOSED",
            "disposalType": "DISMISSED_AS_WITHDRAWN",
            "disposalTypeRaw": "DISMISSED AS WITHDRAWN",
            "contestedStatus": "UNCONTESTED",
            "filingDate": "2015-12-21", "decisionDate": "2018-07-07",
            "caseDurationDays": 929,
            "petitioners": ["Arun Jaitley"], "respondents": ["Arvind Kejriwal"],
            "actsAndSections": "Criminal Procedure Code, 1973",
            "orderCount": 10, "judgmentCount": 1, "hearingCount": 25,
            "interimOrders": [{"orderDate": "2017-10-27", "orderUrl": "order-1.pdf"}],
            "judgmentOrders": [{"orderDate": "2018-07-07", "orderType": "Final Order",
                                "orderUrl": "order-10.pdf"}],
        },
        "entityInfo": {"dateModified": "2026-09-06T14:31:22.178043Z"},
        # The live shape: an OBJECT wrapping the array.
        "files": {"files": [
            {"pdfFile": "x-order-1.pdf", "markdownContent": "…",
             "aiAnalysis": {"foundational_metadata": {}}},
            {"pdfFile": "x-order-2.pdf", "markdownContent": "…", "aiAnalysis": None},
        ]},
        "descriptions": {"enumLookup": {
            "caseType": {"CC": "Criminal Complaint Case"},
            "courtCode": {"DLND02": "Chief Metropolitan Magistrate, New Delhi, "
                                    "Patiala House Courts"},
        }},
    },
    "meta": {"request_id": "4002329e-001d-8b00-b63f-84710c7967bb"},
}


def _real():
    return _provider(lambda r: httpx.Response(200, json=REAL)).case_detail(
        "DLND020047882015")


def test_files_are_nested_one_level_deeper_than_documented():
    """`data.files` is an object wrapping the array. Read as a list it
    yields a dict that iterates over its KEYS — a silent wrong answer."""
    data = _real()
    assert isinstance(data["files"], list)
    assert len(data["files"]) == 2


def test_disposal_type_survives_because_disposed_is_not_a_verdict():
    """A withdrawal and a conviction are both DISPOSED. Only the disposal
    type separates them, so dropping it loses the entire finding."""
    data = _real()
    assert data["case_status"] == "DISPOSED"
    assert data["disposal_type_raw"] == "DISMISSED AS WITHDRAWN"
    assert data["is_pending"] is False


def test_parties_are_kept_so_the_side_is_visible():
    data = _real()
    assert data["petitioners"] == ["Arun Jaitley"]
    assert data["respondents"] == ["Arvind Kejriwal"]


def test_provider_model_content_is_flagged_on_the_plain_case_call():
    """`aiAnalysis` arrives on THIS endpoint, unasked. Scope decision #1 is
    'no LLM anywhere' — the flag is what lets the report keep provider model
    output separate from registry fact."""
    assert _real()["provider_model_content"] is True


def test_enum_codes_get_their_human_label_from_the_response():
    data = _real()
    assert data["case_type_label"] == "Criminal Complaint Case"
    assert "Patiala House" in (data["court_label"] or "")


def test_placeholder_tail_is_stripped_from_case_type_sub():
    # "Criminal Procedure Code. - ---" is not a case sub-type.
    assert _real()["case_type_sub"] == "Criminal Procedure Code"


def test_order_filenames_come_from_orderUrl_not_filename():
    """No `filename` key exists in the live payload."""
    from app.services.runner import _order_files

    names = _order_files(_real())
    assert names[0] == "order-10.pdf"      # judgment first
    assert "order-1.pdf" in names