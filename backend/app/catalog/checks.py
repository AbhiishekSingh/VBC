"""The check catalog: all 32 checks, including the 9 that have no provider.

The unconfigured checks are NOT omitted. They are seeded with
``state=NOT_CONFIGURED`` so that a gap in coverage is a visible row rather
than an absence — in an audit product, silence must never look like a clean
result. Enabling GST later is an adapter plus a state flag, not a migration.

Cost units are never summed together: rupees (FileSure), credits (WhoisXML)
and screenshot credits are three separate budgets.
"""

from __future__ import annotations

from app.domain.types import (
    CheckDefinition,
    CheckParam,
    CheckState,
    Provider,
)

ACTIVE = CheckState.ACTIVE
HOOK = CheckState.NOT_CONFIGURED

FS, WX, FA, EC, AR, IH, NONE = (
    Provider.FILESURE,
    Provider.WHOISXML,
    Provider.FINAGG,
    Provider.ECOURTS,
    Provider.ARCHIVE,
    Provider.IN_HOUSE,
    Provider.NONE,
)


class CheckGroup:
    MCA = "mca"
    DOMAIN = "domain"
    WEB = "web"
    INTERNAL = "internal"
    ADMIN = "admin"
    TAX = "tax"
    SANCTIONS = "sanctions"
    REP = "rep"


CHECK_GROUPS: tuple[dict, ...] = (
    {"id": CheckGroup.MCA, "name": "Company Registry — MCA", "source": "FileSure", "mark": "M", "configured": True},
    {"id": CheckGroup.DOMAIN, "name": "Website & Domain Ownership", "source": "WhoisXML", "mark": "D", "configured": True},
    {"id": CheckGroup.WEB, "name": "Web Presence History", "source": "archive.org · free", "mark": "W", "configured": True},
    {"id": CheckGroup.INTERNAL, "name": "Internal Checks", "source": "our database · free", "mark": "I", "configured": True},
    {"id": CheckGroup.ADMIN, "name": "Account & Data Freshness", "source": "FileSure · admin", "mark": "A", "configured": True},
    {"id": CheckGroup.TAX, "name": "Identity & Tax", "source": "FinAGG GSP · GST", "mark": "G", "configured": True},
    {"id": CheckGroup.SANCTIONS, "name": "Sanctions & Watchlists", "source": "not configured", "mark": "—", "configured": False},
    {"id": CheckGroup.REP, "name": "Litigation & Reputation", "source": "eCourtsIndia · LegalCheck", "mark": "L", "configured": True},
)


def _p(key: str, label: str, **kw) -> CheckParam:
    return CheckParam(key=key, label=label, **kw)


