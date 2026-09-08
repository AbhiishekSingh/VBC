"""eCourtsIndia adapter — litigation exposure, via LegalCheck.

WHY LEGALCHECK AND NOT CASE SEARCH
----------------------------------
eCourtsIndia exposes case-level search across the Supreme Court, 37 High
Courts, District Courts, NCLT and NCLAT. Searching those directly by party
name looks like the obvious integration and is the wrong one.

A name-based court search is noisy in both directions. Common company names
return cases belonging to other companies; a vendor litigating under a
slightly different registered name returns nothing. Applying a fixed
penalty to a fuzzy name match means occasionally condemning the wrong
company, with no way for the analyst to tell that is what happened.

LegalCheck answers the same question and returns something case search
does not: an ``identity_confidence`` alongside the ``risk_band``. That is
the difference between a finding an analyst can defend and a number nobody
can explain. Its own documented example carries
``"purpose": "vendor_onboarding"``, and ``/legal-check/models`` reports
``supported_subject_types: ["individual", "company"]`` — which is what VBC
has, from the MCA legal name and CIN.

So LegalCheck is the SCORED check. Every other documented endpoint is
implemented too — case search, case detail, orders, refresh, cause lists,
enums, court structure — but as evidence an analyst reads, not as points.

Case Search carries one extra protection. Its parameter list was truncated
in the published documentation, so filter names are validated against
``/search/capabilities`` and a search that returns NOTHING while using an
unconfirmed filter is recorded as unexamined, never as "no cases". An empty
result from a malformed query and an empty result from a clean company look
identical from the outside, and only one of them may reach a report as good
news.

NOT IMPLEMENTED: the three Electoral endpoints. Electoral roll data is
personal data about private individuals, collected for another purpose, and
no SCAN parameter or risk rule reads it.

CONFIDENCE GATES SCORING
------------------------
``identity_confidence`` below ``ECI_MIN_IDENTITY_CONFIDENCE`` never produces
a fail. It produces a WARN that names the matched subject and asks for an
analyst. Penalising a vendor for a case belonging to a similarly-named
company is the class of error an audit product cannot defend, and the
provider hands us the number needed to avoid it.

ASYNC, INSIDE A SYNCHRONOUS RUN
-------------------------------
LegalCheck is a queued job — their example completes in about 68 seconds.
VBC has no job queue and nginx cuts the request at 120s, so this polls with
a hard budget and, if the report is not ready in time, records the check as
unavailable WITH THE CHECK CODE. A later run reads that code and fetches the
finished report instead of submitting again. Combined with the idempotency
key, that means a slow check costs money once, not once per attempt.
"""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.providers.base import (
    HttpProvider,
    NotConfigured,
    ParseGuard,
    ProviderParseGap,
    ProviderUnavailable,
    Spend,
    dig,
    is_blank,
)

logger = logging.getLogger(__name__)

#: Below this, a match is reported for review and never scored as adverse.
#: 90.0 is the value in the provider's own example of a good match.
MIN_IDENTITY_CONFIDENCE = 75.0

#: Risk bands the provider returns, worst first.
BAND_HIGH = "HIGH"
BAND_MEDIUM = "MEDIUM"
BAND_LOW = "LOW"

#: Terminal job states.
DONE = ("completed", "failed", "error", "cancelled")

#: Filters the server accepts but `/search/capabilities` does not list.
#: `parties` was confirmed by direct call on 2026-09-07: it returned 200
#: with populated `data.results[]` for a company name. The catalog lists
#: `petitioners` and `respondents` separately; `parties` matches either
#: side in one call, which is what a vendor check needs — a company can be
#: respondent in one matter and petitioner in the next.
#: Anything added here needs the same evidence. It is not a place to
#: silence the guard.
CONFIRMED_UNLISTED_FILTERS: frozenset[str] = frozenset({"parties"})


