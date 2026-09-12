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
    stage: str
    decision: str | None = None
    decisionRemarks: str | None = None
    decidedBy: str | None = None
    unlocked: bool
    submitted: str
    selected: list[str]
    inputs: dict[str, dict[str, str]]
    checks: dict[str, CheckResultOut]
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
