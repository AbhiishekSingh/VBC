"""Request and response shapes.

These mirror `frontend/src/api/contract.ts` field for field, including its
camelCase naming — the contract was written first because the signed-off
prototype is the specification, and the backend implements it rather than
inventing a second shape for the frontend to adapt to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CheckResultOut(ApiModel):
    #: The ROW id. Absent on older payloads and on anything constructed
    #: rather than read, so the screen must not key off it blindly — but
    #: a check now holds several results and "mark this one" and "delete
    #: this one" need to name which.
    id: int | None = None
    checkId: str
    status: str
    value: str = ""
    detail: str = ""
    #: The renderable middle tier — see `app.domain.facts`. Without this the
    #: parser's output stops dead at the API boundary: written to the
    #: database, never sent, and the screen has nothing between a one-line
    #: summary and twenty kilobytes of provider JSON. That was the original
    #: defect; omitting the field here recreates it exactly.
    #:
    #: `Any`, deliberately, and not a typed model: the shape is declared once
    #: in `contract.ts` as `CheckFacts` and validating it a second time here
    #: would mean two definitions that can disagree. Facts are also derived
    #: and never load-bearing, so a malformed blob must degrade to "no middle
    #: tier" rather than fail the whole vendor response.
    facts: Any | None = None
    rawResponse: Any | None = None
    costPaisa: int = 0
    fetchedAt: datetime | None = None

    #: The one result of this check that SCAN, the risk score and the
    #: report read. Exactly one per check, enforced by a partial unique
    #: index rather than by whoever remembers.
    isPrimary: bool = False

    #: What was asked, for THIS result — snapshotted when it ran.
    #: `vendor.inputs` holds one value per key, so it shows whatever was
    #: typed LAST; four runs against four directors would otherwise all
    #: claim the fourth director's number.
    inputs: dict[str, str] = {}

    #: SET ASIDE BY A PERSON. Null means the result is in force.
    #:
    #: Sent so Step 3 can grey the row and print who set it aside and
    #: why — the judgement is part of the evidence, not a filter applied
    #: before the evidence is handed over. An ignored result keeps its
    #: payload and its cost; it simply stops feeding the score.
    ignoredAt: datetime | None = None
    ignoredBy: str | None = None
    ignoreReason: str | None = None


class IgnoreIn(ApiModel):
    """Why this result is being set aside.

    REQUIRED, and `min_length` is doing real work. Ignoring moves a
    client-facing number, and "" would let that happen with no account
    of it — the same hole `decidedBy` left when the caller supplied it.
    A file that cannot say why a finding was set aside is not one
    anybody can defend a year later.
    """

    reason: str = Field(min_length=3)


class ManualEntryIn(ApiModel):
    key: str
    value: str
    type: str
    templateId: str | None = None
    note: str = ""
    enteredBy: str
    enteredAt: str | None = None


class ManualEntryOut(ManualEntryIn):
    id: str


# =====================================================================
# Auth
# =====================================================================


class LoginIn(ApiModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class UserOut(ApiModel):
    id: str
    email: str
    name: str
    role: str
    permissions: list[str]


# =====================================================================
# Clients
# =====================================================================


class ClientIn(ApiModel):
    name: str = Field(min_length=1)
    legalName: str = ""
    industry: str = ""
    spoc: str = ""
    email: str = ""
    phone: str = ""
    notes: str = ""


class ClientPatch(ApiModel):
    name: str | None = None
    legalName: str | None = None
    industry: str | None = None
    spoc: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    active: bool | None = None


class ClientOut(ApiModel):
    id: str
    name: str
    legalName: str
    industry: str
    spoc: str
    email: str
    phone: str
    notes: str
    active: bool
    createdAt: datetime
    #: Rolled up for the client list, so it does not need one call per row.
    vendorCount: int = 0
    decidedCount: int = 0


class VendorIn(ApiModel):
    """Intake. NOTHING IS REQUIRED except a name to file it under.

    A locked scope decision: format checks are advice, never a barrier.
    Anything an API needs is collected later, where it is clear which check
    is asking and why.
    """

    clientId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    legalName: str = ""
    address: str = ""
    material: str = ""
    spoc: str = ""
    designation: str = ""
    gst: str | None = None
    pan: str | None = None
    cin: str | None = None
    domain: str | None = None
    website: str | None = None
    contactMobile: str | None = None


class VendorPatch(ApiModel):
    name: str | None = None
    legalName: str | None = None
    address: str | None = None
    material: str | None = None
    spoc: str | None = None
    designation: str | None = None
    gst: str | None = None
    pan: str | None = None
    cin: str | None = None
    domain: str | None = None
    website: str | None = None
    #: The vendor's own contact number. Ten digits, no +91 — validated at
    #: BLOCK level, because a mistyped mobile does not fail, it returns a
    #: DIFFERENT PERSON'S records.
    contactMobile: str | None = None
    stage: str | None = None


class VendorOut(ApiModel):
    id: str
    clientId: str
    clientName: str = ""
    name: str
    legalName: str
    address: str
    material: str
    spoc: str
    designation: str
    gst: str | None
    pan: str | None
    cin: str | None
    domain: str | None
    website: str | None
    contactMobile: str | None = None
    stage: str
    decision: str | None = None
    decisionRemarks: str | None = None
    decidedBy: str | None = None
    unlocked: bool
    submitted: str
    selected: list[str]
    inputs: dict[str, dict[str, str]]
    #: The PRIMARY result per check — what counts. Shape unchanged, so
    #: the scoring engine and the report read exactly what they always
    #: did.
    checks: dict[str, CheckResultOut]

    #: EVERY result, newest first, including the ones that do not count.
    #: A check used to hold one and a re-run overwrote it; the person
    #: checks are run once per director, so the second run erased the
    #: first. Read by the findings screen; never by anything computing a
    #: number.
    runs: list[CheckResultOut] = []

    scan: dict[str, str | None]
    manual: list[ManualEntryOut]
    surveillance: dict[str, str | None]
    surveillanceDone: bool


class SelectionIn(ApiModel):
    selected: list[str]


class CheckInputIn(ApiModel):
    checkId: str
    key: str
    value: str


class ScanRatingIn(ApiModel):
    paramId: str
    value: str | None = None


class SurveillanceIn(ApiModel):
    values: dict[str, str | None]


class DecisionIn(ApiModel):
    decision: Literal["Approved", "Conditional", "Rejected"]
    remarks: str = Field(min_length=10)
    # NO decidedBy. The actor comes from the session — see services/auth.py.
    # This field used to be supplied by the caller, so anyone could record
    # a binding approval under a colleague's name.
    #: Required when the decision contradicts the recommendation. Not to
    #: discourage overrides, but so the file records why.
    overrideReason: str | None = None


class RunIn(ApiModel):
    """An optional narrowing of a run to specific checks.

    Omitted — or ``only=None`` — runs the whole selection, which is what
    Step 2 does and what every existing caller sends.

    SUPPLIED, it runs ONLY those ids, and only the ones that have not
    already produced a result. That restriction is the whole reason this
    field exists: ``run()`` does not skip checks that already answered, and
    ``_persist`` increments ``attempts``, so a Step 3 "run more checks"
    button that re-posted the full selection would silently re-bill every
    check the analyst had already paid for — on a full MCA set, around ₹40
    a click, with no way to tell from the screen that it had happened.
    """

    only: list[str] | None = None


class RunResultOut(ApiModel):
    vendor: VendorOut
    ran: int
    skippedMissingInput: list[str]
    costPaisa: int
    credits: int
    #: Populated when a name resolves to more than one strong candidate.
    #: The analyst picks; the system never picks for them.
    ambiguousCandidates: list[dict] = []
    notes: list[str] = []


class AuditOut(ApiModel):
    ts: datetime
    vendorId: str | None
    actor: str
    action: str
    detail: str


class CostRefOut(ApiModel):
    group: str
    item: str
    unit: str
    source: str


class ProviderStatusOut(ApiModel):
    """Whether each provider is live, and honestly why not when it isn't."""

    provider: str
    configured: bool
    sandbox: bool = False
    note: str = ""

    #: True when the provider is refusing OUR ACCOUNT — an empty balance, a
    #: revoked key, an IP that is not allowlisted. Distinct from
    #: `configured`, which only says whether a key was set: a provider can
    #: be perfectly configured and still blocked.
    blocked: bool = False

    #: The provider's OWN sentence, verbatim, never ours. WhoisXML returns
    #: an empty balance, a bad key and a blocked IP under one 403, and each
    #: needs a different person to act. A fixed message of ours would send
    #: the wrong person to the wrong place two times in three.
    blockedReason: str = ""

    #: ISO-8601. Answers "has this just happened, or has it been like this
    #: all morning" without a trip to the audit log.
    blockedSince: str | None = None

    #: 401, 402 or 403 — which the provider actually returned.
    blockedStatus: int | None = None

    #: The CHECK IDS this provider's outages actually cover, each with the
    #: provider's own reason.
    #:
    #: Computed here rather than on the screen because providers do not
    #: all bill the same way. WhoisXML charges its products from separate
    #: pools — on 6 Nov 2026 one key returned 200 for SSL and 403 for
    #: WHOIS History in the same minute — while FileSure, eCourts and
    #: FinAGG each draw on one wallet. Teaching the browser that
    #: distinction would mean a second copy of it, and the two copies
    #: would drift. The browser just asks "is my check id in here".
    #:
    #: Empty while nothing is blocked, which is the normal case.
    blockedChecks: dict[str, str] = {}