class EcourtsProvider(HttpProvider):
    """The full documented surface: cases, orders, cause lists, LegalCheck."""

    name = "ecourts"

    def __init__(self, settings: Settings | None = None, client=None,
                 spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()
        #: Cached capability catalog — free to fetch, wasteful to refetch.
        self._capabilities: dict | None = None

    # -----------------------------------------------------------------

    def _require_key(self) -> None:
        if not self.settings.ecourts_configured:
            raise NotConfigured(
                "eCourtsIndia has no API token configured. Set "
                "VBC_ECOURTS_API_KEY. Until then the court check reports "
                "not_configured — which is not the same as a vendor having "
                "no litigation against it."
            )

    def _url(self, path: str) -> str:
        return f"{self.settings.ecourts_base_url.rstrip('/')}/{path.lstrip('/')}"

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.settings.ecourts_api_key}"}
        if extra:
            headers.update(extra)
        return headers

    # -----------------------------------------------------------------
    # Free — capability discovery
    # -----------------------------------------------------------------

    def models(self) -> dict:
        """Which LegalCheck models exist and what subjects they accept.

        Free. Worth calling before a company check to confirm the account's
        model still lists ``company`` — a model that quietly dropped it
        would otherwise fail deep inside a paid submit.
        """
        self._require_key()
        response = self.request("GET", self._url("legal-check/models"),
                                headers=self._headers())
        data = (response.payload or {}).get("data") or {}
        models = data.get("models") or []
        return {
            "models": models,
            "supports_company": any(
                "company" in (m.get("supported_subject_types") or [])
                for m in models if isinstance(m, dict)
            ),
        }

    # -----------------------------------------------------------------
    # The check
    # -----------------------------------------------------------------

    def submit_legal_check(
        self,
        *,
        subject_name: str,
        idempotency_key: str,
        client_ref_no: str,
        subject_type: str = "company",
        aliases: list[str] | None = None,
        addresses: list[str] | None = None,
        model: str = "eCI-1.2",
        notes: str = "",
    ) -> dict:
        """Queue a check. Returns the code needed to collect the report.

        The idempotency key is not decoration: this costs money and the
        submit may be retried by the HTTP layer. A stable key — vendor id
        plus attempt — means a retry collects the existing job rather than
        starting a second one.
        """
        self._require_key()
        if is_blank(subject_name):
            raise ValueError(
                "A legal check needs a subject name. For a company use the "
                "MCA legal name, not the trade name — the courts use the "
                "registered one."
            )

        subject: dict = {"name": subject_name.strip()}
        if aliases:
            subject["aliases"] = [a for a in aliases if not is_blank(a)]
        if addresses:
            subject["addresses"] = [a for a in addresses if not is_blank(a)]
        if notes:
            subject["notes"] = notes

        response = self.request(
            "POST",
            self._url("legal-check"),
            headers=self._headers({
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            }),
            json={
                "subject_type": subject_type,
                "subject": subject,
                "config": {
                    "model": model,
                    "purpose": "vendor_onboarding",
                    "client_ref_no": client_ref_no,
                },
            },
        )
        self.spend.record("ecourts.legal-check", paisa=self.settings.ecourts_check_paisa)

        data = (response.payload or {}).get("data") or {}
        code = data.get("code")
        guard = ParseGuard("ecourts.submit")
        guard.expect("check code", raw=data, parsed=code,
                     hint="data.code · without it the report cannot be collected")
        guard.raise_if_gaps(payload=response.payload)
        return {"code": code, "status": data.get("status"), "raw": data}

    def check_status(self, code: str) -> dict:
        self._require_key()
        response = self.request("GET", self._url(f"legal-check/{code}"),
                                headers=self._headers())
        data = (response.payload or {}).get("data") or {}
        progress = data.get("progress") or {}
        return {
            "code": data.get("code", code),
            "status": str(data.get("status") or "").lower(),
            "stage": data.get("current_stage"),
            "completed": progress.get("completed"),
            "total": progress.get("total"),
            "error": data.get("error"),
        }

    def report(self, code: str, *, min_score: int | None = None,
               verbosity: str = "standard") -> dict:
        """The finished check, normalised.

        ``min_score`` is a match-confidence floor applied by the provider.
        It is recorded in the result because it changes what the report
        contains — a score computed against one floor is not comparable to
        one computed against another, and an audit trail that cannot
        reproduce its own inputs is not one.
        """
        self._require_key()
        params: dict = {"verbosity": verbosity}
        if min_score is not None:
            params["min_score"] = min_score

        response = self.request("GET", self._url(f"legal-check/{code}/report"),
                                headers=self._headers(), params=params)
        data = (response.payload or {}).get("data") or {}

        band = str(data.get("risk_band") or "").upper()
        confidence = _as_float(data.get("identity_confidence"))

        guard = ParseGuard("ecourts.report")
        guard.expect("risk band", raw=data, parsed=band,
                     hint="risk_band · the only field that scores")
        guard.expect_any(
            "identity confidence", raw=data, parsed=[confidence],
            hint="identity_confidence · gates whether the band may score at all",
        )
        guard.raise_if_gaps(payload=response.payload)

        matches = _matches(data)
        return {
            "code": data.get("code", code),
            "schema_version": data.get("schema_version"),
            "model": data.get("model"),
            "engine_version": data.get("engine_version"),
            "status": data.get("status"),
            "requested_at": data.get("requested_at"),
            "completed_at": data.get("completed_at"),
            "client_ref_no": data.get("client_ref_no"),
            "subject": data.get("subject") or {},
            "risk_band": band,
            "identity_confidence": confidence,
            #: The floor this report was produced under. Stored so an old
            #: score can be reproduced against the same inputs.
            "min_score_applied": min_score,
            "matches": matches,
            "match_count": len(matches),
            "confident": (
                confidence is not None and confidence >= MIN_IDENTITY_CONFIDENCE
            ),
        }

    def run_legal_check(
        self,
        *,
        subject_name: str,
        idempotency_key: str,
        client_ref_no: str,
        existing_code: str | None = None,
        subject_type: str = "company",
        aliases: list[str] | None = None,
        addresses: list[str] | None = None,
        min_score: int | None = None,
    ) -> dict:
        """Submit (or resume), poll to a budget, and collect the report.

        ``existing_code`` resumes a check a previous run paid for and did
        not finish. Passing it skips the submit entirely — the alternative
        is paying twice for the same answer because the first attempt ran
        out of wall-clock.
        """
        code = existing_code
        if not code:
            code = self.submit_legal_check(
                subject_name=subject_name,
                idempotency_key=idempotency_key,
                client_ref_no=client_ref_no,
                subject_type=subject_type,
                aliases=aliases,
                addresses=addresses,
            )["code"]

        deadline = time.monotonic() + self.settings.ecourts_poll_budget_seconds
        interval = self.settings.ecourts_poll_interval_seconds
        last: dict = {}

        while True:
            last = self.check_status(code)
            if last["status"] in DONE:
                break
            if time.monotonic() >= deadline:
                # Not a failure — an unfinished job. The code is raised with
                # the error so the runner can store it and resume later.
                raise LegalCheckPending(
                    f"Legal check {code} was still {last['status'] or 'queued'} "
                    f"after {self.settings.ecourts_poll_budget_seconds:.0f}s "
                    f"(stage {last.get('stage') or 'unknown'}, "
                    f"{last.get('completed')}/{last.get('total')} done). "
                    f"The check is paid for and still running — the next run "
                    f"collects the report using this code rather than "
                    f"submitting again.",
                    code=code,
                )
            time.sleep(interval)

        if last["status"] != "completed":
            raise ProviderUnavailable(
                f"Legal check {code} ended as '{last['status']}'"
                + (f" — {last['error']}" if last.get("error") else "")
            )

        result = self.report(code, min_score=min_score)
        result["resumed"] = bool(existing_code)
        return result


    # -----------------------------------------------------------------
    # Cases
    # -----------------------------------------------------------------

    def search_capabilities(self) -> dict:
        """What Case Search actually supports. Free, and cached per instance.

        This is not a nicety. The published Case Search parameter list was
        truncated, so the only trustworthy source for which filters exist is
        the provider itself. Everything ``case_search`` accepts is checked
        against this.
        """
        self._require_key()
        if self._capabilities is not None:
            return self._capabilities
        response = self.request("GET", self._url("search/capabilities"),
                                headers=self._headers())
        data = (response.payload or {}).get("data") or {}
        fields: set[str] = set()
        for key in ("sortableFields", "facetableFields", "projectableFields",
                    "presenceFilterableFields", "filterableFields",
                    "searchableFields", "queryableFields"):
            value = data.get(key)
            if isinstance(value, list):
                fields.update(str(v) for v in value)
        self._capabilities = {
            "raw": data,
            "fields": sorted(fields),
            "name_match_modes": data.get("nameMatchModes") or data.get("name_match_modes"),
            "court_levels": data.get("courtLevels") or data.get("court_levels"),
            "limits": data.get("limits"),
        }
        return self._capabilities

    def case_search(self, **filters) -> dict:
        """Search cases by whatever filters the provider says it supports.

        Filter names are passed through rather than hard-coded, because the
        documentation did not publish the full list. Two protections make
        that safe:

        * every key is checked against ``search_capabilities()`` and an
          unknown one raises immediately, naming the valid fields — instead
          of being silently ignored by the server;
        * a search that returns NOTHING while carrying a key the capability
          catalog did not confirm is reported as a parse gap, never as "no
          cases". An empty result from a malformed query and an empty result
          from a clean company are indistinguishable from the outside, and
          only one of them may reach a report as good news.
        """
        self._require_key()
        params = {k: v for k, v in filters.items() if not is_blank(v)}
        if not params:
            raise ValueError("case_search needs at least one filter.")

        known = set(self.search_capabilities()["fields"]) | CONFIRMED_UNLISTED_FILTERS
        unverified = sorted(k for k in params if known and k not in known)
        if known and unverified and self.settings.ecourts_strict_search:
            raise ValueError(
                f"Case Search filter(s) {unverified} are not in this account's "
                f"capability catalog. Supported: {sorted(known)}. Set "
                f"VBC_ECOURTS_STRICT_SEARCH=false to send them anyway."
            )

        response = self.request("GET", self._url("search"),
                                headers=self._headers(), params=params)
        self.spend.record("ecourts.search", paisa=self.settings.ecourts_search_paisa)

        data = (response.payload or {}).get("data") or {}
        results = data.get("results")
        if not isinstance(results, list):
            guard = ParseGuard("ecourts.search")
            guard.expect("results", raw=data, parsed=results,
                         hint="data.results[] · the case list")
            guard.raise_if_gaps(payload=response.payload)
            results = []

        if not results and unverified:
            raise ProviderParseGap(
                f"Case Search returned no results for a query using "
                f"unconfirmed filter(s) {unverified}. That is indistinguishable "
                f"from a company with no litigation, so it is recorded as "
                f"unexamined rather than clean. Check "
                f"GET /search/capabilities for the supported field names.",
                payload=response.payload,
            )

        return {
            "query": params,
            "unverified_filters": unverified,
            "results": [_case_row(r) for r in results if isinstance(r, dict)],
            "count": len(results),
            "total": data.get("total") or data.get("totalCount"),
        }

    def case_detail(self, cnr: str) -> dict:
        """Everything about one case, by CNR.

        Rewritten against a real payload. The reference examples were thin
        and three things in the live response would have been read wrongly:

        * ``data.files`` is an OBJECT wrapping the array — ``{"files":
          {"files": [...]}}`` — so treating it as a list silently produced a
          dict where a list was expected.
        * order documents carry no ``filename``; the key is ``orderUrl``,
          holding a bare name like ``order-1.pdf``.
        * ``files[].aiAnalysis`` is present in THIS response. Provider model
          output arrives whether or not the AI endpoint is called — see
          ``provider_model_content`` below.
        """
        self._require_key()
        cnr = _cnr(cnr)
        response = self.request("GET", self._url(f"case/{cnr}"),
                                headers=self._headers())
        self.spend.record("ecourts.case", paisa=self.settings.ecourts_case_paisa)

        data = (response.payload or {}).get("data") or {}
        case = data.get("courtCaseData") or {}
        guard = ParseGuard("ecourts.case_detail")
        guard.expect("case data", raw=data, parsed=case,
                     hint="data.courtCaseData")
        guard.expect_any(
            "case status", raw=case,
            parsed=[case.get("caseStatus"), case.get("disposalType")],
            hint="caseStatus / disposalType · whether the matter is live",
        )
        guard.raise_if_gaps(payload=response.payload)

        files = _files_list(data)
        labels = dig(data, "descriptions", "enumLookup", default={}) or {}

        return {
            "cnr": cnr,
            # ---- what an analyst needs to judge the matter ---------------
            "case_number": case.get("caseNumber"),
            "case_type": case.get("caseType"),
            "case_type_label": _label(labels, "caseType", case.get("caseType")),
            "case_type_sub": _tidy(case.get("caseTypeSub")),
            "case_status": case.get("caseStatus"),
            #: DISPOSED is not the same as cleared. The disposal TYPE is the
            #: fact — "DISMISSED_AS_WITHDRAWN" and a conviction are both
            #: "disposed", and only one of them is good news for a vendor.
            "disposal_type": case.get("disposalType"),
            "disposal_type_raw": case.get("disposalTypeRaw"),
            "contested_status": case.get("contestedStatus"),
            "is_pending": str(case.get("caseStatus") or "").upper() == "PENDING",
            "petitioners": case.get("petitioners") or [],
            "respondents": case.get("respondents") or [],
            "acts_and_sections": case.get("actsAndSections"),
            "case_category": case.get("caseCategoryFacetPath"),
            "has_fir": bool(case.get("firDetails")),
            "police_station": dig(case, "firDetails", "policeStation"),
            # ---- timeline ------------------------------------------------
            "filing_date": case.get("filingDate"),
            "registration_date": case.get("registrationDate"),
            "first_hearing_date": case.get("firstHearingDate"),
            "next_hearing_date": case.get("nextHearingDate"),
            "decision_date": case.get("decisionDate"),
            "case_duration_days": case.get("caseDurationDays"),
            # ---- court ---------------------------------------------------
            "court_name": case.get("courtName"),
            "court_code": case.get("courtCode"),
            "court_label": _label(labels, "courtCode", case.get("cnrCourtCode")),
            "state": case.get("state"),
            "district": case.get("district"),
            # ---- documents -----------------------------------------------
            "judgment_orders": case.get("judgmentOrders") or [],
            "interim_orders": case.get("interimOrders") or [],
            "order_count": case.get("orderCount"),
            "judgment_count": case.get("judgmentCount"),
            "hearing_count": case.get("hearingCount"),
            "files": files,
            #: True when the response already carries provider MODEL output.
            #: It does so on this endpoint, unasked. Scope decision #1 says
            #: "no LLM anywhere" — that rule needs restating as "VBC runs no
            #: model" or this response violates it on arrival.
            "provider_model_content": any(
                isinstance(f, dict) and f.get("aiAnalysis") for f in files
            ),
            "data_last_modified": dig(data, "entityInfo", "dateModified"),
            "court_case_data": case,
        }

    def order_download(self, cnr: str, filename: str) -> dict:
        """File reference for one order. Returns metadata, not the bytes."""
        self._require_key()
        response = self.request(
            "GET", self._url(f"case/{_cnr(cnr)}/order/{filename}"),
            headers=self._headers(),
        )
        return (response.payload or {}).get("data") or {}

    def order_markdown(self, cnr: str, filename: str, *, signed: bool = True) -> dict:
        """Order as markdown plus a base64 PDF.

        ``signed=True`` returns the watermarked certified true copy. The
        provider's own note is worth heeding: the full order text is already
        in ``case_detail`` under ``files[].markdownContent``, so this is only
        worth paying for when the watermarked PDF is needed for submission.
        """
        self._require_key()
        response = self.request(
            "GET", self._url(f"case/{_cnr(cnr)}/order-md/{filename}"),
            headers=self._headers(),
            params=None if signed else {"signed": "false"},
        )
        data = (response.payload or {}).get("data") or {}
        return {
            "cnr": cnr,
            "filename": filename,
            "signed": signed,
            # May be null when conversion failed — documented behaviour, and
            # NOT the same as an order with no text.
            "markdown": data.get("markdownContent"),
            "markdown_available": data.get("markdownContent") is not None,
            "pdf_base64": data.get("pdfBase64"),
        }

    def order_ai(self, cnr: str, filename: str) -> dict:
        """Extracted text plus the provider's structured analysis.

        NOTE FOR VBC. Locked scope decision #1 is "no LLM anywhere", and the
        report is deterministic template assembly. The analysis returned here
        is model-generated — on eCourts' side, not ours. That is defensible
        (it is a sourced provider field like any other), but it is a decision
        to make deliberately rather than discover later, which is why this
        method is available and no check calls it by default.
        """
        self._require_key()
        response = self.request(
            "GET", self._url(f"case/{_cnr(cnr)}/order-ai/{filename}"),
            headers=self._headers(),
        )
        data = (response.payload or {}).get("data") or {}
        core = dig(data, "aiAnalysis", "foundational_metadata",
                   "core_case_identifiers", default={}) or {}
        return {
            "cnr": cnr,
            "filename": filename,
            "extracted_text": data.get("extractedText"),
            "case_type": core.get("case_type"),
            "case_sub_type": core.get("case_sub_type"),
            "court_name": core.get("court_name"),
            "case_number_primary": core.get("case_number_primary"),
            "ai_analysis": data.get("aiAnalysis") or {},
            #: Flagged so the report can distinguish provider-model output
            #: from registry fact.
            "provider_model_generated": True,
        }

    def case_refresh(self, cnr: str) -> dict:
        """Ask the provider to re-pull one case. Async — 202, then wait."""
        self._require_key()
        response = self.request("POST", self._url(f"case/{_cnr(cnr)}/refresh"),
                                headers=self._headers())
        data = (response.payload or {}).get("data") or {}
        return {
            "cnr": cnr,
            "status": data.get("status"),
            "estimated_time": data.get("estimatedTime"),
            "message": data.get("message"),
        }

    def bulk_refresh(self, cnrs: list[str]) -> dict:
        self._require_key()
        response = self.request(
            "POST", self._url("case/bulk-refresh"),
            headers=self._headers({"Content-Type": "application/json"}),
            json={"cnrs": [_cnr(c) for c in cnrs]},
        )
        data = (response.payload or {}).get("data") or {}
        # Three outcomes, not two — an invalid CNR is neither refreshed nor
        # queued, and dropping that list loses the only sign of a bad input.
        return {
            "refreshed": data.get("refreshed") or [],
            "queued": data.get("queued") or [],
            "invalid": data.get("invalid") or [],
        }

    def bulk_refresh_status(self, cnrs: list[str]) -> dict:
        self._require_key()
        response = self.request(
            "POST", self._url("case/bulk-refresh-status"),
            headers=self._headers({"Content-Type": "application/json"}),
            json={"cnrs": list(cnrs)},
        )
        data = (response.payload or {}).get("data") or {}
        rows = data.get("results") or []
        return {
            "results": [r for r in rows if isinstance(r, dict)],
            "by_cnr": {r.get("cnr"): r.get("status")
                       for r in rows if isinstance(r, dict)},
        }

    def enums(self, types: str = "caseStatus,benchType") -> dict:
        """Live enum reference. Free of charge, but authenticated.

        The docs show this with no Authorization header; the server returns
        401 INVALID_TOKEN without one. Confirmed by direct call.

        The docs also show data.<type>[]; the live shape is
        data.enums.<type>[]. Reading `data` directly counted enumCount and
        generatedAt as enum groups and reported 3 where there were 2.
        """
        self._require_key()
        response = self.request("GET", self._url("enums"),
                                headers=self._headers(), params={"types": types})
        data = (response.payload or {}).get("data") or {}
        return data.get("enums") or {}

    # -----------------------------------------------------------------
    # Cause list
    # -----------------------------------------------------------------

    def court_structure(self, state: str | None = None,
                        district_code: str | None = None) -> list:
        """States, then districts, then complexes. Free, no auth.

        High courts appear AS DISTRICTS (``{"districtCode": "HC"}``) and the
        Supreme Court as a state (``{"state": "SC"}``). Filtering on the
        assumption that a district is a district drops both.
        """
    def court_structure(self, state: str | None = None,
                        district_code: str | None = None) -> list:
        """States, then districts, then complexes. Free of charge, but authenticated.

        The docs describe this as needing no auth; the server returns
        401 INVALID_TOKEN without a bearer token.

        High courts appear AS DISTRICTS (``{"districtCode": "HC"}``) and the
        Supreme Court as a state (``{"state": "SC"}``). Filtering on the
        assumption that a district is a district drops both.
        """
        self._require_key()
        path = "causelist/court-structure/states"
        if state:
            path += f"/{state}/districts"
            if district_code:
                path += f"/{district_code}/complexes"
        response = self.request("GET", self._url(path),
                                headers=self._headers())
        payload = response.payload
        if isinstance(payload, list):
            return payload
        return (payload or {}).get("data") or []
        payload = response.payload
        if isinstance(payload, list):
            return payload
        return (payload or {}).get("data") or []

    
    def causelist_search(self, query: str, *, state: str | None = None,
                         limit: int = 100, offset: int = 0) -> dict:
        """Scheduled hearings naming a party.

        Uses `litigant`, not `q`: `q` is full-text across case numbers,
        parties AND advocates, so it matches a company whose name merely
        resembles an advocate's. `litigant` is still a FUZZY match — a
        search for "RELIANCE INDUSTRIES" returns Reliance Jio, Reliance
        Chemotex, Reliance Infratel and a petrol-pump branch manager — so
        these rows are evidence an analyst reads, never a scored count.

        Pagination is carried through rather than discarded. The provider
        caps `limit` at 200; reporting the page length as the total would
        let a truncated list read as a complete one.
        """
        self._require_key()
        params: dict = {"litigant": query, "limit": limit, "offset": offset}
        if state:
            params["state"] = state
        response = self.request("GET", self._url("causelist/search"),
                                headers=self._headers(), params=params)
        data = (response.payload or {}).get("data") or {}
        rows = data.get("results") or []
        labels = data.get("enumDescriptions") or {}
        page = [_blank_unknown(r) for r in rows if isinstance(r, dict)]
        for row in page:
            # "WBHW01" means nothing in a report. The provider ships the
            # readable name in the same payload; it was being discarded.
            row["courtLabel"] = labels.get(row.get("court")) or row.get("court")
        cap = data.get("limit") or limit
        return {
            # The provider echoes `query` only for `q`, so it comes back
            # empty on a `litigant` search — keep what we actually asked.
            "query": query,
            "results": page,
            "count": len(page),
            "returned_count": data.get("returnedCount"),
            "limit": cap,
            "offset": data.get("offset", offset),
            "truncated": len(page) >= cap,
            "filters_applied": data.get("filters"),
        }
    def cnr_causelist_batch(self, cnrs: list[str]) -> dict:
        """Which of these cases are listed for hearing, and when.

        An upcoming listing says the matter is ACTIVE — a stronger signal
        than a historical case count, which may all be long disposed.
        """
        self._require_key()
        response = self.request(
            "POST", self._url("causelist/cnr/batch"),
            headers=self._headers({"Content-Type": "application/json"}),
            json={"cnrs": [_cnr(c) for c in cnrs]},
        )
        rows = (response.payload or {}).get("data") or []
        listed = [r for r in rows if isinstance(r, dict) and r.get("hasCauselist")]
        return {
            "rows": [r for r in rows if isinstance(r, dict)],
            "listed": listed,
            "listed_count": len(listed),
            "checked": len(rows),
        }

    def available_dates(self, **filters) -> list:
        """Which dates have cause-list data. Free with auth."""
        self._require_key()
        params = {k: v for k, v in filters.items() if not is_blank(v)}
        response = self.request("GET", self._url("causelist/available-dates"),
                                headers=self._headers(), params=params or None)
        return (response.payload or {}).get("data") or []

    # -----------------------------------------------------------------
    # LegalCheck — listing
    # -----------------------------------------------------------------

    def list_legal_checks(self, *, status: str | None = None,
                          page: int = 1, page_size: int = 20) -> dict:
        self._require_key()
        params: dict = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        response = self.request("GET", self._url("legal-check"),
                                headers=self._headers(), params=params)
        data = (response.payload or {}).get("data") or {}
        return {"items": data.get("items") or [], "raw": data}