CHECKS: tuple[CheckDefinition, ...] = (
    # ================= Group M · Company Registry (FileSure) ==============
    CheckDefinition(
        id="master",
        group=CheckGroup.MCA,
        name="Company master",
        endpoint="GET /v1/companies/{cin}?idType=cin",
        provider=FS,
        note="Status, incorporation date, capital, registered address",
        cost_paisa=500,    # ₹5.00  companies.master
        feeds=("S1", "S2"),
        params=(
            _p("cin", "CIN", required=True, from_vendor="cin",
               placeholder="U21029MH2013PTC245119"),
            _p("idType", "Look up by", type="select",
               options=("cin", "name"), default="cin"),
        ),
    ),
    CheckDefinition(
        id="resolve",
        group=CheckGroup.MCA,
        name="Resolve company name → CIN",
        endpoint="GET /v1/companies/resolve?q={name}",
        provider=FS,
        note="Only needed when the client submits a name rather than a CIN",
        cost_paisa=500,    # ₹5.00  companies.resolve
        params=(
            _p("q", "Company name to search", required=True, from_vendor="name",
               placeholder="e.g. Meridian Packaging"),
            _p("state", "State", placeholder="Maharashtra"),
            _p("city", "City", placeholder="Mumbai"),
            _p("limit", "Max results", type="number", default="10"),
        ),
    ),
    CheckDefinition(
        id="dirs",
        group=CheckGroup.MCA,
        name="Directors list",
        endpoint="included in company master",
        provider=FS,
        note="DIN, name, appointment date, other directorships",
        requires=("master",),
    ),
    CheckDefinition(
        id="dresolve",
        group=CheckGroup.MCA,
        name="Resolve director name → DIN",
        endpoint="GET /v1/directors/resolve?q={name}",
        provider=FS,
        note=(
            "Needed when a client gives a director's name rather than a DIN. "
            "totalDirectorshipCount is a free red-flag metric — an unusually "
            "high count is the classic mass-director pattern."
        ),
        cost_paisa=500,    # ₹5.00  directors.resolve
        params=(
            _p("q", "Director name to search", required=True,
               placeholder="e.g. Amit Sharma"),
            _p("limit", "Max results", type="number", default="10"),
        ),
    ),
    CheckDefinition(
        id="dprof",
        group=CheckGroup.MCA,
        name="Director full profile",
        endpoint="GET /v1/directors/{din}",
        provider=FS,
        note="Full directorship history including cessation dates",
        cost_paisa=500,    # ₹5.00  directors.profile
        requires=("dirs",),
        params=(
            _p("din", "DIN", from_result="dirs",
               placeholder="blank = every director found on the company"),
        ),
    ),
    CheckDefinition(
        id="dcontact",
        group=CheckGroup.MCA,
        name="Director contact details",
        endpoint="GET /v1/directors/{din}/contact",
        provider=FS,
        note="Mobile and email as filed with MCA — number is returned masked",
        cost_paisa=5,      # ₹0.05  directors.contact (needs the ₹50 unlock)
        needs_director_unlock=True,
        requires=("dirs",),
        params=(
            _p("din", "DIN", from_result="dirs",
               placeholder="blank = every director found on the company"),
        ),
    ),
    CheckDefinition(
        id="charges",
        group=CheckGroup.MCA,
        name="Charges and secured loans",
        endpoint="included in company master",
        provider=FS,
        note="Open and satisfied charges, lender, amount",
        requires=("master",),
    ),
    CheckDefinition(
        id="filings",
        group=CheckGroup.MCA,
        name="Filing history",
        endpoint="GET /v1/companies/{cin}/filings",
        provider=FS,
        note="Filtered to AOC-4, MGT-7, CHG and ADT-1 forms",
        cost_paisa=500,    # ₹5.00  companies.filings.list
        requires=("master",),
        params=(
            _p("formId", "Form type", type="select",
               options=("All forms", "AOC-4", "MGT-7", "CHG-9", "CHG-4", "ADT-1"),
               default="All forms"),
            _p("year", "Year", type="number", placeholder="2024"),
            _p("limit", "Results per page", type="number", default="50"),
        ),
    ),
    CheckDefinition(
        id="download",
        group=CheckGroup.MCA,
        name="Filing document download",
        endpoint="GET /v1/companies/{cin}/filings/{filingId}/download",
        provider=FS,
        note="Source PDFs attached to the report as evidence",
        cost_paisa=5,      # ₹0.05  companies.filings.download
        needs_company_unlock=True,
        requires=("filings",),
        params=(
            _p("filingId", "Filing ID", required=True, from_result="filings",
               placeholder="flg_Ui2a1vIty…"),
        ),
    ),
    CheckDefinition(
        id="frefresh",
        group=CheckGroup.MCA,
        name="Refresh filings from MCA",
        endpoint="POST /v1/companies/{cin}/filings/refresh",
        provider=FS,
        note=(
            "₹5 filings-only refresh, distinct from the ₹150 full update. Has "
            "its own ~6h cooldown and can return fromCache:true — billing you "
            "for cached data with no fresh MCA pull. Check cooldownUntil first."
        ),
        cost_paisa=500,    # ₹5.00  companies.filings.refresh
        requires=("master",),
        params=(
            _p("cin", "CIN", required=True, from_vendor="cin",
               placeholder="U21029MH2013PTC245119"),
        ),
    ),
    CheckDefinition(
        id="fin",
        group=CheckGroup.MCA,
        name="Filed financial statements",
        endpoint="GET /v1/companies/{cin}/extractions/{form}/{year}",
        provider=FS,
        note=(
            "Government-filed XBRL — revenue, profit, net worth, cash flow. "
            "Reaching it is a THREE-step drill-down: available form types, "
            "then available years, then the filing itself. Year gaps in step 2 "
            "are a compliance signal, not an error."
        ),
        cost_paisa=5,      # ₹0.05  companies.extractions.data
        needs_company_unlock=True,
        requires=("master",),
        feeds=("N3",),
        params=(
            _p("formType", "Form", type="select",
               options=("AOC-4", "MGT-7", "PAS-3", "CHARGES"), default="AOC-4"),
            _p("year", "Year", type="number", placeholder="blank = latest filed"),
            _p("scope", "Scope", type="select",
               options=("standalone", "consolidated"), default="standalone"),
        ),
    ),
    # ================= Group D · Domain (WhoisXML) =========================
    CheckDefinition(
        id="whois",
        group=CheckGroup.DOMAIN,
        name="Domain ownership history",
        endpoint="GET /whois-history/api/v1",
        provider=WX,
        note="Registrant, registrar and nameserver changes over time",
        credits=50,
        feeds=("S3",),
        params=(
            _p("domainName", "Domain", required=True, from_vendor="domain",
               placeholder="example.com"),
            _p("mode", "Mode", type="select",
               options=("purchase — full records (50 credits)", "preview — count only"),
               default="purchase — full records (50 credits)"),
        ),
    ),
    CheckDefinition(
        id="reput",
        group=CheckGroup.DOMAIN,
        name="Domain trust score",
        endpoint="GET /domain-reputation/api/v2",
        provider=WX,
        note="0–100 reputation with WHOIS and SSL sanity checks",
        credits=1,
        params=(
            _p("domainName", "Domain", required=True, from_vendor="domain",
               placeholder="example.com"),
            _p("mode", "Depth", type="select", options=("fast", "full"), default="fast"),
        ),
    ),
    CheckDefinition(
        id="ssl",
        group=CheckGroup.DOMAIN,
        name="SSL certificate",
        endpoint="GET /ssl-certificates/api/v1",
        provider=WX,
        note="Issuer, validity window, wildcard coverage — current certificate only",
        credits=1,
        params=(
            _p("domainName", "Domain", required=True, from_vendor="domain",
               placeholder="example.com"),
        ),
    ),
    CheckDefinition(
        id="rwhois",
        group=CheckGroup.DOMAIN,
        name="Other domains by the same owner",
        endpoint="POST /reverse-whois/api/v2",
        provider=WX,
        note="Portfolio check — needs a registrant value from ownership history",
        credits=1,
        requires=("whois",),
        params=(
            _p("searchTerm", "Registrant email / name / organisation",
               from_result="whois",
               placeholder="blank = taken from the ownership history result"),
            _p("searchType", "Search", type="select",
               options=("current", "historic"), default="current"),
        ),
    ),
    CheckDefinition(
        id="shot",
        group=CheckGroup.DOMAIN,
        name="Website screenshot",
        endpoint="GET /website-screenshot/api/v1",
        provider=WX,
        note="Live dated image embedded in the report",
        screenshots=1,
        params=(
            _p("url", "Full website URL", required=True, from_vendor="website",
               placeholder="https://example.com"),
            _p("imageOutputFormat", "Image format", type="select",
               options=("JPG", "PNG"), default="JPG"),
        ),
    ),
    # ================= Group W · Web presence (archive.org, free) =========
    CheckDefinition(
        id="avail",
        group=CheckGroup.WEB,
        name="Website existence check",
        endpoint="GET /wayback/available?url={domain}",
        provider=AR,
        note="Has the site ever been archived, and when was it last captured",
        params=(
            _p("url", "Domain", required=True, from_vendor="domain",
               placeholder="example.com"),
            _p("timestamp", "Closest to date", type="date"),
        ),
    ),
    CheckDefinition(
        id="cdx",
        group=CheckGroup.WEB,
        name="Full web presence timeline",
        endpoint="GET /cdx/search/cdx",
        provider=AR,
        note="When the site went live, outage periods, content-change events",
        feeds=("S3",),
        params=(
            _p("url", "Domain", required=True, from_vendor="domain",
               placeholder="example.com"),
            _p("matchType", "Scope", type="select",
               options=("domain — all pages", "prefix", "exact — homepage only"),
               default="domain — all pages"),
            _p("limit", "Max snapshots", type="number", default="50"),
            _p("from", "From date", type="date"),
            _p("to", "To date", type="date"),
        ),
    ),
    CheckDefinition(
        id="mentions",
        group=CheckGroup.WEB,
        name="Additional archive mentions",
        endpoint="GET /advancedsearch.php",
        provider=AR,
        note="Usually empty for smaller companies — every hit needs relevance review",
        params=(
            _p("q", "Search term", required=True, from_vendor="name",
               placeholder="company name"),
            _p("rows", "Max results", type="number", default="50"),
        ),
    ),
    # ================= Group I · Internal (in-house, free) ================
    CheckDefinition(
        id="dup",
        group=CheckGroup.INTERNAL,
        name="Duplicate vendor",
        endpoint="in-house",
        provider=IH,
        note="Matching GST, PAN or address already in the vendor master",
    ),
    CheckDefinition(
        id="rp",
        group=CheckGroup.INTERNAL,
        name="Related party",
        endpoint="in-house, over MCA director data",
        provider=IH,
        note="Shared directors or addresses with an existing vendor",
        requires=("dirs",),
    ),
    CheckDefinition(
        id="conflict",
        group=CheckGroup.INTERNAL,
        name="Director conflict of interest",
        endpoint="in-house, over MCA director data",
        provider=IH,
        note="Overlap between vendor directors and employee records",
        requires=("dirs",),
        feeds=("A3",),
    ),
    # ================= Group A · Admin (FileSure housekeeping) ============
    CheckDefinition(
        id="ustatus",
        group=CheckGroup.ADMIN,
        name="Unlock status check",
        endpoint="GET /v1/companies/{cin}/unlock",
        provider=FS,
        note="Free. The unlock lifecycle runs this before any paid unlock "
             "whether or not it is ticked; tick it to see the result on the "
             "findings page",
        # NOT always=True, and NOT preselected. Nothing in this catalog is
        # selected on the analyst's behalf.
        #
        # It was forced on to protect against a duplicate ₹330 unlock. That
        # protection does not actually live here: CheckRunner._ensure_unlock
        # calls the free GET through FileSureProvider.ensure_unlocked() at
        # STEP 2, before any paid POST, regardless of what was selected. So
        # forcing the checkbox bought no safety — it only guaranteed a row
        # on the findings page, at the cost of the analyst not choosing it.
        #
        # If this is ever made deselectable-but-load-bearing again, check
        # _ensure_unlock first: THAT is the cost control.
        admin=True,
        params=(
            _p("cin", "CIN", required=True, from_vendor="cin",
               placeholder="U21029MH2013PTC245119"),
        ),
    ),
    CheckDefinition(
        id="refresh",
        group=CheckGroup.ADMIN,
        name="Refresh company data from MCA",
        endpoint="POST /v1/companies/{cin}/update",
        provider=FS,
        note="Async job, ~15 seconds. 48-hour cooldown before it can run again",
        cost_paisa=15000,  # ₹150   companies.update
        admin=True,
        params=(
            _p("cin", "CIN", required=True, from_vendor="cin",
               placeholder="U21029MH2013PTC245119"),
        ),
    ),
    CheckDefinition(
        id="usage",
        group=CheckGroup.ADMIN,
        name="Wallet balance and usage",
        endpoint="GET /v1/account/usage",
        provider=FS,
        note="Spend by endpoint over the last 30 days",
        admin=True,
    ),
    # ================= Group G · GST (FinAGG GSP) =========================
    #
    # Two calls, both on the Common APIs, both needing no taxpayer consent.
    #
    # FinAGG's other eleven endpoints — every Taxpayer API and both File
    # Download calls — authenticate AS THE TAXPAYER with an OTP sent to
    # their registered mobile. A vendor under assessment does not forward
    # an OTP, so those endpoints are not in this catalog and not in the
    # adapter. Composition status in particular is read from search.dty
    # rather than from the OTP-gated /returns/cmp endpoint, which would
    # otherwise be the obvious source for C3.
    CheckDefinition(
        id="gst",
        group=CheckGroup.TAX,
        name="GST registration and status",
        endpoint="GET /commonapi/{v}/search?action=TP",
        provider=FA,
        note="Registration status, taxpayer type, constitution, principal address",
        feeds=("C1", "C3", "C4", "C5"),
        params=(
            _p("gstin", "GSTIN", required=True, from_vendor="gst",
               placeholder="27AAACX1234C1ZV"),
        ),
    ),
    CheckDefinition(
        id="gstret",
        group=CheckGroup.TAX,
        name="GST return filing history",
        endpoint="GET /commonapi/{v}/returns?action=RETTRACK",
        provider=FA,
        note="Filed periods and dates — no invoice data, no consent needed",
        requires=("gst",),
        feeds=("C2",),
        params=(
            _p("gstin", "GSTIN", required=True, from_vendor="gst",
               placeholder="27AAACX1234C1ZV"),
            _p("fy", "Financial year", placeholder="2025-26"),
        ),
    ),
    CheckDefinition(
        id="courtsearch",
        group=CheckGroup.REP,
        name="Court case search",
        endpoint="GET /search",
        provider=EC,
        note="Cases naming this party, with petitioner/respondent so the side is visible",
        params=(
            _p("parties", "Party name", required=True, from_vendor="legal_name",
               placeholder="MERIDIAN PACKAGING PRIVATE LIMITED"),
            _p("courtCodes", "Court codes", placeholder="DLHC01"),
            _p("filingDateFrom", "Filed since", type="date"),
        ),
    ),
    CheckDefinition(
        id="courthearing",
        group=CheckGroup.REP,
        name="Upcoming hearings",
        endpoint="POST /causelist/cnr/batch",
        provider=EC,
        note="Which matched cases are listed for hearing — active, not merely historical",
        requires=("courtsearch",),
    ),
    CheckDefinition(
        id="casedetail",
        group=CheckGroup.REP,
        name="Case detail",
        endpoint="GET /case/{cnr}",
        provider=EC,
        note="Full record for one case, including its order list",
        params=(
            _p("cnr", "CNR", required=True, from_result="courtsearch",
               placeholder="DLHC010001232024"),
        ),
    ),
    CheckDefinition(
        id="courtorders",
        group=CheckGroup.REP,
        name="Order text",
        endpoint="GET /case/{cnr}/order-md/{file}",
        provider=EC,
        note="What the orders actually say — capped by VBC_ECOURTS_MAX_ORDERS",
        requires=("casedetail",),
    ),
    CheckDefinition(
        id="courtorderai",
        group=CheckGroup.REP,
        name="Order analysis (provider model)",
        endpoint="GET /case/{cnr}/order-ai/{file}",
        provider=EC,
        note="PROVIDER-GENERATED analysis, not registry fact. See scope decision 1.",
        requires=("casedetail",),
    ),
    CheckDefinition(
        id="causelist",
        group=CheckGroup.REP,
        name="Cause list search",
        endpoint="GET /causelist/search",
        provider=EC,
        note="Scheduled hearings naming this party — fuzzy match, analyst confirms identity",
        params=(
            _p("litigant", "Party name", required=True, from_vendor="legal_name"),
            _p("state", "State code", placeholder="MH"),
            _p("limit", "Max rows", type="number", default="100"),
            _p("offset", "Skip rows", type="number", default="0"),
        ),
    ),
    # ---- Admin · reference data and freshness. Feed no parameter and no
    # ---- risk rule, exactly like FileSure's wallet check.
    CheckDefinition(
        id="courtcaps",
        group=CheckGroup.ADMIN,
        name="Court search capabilities",
        endpoint="GET /search/capabilities",
        provider=EC,
        note="Which filters and name-match modes Case Search supports. Free.",
        admin=True,
    ),
    CheckDefinition(
        id="courtenums",
        group=CheckGroup.ADMIN,
        name="Court enum reference",
        endpoint="GET /enums",
        provider=EC,
        note="Live case-status and bench-type codes. Free of charge, authenticated.",
        admin=True,
        params=(_p("types", "Enum types", default="caseStatus,benchType"),),
    ),
    CheckDefinition(
        id="courtstructure",
        group=CheckGroup.ADMIN,
        name="Court structure",
        endpoint="GET /causelist/court-structure/…",
        provider=EC,
        note="States, districts and complexes. High courts appear as districts.",
        admin=True,
        params=(
            _p("state", "State code", placeholder="DL"),
            _p("districtCode", "District code", placeholder="1"),
        ),
    ),
    CheckDefinition(
        id="courtdates",
        group=CheckGroup.ADMIN,
        name="Cause list available dates",
        endpoint="GET /causelist/available-dates",
        provider=EC,
        note="Which dates hold cause-list data. Free with auth.",
        admin=True,
        params=(
            _p("state", "State code", placeholder="DL"),
            _p("districtCode", "District code"),
            _p("courtComplexCode", "Complex code"),
            _p("courtNo", "Court room"),
            _p("court", "Court identifier"),
        ),
    ),
    CheckDefinition(
        id="caserefresh",
        group=CheckGroup.ADMIN,
        name="Refresh a case from source",
        endpoint="POST /case/{cnr}/refresh",
        provider=EC,
        note="Async — queues a re-pull; the provider quotes 5-10 minutes",
        admin=True,
        params=(_p("cnr", "CNR", required=True, from_result="courtsearch"),),
    ),
    CheckDefinition(
        id="courtchecks",
        group=CheckGroup.ADMIN,
        name="Legal checks on this account",
        endpoint="GET /legal-check",
        provider=EC,
        note="Every legal check submitted, with its risk band. Free.",
        admin=True,
        params=(
            _p("status", "Status", type="select",
               options=("", "completed", "running", "failed"), default="completed"),
            _p("page_size", "Rows", type="number", default="20"),
        ),
    ),
    # ================= Hooks · defined, no provider wired up ==============
    CheckDefinition(
        id="pan", group=CheckGroup.TAX, name="PAN verification",
        endpoint="provider not selected", provider=NONE, state=HOOK,
        note="Identity substantiation",
    ),
    CheckDefinition(
        id="ofac", group=CheckGroup.SANCTIONS, name="OFAC / UN consolidated lists",
        endpoint="provider not selected", provider=NONE, state=HOOK,
    ),
    CheckDefinition(
        id="eusanc", group=CheckGroup.SANCTIONS, name="EU consolidated sanctions",
        endpoint="provider not selected", provider=NONE, state=HOOK,
    ),
    CheckDefinition(
        id="rbi", group=CheckGroup.SANCTIONS, name="RBI defaulter list",
        endpoint="provider not selected", provider=NONE, state=HOOK,
    ),
    CheckDefinition(
        id="news", group=CheckGroup.REP, name="Adverse news scan",
        endpoint="provider not selected", provider=NONE, state=HOOK,
    ),
    # ---- Litigation · eCourtsIndia LegalCheck ------------------------
    #
    # NOT case search. A name-based court search is noisy in both
    # directions, and a fixed penalty on a fuzzy name match occasionally
    # condemns the wrong company with nothing to show the analyst that is
    # what happened. LegalCheck returns identity_confidence beside the
    # risk band, which is what makes the finding defensible.
    #
    # Covers Supreme Court, 37 High Courts, District Courts, NCLT, NCLAT.
    CheckDefinition(
        id="court",
        group=CheckGroup.REP,
        name="Litigation exposure",
        endpoint="POST /legal-check → GET /legal-check/{code}/report",
        provider=EC,
        state=HOOK,
        note=("Risk band with an identity-confidence score. NOT CONFIGURED: "
              "POST /legal-check returns 400 VALIDATION_ERROR with an empty "
              "details[] on every documented body shape, and the submit "
              "endpoint is absent from the published API docs. Awaiting the "
              "schema from eCourts. /legal-check/models confirms the account "
              "has model eCI-1.2 with company support, so this is a contract "
              "gap, not an entitlement one."),
        params=(
            _p("subjectName", "Legal name to search", required=True,
               from_vendor="legal_name",
               placeholder="MERIDIAN PACKAGING PRIVATE LIMITED"),
            _p("subjectType", "Subject", type="select",
               options=("company", "individual"), default="company"),
        ),
    ),
    CheckDefinition(
        id="reviews", group=CheckGroup.REP, name="Online reviews",
        endpoint="provider not selected", provider=NONE, state=HOOK,
    ),
    CheckDefinition(
        id="dirlist", group=CheckGroup.REP, name="Business directory presence",
        endpoint="provider not selected", provider=NONE, state=HOOK,
    ),
)