# =====================================================================
# API call history — the ledger
# =====================================================================


class HistoryRowOut(ApiModel):
    """One API call, with what it cost and who it was spent on.

    DISTINCT FROM THE AUDIT LOG, and the distinction is the reason this
    exists. The audit log records acts, in prose, for a reader: "ran 11
    checks", "set a result aside because…". Prose cannot be summed, and
    "what has this client cost us" is a question about money that has to
    be answered by adding numbers up.

    So: one row per call, joined up to the vendor and the client it was
    spent on, with the price as an integer.
    """

    runId: int
    clientId: str
    clientName: str
    vendorId: str
    vendorName: str
    checkId: str
    #: Resolved from the catalog, not stored on the row — a check that is
    #: renamed should read by its current name everywhere, and the id is
    #: carried beside it for anyone reconciling against raw tables.
    checkName: str
    provider: str
    status: str
    value: str = ""
    inputs: dict[str, str] = {}
    costPaisa: int = 0
    credits: int = 0
    attempts: int = 1
    fetchedAt: datetime
    isPrimary: bool = False

    #: SET ASIDE, AND STILL HERE. A result taken out of the score was
    #: still a call that was paid for, so it stays in the ledger and is
    #: marked rather than filtered out. Leaving it out would make this
    #: page under-report the bill, silently, which is the defect that
    #: retiring the delete was meant to close.
    ignoredAt: datetime | None = None
    ignoredBy: str | None = None
    ignoreReason: str | None = None


class HistoryTotalOut(ApiModel):
    id: str
    name: str
    calls: int
    costPaisa: int
    credits: int


class HistoryOut(ApiModel):
    rows: list[HistoryRowOut]
    #: Rolled up over the SAME filter the rows were drawn with, so the
    #: totals and the list on screen can never disagree.
    byClient: list[HistoryTotalOut] = []
    byVendor: list[HistoryTotalOut] = []
    totalCalls: int = 0
    totalCostPaisa: int = 0
    totalCredits: int = 0