class LegalCheckPending(ProviderUnavailable):
    """The job is still running. Carries the code so it can be resumed."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------


def _as_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _matches(data) -> list[dict]:
    """The matched cases, under whichever key the report uses.

    Kept tolerant because the report body below `risk_band` was not fully
    published — and an empty list here is NOT treated as "no litigation",
    since ParseGuard has already established the report itself parsed.
    """
    if not isinstance(data, dict):
        return []
    for key in ("matches", "results", "cases", "findings", "hits"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


CNR_LEN = 16


def _cnr(value: str) -> str:
    """Validate a CNR before it becomes a URL path segment."""
    text = str(value or "").strip().upper()
    if len(text) != CNR_LEN or not text[:4].isalpha() or not text[4:].isdigit():
        raise ValueError(
            f"'{value}' is not a CNR. Expected 4 letters then 12 digits, "
            f"e.g. DLHC010001232024."
        )
    return text


def _case_row(row: dict) -> dict:
    """One search hit, with the two fields the scoring must not lose.

    ``petitioners`` and ``respondents`` are what say WHICH SIDE the vendor
    was on. A company recovering a debt and a company being wound up both
    appear as "a case"; only the parties distinguish them, and a finding
    that drops them cannot be reviewed.
    """
    return {
        "cnr": row.get("cnr"),
        "case_type": row.get("caseType"),
        "case_status": row.get("caseStatus"),
        "filing_date": row.get("filingDate"),
        "next_hearing_date": row.get("nextHearingDate"),
        "judges": row.get("judges") or [],
        "petitioners": row.get("petitioners") or [],
        "respondents": row.get("respondents") or [],
    }


def _blank_unknown(row: dict) -> dict:
    """Turn the provider's literal "UNKNOWN" into None.

    Cause-list rows carry "UNKNOWN" as a real string value. Left alone it
    passes every truthiness test and reaches a report as though it were a
    court name.
    """
    return {
        k: (None if isinstance(v, str) and v.strip().upper() == "UNKNOWN" else v)
        for k, v in row.items()
    }


def _files_list(data) -> list:
    """The order-document array, however it is wrapped.

    Live responses nest it: ``data.files.files``. The reference examples
    showed a bare list. Reading the object as a list is not a crash — it
    yields a dict that iterates over its KEYS, so the failure is silent.
    """
    files = data.get("files") if isinstance(data, dict) else None
    if isinstance(files, dict):
        inner = files.get("files")
        return inner if isinstance(inner, list) else []
    return files if isinstance(files, list) else []


def _label(lookup: dict, field: str, code) -> str | None:
    """Human label for an enum code, from the response's own dictionary."""
    if not isinstance(lookup, dict) or code is None:
        return None
    table = lookup.get(field)
    return table.get(str(code)) if isinstance(table, dict) else None


def _tidy(value) -> str | None:
    """Strip the placeholder tail off values like "Criminal Procedure Code. - ---"."""
    if is_blank(value):
        return None
    text = str(value).strip()
    for junk in (" - ---", " - --", " ---"):
        if text.endswith(junk):
            text = text[: -len(junk)].strip()
    return text.rstrip(".- ").strip() or None