CHECKS_BY_ID: dict[str, CheckDefinition] = {c.id: c for c in CHECKS}

#: One-time unlock prices, in paisa, from the account's own pricing
#: table effective 24 Aug 2026.
#:
#: These were 22_000 and 1_000, and the comment that stood here asserted
#: the evaluation report's ₹330 "is wrong". The report was right. The
#: figures here had been inferred from a SANDBOX usage response, where
#: nothing real is charged — so the estimate shown to an analyst before
#: a run understated a company unlock by ₹110 and a director unlock by
#: 5x. See app/providers/filesure.py for the full price table.
COMPANY_UNLOCK_PAISA = 33_000  # ₹330
DIRECTOR_UNLOCK_PAISA = 5_000  # ₹50


def check(check_id: str) -> CheckDefinition:
    try:
        return CHECKS_BY_ID[check_id]
    except KeyError:
        raise KeyError(f"Unknown check: {check_id!r}") from None


def resolve_dependencies(check_id: str) -> list[str]:
    """``check_id`` plus every prerequisite it needs, transitively.

    Ticking a check auto-enables what it depends on: ``fin`` cannot run
    without ``master``, because it needs the CIN that master resolves.
    """
    out: list[str] = [check_id]
    for req in check(check_id).requires:
        for dep in resolve_dependencies(req):
            if dep not in out:
                out.append(dep)
    return out


def dependents(check_id: str) -> list[str]:
    """Checks that would be orphaned if ``check_id`` were deselected."""
    return [c.id for c in CHECKS if check_id in c.requires]


def expand_selection(selected: list[str]) -> list[str]:
    """A selection with every transitive prerequisite folded in."""
    out: list[str] = []
    for cid in selected:
        for dep in resolve_dependencies(cid):
            if dep not in out:
                out.append(dep)
    return out


#: 34 before GST. The FinAGG integration replaced the single `gst` hook
#: with two live checks — `gst` (search) and `gstret` (returns metadata) —
#: because the two facts come from two endpoints, so 35 checks and one
#: fewer hook.
assert len(CHECKS) == 47, f"expected 47 checks, got {len(CHECKS)}"
#: 8, not 7: `court` went back to a hook on 2026-09-08 when LegalCheck
#: submit could not be made to accept any request body. The other twelve
#: eCourts checks are live, so litigation EVIDENCE still reaches the
#: analyst — only the scored band is missing, and it says so.
assert sum(1 for c in CHECKS if not c.is_configured) == 8