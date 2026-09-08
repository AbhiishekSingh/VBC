"""API routes. Implements frontend/src/api/contract.ts.

Two habits run through every handler:

  * Every mutation writes an audit entry. The log is append-only at the
    database level, so this is the only way anything gets recorded.
  * A score is never returned from a live recomputation at decision time.
    The decision cites an immutable snapshot, so "what did the system say
    when this was decided" has an answer that cannot drift.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.catalog.checks import CHECKS, expand_selection
from app.catalog.manual_fields import TEMPLATES_BY_ID
from app.catalog.scan import SCAN_PARAMETERS, scan_parameter
from app.catalog.surveillance import SURVEILLANCE_PARAMETERS
from app.config import get_settings
from app.api.deps import client_or_404, current_user, require_permission
from app.db.models import (
    AuditLog,
    Client,
    Decision,
    FieldVisit,
    ScanRating,
    SurveillanceEntry,
    User,
    Vendor,
    VendorCheck,
    VendorCheckInput,
    VendorManualEntry,
)
from app.db.scoring_store import latest_score, record_score
from app.db.session import get_session
from app.domain.policy import DEFAULT_POLICY, Verdict, apply_policy
from app.domain.scoring import score_scan, score_surveillance
from app.services import auth
from app.services.runner import CheckRunner

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------


def _vendor_or_404(session: Session, vendor_id: str) -> Vendor:
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(404, f"No vendor with id {vendor_id}")
    return vendor


def _next_vendor_id(session: Session) -> str:
    """Next free vendor id.

    Takes the MAXIMUM numeric id, not the last row by string order. Vendor
    ids are strings, so "TZ001" sorts after "234478" and an ORDER BY id DESC
    returns a row whose id is not a number at all — the previous version
    then fell back to the hardcoded seed and collided with an existing row.
    """
    ids = [i for i in session.scalars(select(Vendor.id)).all() if i.isdigit()]
    return str(max(int(i) for i in ids) + 1) if ids else "234478"


def _audit(session: Session, vendor_id: str | None, actor: str, action: str, detail: str) -> None:
    session.add(AuditLog(vendor_id=vendor_id, actor=actor, action=action, detail=detail))


def _serialise(session: Session, vendor: Vendor) -> s.VendorOut:
    checks = {
        row.check_id: s.CheckResultOut(
            checkId=row.check_id, status=row.status, value=row.value,
            detail=row.detail, rawResponse=row.raw_response,
            costPaisa=row.cost_paisa, fetchedAt=row.fetched_at,
        )
        for row in session.scalars(
            select(VendorCheck).where(VendorCheck.vendor_id == vendor.id)
        )
    }

    ratings = {
        row.param_id: row.value
        for row in session.scalars(
            select(ScanRating).where(ScanRating.vendor_id == vendor.id)
        )
    }
    # Every parameter appears, N/A included — a parameter that is absent
    # from the response is indistinguishable from one that is not applicable,
    # and those mean different things.
    scan = {p.id: ratings.get(p.id) for p in SCAN_PARAMETERS}

    inputs: dict[str, dict[str, str]] = {}
    for row in session.scalars(
        select(VendorCheckInput).where(VendorCheckInput.vendor_id == vendor.id)
    ):
        inputs.setdefault(row.check_id, {})[row.key] = row.value

    manual = [
        s.ManualEntryOut(
            id=str(row.id), key=row.key, value=row.value, type=row.type,
            templateId=row.template_id, note=row.note, enteredBy=row.entered_by,
            enteredAt=row.entered_at.strftime("%Y-%m-%d %H:%M"),
        )
        for row in session.scalars(
            select(VendorManualEntry).where(VendorManualEntry.vendor_id == vendor.id)
        )
    ]

    surveillance = {
        row.param_id: row.value
        for row in session.scalars(
            select(SurveillanceEntry).where(SurveillanceEntry.vendor_id == vendor.id)
        )
    }

    decision = session.scalar(
        select(Decision).where(Decision.vendor_id == vendor.id)
        .order_by(Decision.decided_at.desc()).limit(1)
    )

    return s.VendorOut(
        id=vendor.id,
        clientId=vendor.client_id,
        clientName=vendor.client.name if vendor.client else "", name=vendor.name, legalName=vendor.legal_name,
        address=vendor.address, material=vendor.material, spoc=vendor.spoc,
        designation=vendor.designation, gst=vendor.gst, pan=vendor.pan,
        cin=vendor.cin, domain=vendor.domain, website=vendor.website,
        stage=vendor.stage,
        decision=decision.decision if decision else None,
        decisionRemarks=decision.remarks if decision else None,
        decidedBy=decision.decided_by if decision else None,
        unlocked=vendor.unlocked,
        submitted=vendor.submitted_at.strftime("%Y-%m-%d %H:%M"),
        selected=list(vendor.selected or []), inputs=inputs, checks=checks,
        scan=scan, manual=manual, surveillance=surveillance,
        surveillanceDone=vendor.surveillance_done,
    )


def _apply_manual_mapping(session: Session, vendor: Vendor, entry: VendorManualEntry) -> str | None:
    """A library entry that maps to a SCAN parameter sets it.

    One parameter, one template — enforced by a UNIQUE constraint — so this
    can never depend on data-entry order.
    """
    template = TEMPLATES_BY_ID.get(entry.template_id or "")
    if not template or not template.maps_to:
        return None
    target = template.map_when.get(entry.value)
    if not target:
        return None
    _set_rating(session, vendor.id, template.maps_to, target,
                set_by=f"manual_field:{template.id}")
    return f"{template.maps_to} → {target}"


def _set_rating(session: Session, vendor_id: str, param_id: str,
                value: str | None, *, set_by: str) -> None:
    parameter = scan_parameter(param_id)
    rating = parameter.rate(value)
    row = session.scalar(
        select(ScanRating).where(
            ScanRating.vendor_id == vendor_id, ScanRating.param_id == param_id
        )
    )
    if row is None:
        row = ScanRating(vendor_id=vendor_id, param_id=param_id)
        session.add(row)
    row.value = value
    row.rating = rating.value if rating else None
    row.set_by = set_by
    # set_at has server_default=now() but no onupdate, so re-rating a
    # parameter kept the ORIGINAL timestamp. An analyst moving a parameter
    # from Green to Red is exactly the event an audit trail exists to
    # record, and it was being recorded under the time of the first rating.
    # The immutable audit_log row below carries the change itself; this
    # keeps the current-state row honest about when it last changed.
    row.set_at = datetime.now(timezone.utc)


# =====================================================================
# Vendors
# =====================================================================


@router.get("/vendors", response_model=list[s.VendorOut])
def list_vendors(
    clientId: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Every vendor, or one client's vendors when clientId is given."""
    query = select(Vendor).order_by(Vendor.submitted_at.desc())
    if clientId:
        query = query.where(Vendor.client_id == clientId)
    return [_serialise(session, v) for v in session.scalars(query).all()]


@router.get("/vendors/{vendor_id}", response_model=s.VendorOut)
def get_vendor(vendor_id: str, session: Session = Depends(get_session)):
    return _serialise(session, _vendor_or_404(session, vendor_id))


@router.post("/vendors", response_model=s.VendorOut, status_code=201)
def create_vendor(
    body: s.VendorIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    client = client_or_404(session, body.clientId)

    # One client cannot add the same company twice. A second CLIENT can —
    # that is what the client layer is for. Enforced by a unique index too,
    # so this is the friendly message rather than the guarantee.
    if body.cin:
        clash = session.scalar(
            select(Vendor).where(
                Vendor.client_id == client.id, Vendor.cin == body.cin
            )
        )
        if clash is not None:
            raise HTTPException(
                409,
                f"{client.name} already has this company on file as "
                f"{clash.name} (#{clash.id}).",
            )

    vendor = Vendor(
        id=_next_vendor_id(session), client_id=client.id, name=body.name,
        legal_name=body.legalName or body.name.upper(),
        address=body.address, material=body.material, spoc=body.spoc,
        designation=body.designation, gst=body.gst or None, pan=body.pan or None,
        cin=body.cin or None, domain=body.domain or None, website=body.website or None,
        stage="select",
        # NOTHING is selected on the analyst's behalf. A new vendor starts
        # with an empty selection, and every check is a deliberate choice.
        #
        # This used to preselect "ustatus". Safe to drop: the free unlock
        # status GET runs inside CheckRunner._ensure_unlock before any paid
        # unlock regardless of selection, so no cost control depended on it.
        selected=[],
    )
    session.add(vendor)
    session.flush()

    for parameter in SCAN_PARAMETERS:
        session.add(ScanRating(vendor_id=vendor.id, param_id=parameter.id,
                               value=None, rating=None, set_by="system"))

    _audit(session, vendor.id, user.email, "VENDOR_SUBMITTED",
           f"{vendor.name} submitted under client {client.name}")
    session.commit()
    return _serialise(session, vendor)


@router.patch("/vendors/{vendor_id}", response_model=s.VendorOut)
def update_vendor(vendor_id: str, body: s.VendorPatch, session: Session = Depends(get_session)):
    vendor = _vendor_or_404(session, vendor_id)
    field_map = {
        "legalName": "legal_name", "name": "name", "address": "address",
        "material": "material", "spoc": "spoc", "designation": "designation",
        "gst": "gst", "pan": "pan", "cin": "cin", "domain": "domain",
        "website": "website", "stage": "stage",
    }
    for api_field, column in field_map.items():
        value = getattr(body, api_field, None)
        if value is not None:
            setattr(vendor, column, value)
    session.commit()
    return _serialise(session, vendor)


# =====================================================================
# Selection and inputs
# =====================================================================


@router.post("/vendors/{vendor_id}/selection", response_model=s.VendorOut)
def set_selection(vendor_id: str, body: s.SelectionIn, session: Session = Depends(get_session)):
    vendor = _vendor_or_404(session, vendor_id)
    # Prerequisites are folded in server-side too — the UI does it for
    # feedback, but the API cannot rely on the UI having done it.
    vendor.selected = expand_selection(body.selected)
    session.commit()
    return _serialise(session, vendor)


@router.post("/vendors/{vendor_id}/inputs", response_model=s.VendorOut)
def set_input(vendor_id: str, body: s.CheckInputIn, session: Session = Depends(get_session)):
    _vendor_or_404(session, vendor_id)
    row = session.scalar(
        select(VendorCheckInput).where(
            VendorCheckInput.vendor_id == vendor_id,
            VendorCheckInput.check_id == body.checkId,
            VendorCheckInput.key == body.key,
        )
    )
    if row is None:
        row = VendorCheckInput(vendor_id=vendor_id, check_id=body.checkId, key=body.key)
        session.add(row)
    row.value = body.value
    session.commit()
    return _serialise(session, vendor_id and session.get(Vendor, vendor_id))


# =====================================================================
# Running checks
# =====================================================================


@router.post("/vendors/{vendor_id}/run", response_model=s.RunResultOut)
def run_checks(vendor_id: str, session: Session = Depends(get_session)):
    """Run the selected checks against the live providers.

    Synchronous for now. This is the call that belongs behind Celery once
    real vendors are being processed — a run with a company unlock and a
    full parallel block can take tens of seconds, which is too long to hold
    an HTTP connection open in production.
    """
    vendor = _vendor_or_404(session, vendor_id)
    runner = CheckRunner(session)
    try:
        result = runner.run(vendor)
    finally:
        runner.close()

    # Automated findings write the SCAN parameters they feed.
    _write_auto_ratings(session, vendor, result)

    vendor.stage = "manual"
    session.commit()

    return s.RunResultOut(
        vendor=_serialise(session, vendor),
        ran=result.examined,
        skippedMissingInput=[
            f.check_id for f in result.findings
            if f.status.value == "skipped_missing_input"
        ],
        costPaisa=result.spend.paisa,
        credits=result.spend.credits,
        ambiguousCandidates=result.ambiguous_candidates,
        notes=result.notes,
    )


def _write_auto_ratings(session: Session, vendor: Vendor, result) -> None:
    """Translate findings into the SCAN parameters they feed.

    Only AUTO parameters are written here. Human parameters are never
    inferred from a check — that would blur the line between what a source
    said and what a person judged, which the whole product exists to keep
    separate.
    """
    by_id = {f.check_id: f for f in result.findings}

    master = by_id.get("master")
    if master and master.status.was_examined and master.raw:
        facts = (master.raw or {}).get("facts", {})
        klass = str(facts.get("class_of_company") or "").lower()
        listed = str(facts.get("listed") or "").lower()
        if "public" in klass or "listed" in listed and "unlisted" not in listed:
            _set_rating(session, vendor.id, "S1", "Listed/Public", set_by="system")
        elif "private" in klass:
            _set_rating(session, vendor.id, "S1", "Private Ltd", set_by="system")
        elif klass:
            _set_rating(session, vendor.id, "S1", "Partnership/LLP", set_by="system")

        incorporated = facts.get("incorporated_on")
        if incorporated:
            try:
                years = (datetime.now(timezone.utc)
                         - datetime.fromisoformat(incorporated).replace(tzinfo=timezone.utc)
                         ).days / 365.25
                value = ("> 10 Years" if years > 10
                         else "3 - 10 Years" if years >= 3 else "< 3 Years")
                _set_rating(session, vendor.id, "S2", value, set_by="system")
            except ValueError:
                pass
    elif master and master.status.value == "fail":
        _set_rating(session, vendor.id, "S1", "Individual/ Proprietorship", set_by="system")

    # C1, C3, C4, C5 — one GST search call fills four Compliance parameters.
    gst = by_id.get("gst")
    if gst and gst.status.was_examined and gst.raw:
        facts = gst.raw or {}

        # C1 registration. "Not Applicable" is a judgement about whether a
        # vendor NEEDS to be registered — turnover threshold, exempt supply —
        # which no API answers. So this writes only the two states the
        # registry actually evidences, and leaves the third to an analyst.
        if facts.get("is_active") or facts.get("is_suspended"):
            _set_rating(session, vendor.id, "C1", "Registered", set_by="system")
        elif facts.get("is_cancelled"):
            _set_rating(session, vendor.id, "C1", "Unregistered", set_by="system")

        # C3 registration type, from search.dty — NOT from the composition
        # returns endpoint, which is OTP-gated.
        taxpayer_type = facts.get("taxpayer_type")
        if taxpayer_type:
            _set_rating(session, vendor.id, "C3",
                        "Composite" if facts.get("is_composition") else "Regular",
                        set_by="system")

        # C4 suspension. Only written when a status came back at all; an
        # unreadable status must leave the parameter N/A rather than record
        # "not suspended" on the strength of nothing.
        if facts.get("status"):
            _set_rating(session, vendor.id, "C4",
                        "Yes" if facts.get("is_suspended") else "No",
                        set_by="system")

        # C5 address. GSTN has no residential flag, so only a positive
        # commercial signal is recorded. Absence of the nature-of-business
        # field means nothing was declared — it does not mean a home
        # address, and inferring one would put a guess in the sourced half
        # of the report.
        if facts.get("premises_kind") == "commercial":
            _set_rating(session, vendor.id, "C5", "Commercial", set_by="system")

    # C2 — filing status, from the returns metadata track.
    gstret = by_id.get("gstret")
    if gstret and gstret.status.was_examined and gstret.raw:
        facts = gstret.raw or {}
        months = facts.get("months_since_last_filing")
        if not facts.get("filing_count"):
            value = "Current Default (0-3 months)"
        elif months is not None and months > 3:
            value = "Current Default (0-3 months)"
        elif months is not None and months > 1:
            value = "History of Default"
        else:
            value = "Regular"
        _set_rating(session, vendor.id, "C2", value, set_by="system")

    # S3 — web presence, from the archive timeline.
    cdx = by_id.get("cdx")
    if cdx and cdx.status.was_examined and cdx.raw:
        has_presence = (cdx.raw or {}).get("ok_captures", 0) > 0
        _set_rating(session, vendor.id, "S3", "Yes" if has_presence else "No",
                    set_by="system")

    # A3 — conflict of interest. Written ONLY when a register was actually
    # compared; an unavailable check leaves the parameter N/A rather than
    # recording a clean result nobody verified.
    conflict = by_id.get("conflict")
    if conflict and conflict.status.was_examined:
        _set_rating(session, vendor.id, "A3",
                    "Positive" if conflict.status.value == "pass" else "Negative",
                    set_by="system")

    # N3 — turnover, from filed financials.
    fin = by_id.get("fin")
    if fin and fin.status.was_examined and fin.raw:
        revenue = (fin.raw or {}).get("revenue")
        if isinstance(revenue, (int, float)):
            crore = revenue / 10_000_000
            value = ("2 Cr / 1 Cr" if crore >= 2
                     else "> 50 Lac / 25 Lac" if crore >= 0.5 else "< 50 Lac / 25 Lac")
            _set_rating(session, vendor.id, "N3", value, set_by="system")


# =====================================================================
# Manual entries
# =====================================================================


@router.post("/vendors/{vendor_id}/manual", response_model=s.VendorOut)
def add_manual_entry(vendor_id: str, body: s.ManualEntryIn,
                     session: Session = Depends(get_session)):
    vendor = _vendor_or_404(session, vendor_id)
    entry = VendorManualEntry(
        vendor_id=vendor.id, template_id=body.templateId, key=body.key,
        value=body.value, type=body.type, note=body.note, entered_by=body.enteredBy,
    )
    session.add(entry)
    session.flush()

    mapping = _apply_manual_mapping(session, vendor, entry)
    _audit(session, vendor.id, body.enteredBy, "MANUAL_FIELD_ADDED",
           f"{body.key} = {body.value}" + (f" · sets {mapping}" if mapping else ""))
    session.commit()
    return _serialise(session, vendor)


@router.delete("/vendors/{vendor_id}/manual/{entry_id}", response_model=s.VendorOut)
def remove_manual_entry(vendor_id: str, entry_id: int,
                        session: Session = Depends(get_session)):
    vendor = _vendor_or_404(session, vendor_id)
    entry = session.get(VendorManualEntry, entry_id)
    if entry is None or entry.vendor_id != vendor_id:
        raise HTTPException(404, "No such manual entry for this vendor")

    # The SCAN parameter the entry justified goes with it — a score must
    # never outlive the evidence behind it.
    template = TEMPLATES_BY_ID.get(entry.template_id or "")
    if template and template.maps_to:
        _set_rating(session, vendor_id, template.maps_to, None, set_by="system")

    _audit(session, vendor_id, entry.entered_by, "MANUAL_FIELD_REMOVED",
           f"{entry.key} removed")
    session.delete(entry)
    session.commit()
    return _serialise(session, vendor)


# =====================================================================
# Surveillance
# =====================================================================


@router.post("/vendors/{vendor_id}/surveillance", response_model=s.VendorOut)
def set_surveillance(vendor_id: str, body: s.SurveillanceIn,
                     session: Session = Depends(get_session)):
    vendor = _vendor_or_404(session, vendor_id)
    for param_id, value in body.values.items():
        row = session.scalar(
            select(SurveillanceEntry).where(
                SurveillanceEntry.vendor_id == vendor_id,
                SurveillanceEntry.param_id == param_id,
            )
        )
        if row is None:
            row = SurveillanceEntry(vendor_id=vendor_id, param_id=param_id)
            session.add(row)
        row.value = value
        # Same stale-timestamp defect as ScanRating: a field observation
        # corrected after the visit kept the time of the first entry.
        row.observed_at = datetime.now(timezone.utc)
    session.commit()
    return _serialise(session, vendor)


@router.post("/vendors/{vendor_id}/surveillance/complete", response_model=s.VendorOut)
def complete_surveillance(vendor_id: str, session: Session = Depends(get_session)):
    """File the field result. Writes A2 — the heaviest-weighted parameter."""
    vendor = _vendor_or_404(session, vendor_id)
    values = {
        row.param_id: row.value
        for row in session.scalars(
            select(SurveillanceEntry).where(SurveillanceEntry.vendor_id == vendor_id)
        )
    }
    result = score_surveillance(values, done=True)
    vendor.surveillance_done = True

    _set_rating(session, vendor_id, "A2", result.scan_value, set_by="surveillance")
    session.add(
        FieldVisit(vendor_id=vendor_id, conducted_by="field", result=result.verdict,
                   pct=result.pct, gate_failed=result.gate_failed)
    )
    _audit(session, vendor_id, "system", "SURVEILLANCE_FILED",
           f"{result.verdict} · {result.pct}% of {result.applicable} parameters"
           + (" · forced Negative by the premises hard gate" if result.gate_failed else ""))
    session.commit()
    return _serialise(session, vendor)


# =====================================================================
# SCAN
# =====================================================================


@router.post("/vendors/{vendor_id}/scan", response_model=s.VendorOut)
def set_scan_rating(vendor_id: str, body: s.ScanRatingIn,
                    session: Session = Depends(get_session)):
    vendor = _vendor_or_404(session, vendor_id)
    try:
        _set_rating(session, vendor_id, body.paramId, body.value, set_by="analyst")
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return _serialise(session, vendor)


# =====================================================================
# Decision
# =====================================================================


@router.post("/vendors/{vendor_id}/decision", response_model=s.VendorOut)
def record_decision(
    vendor_id: str,
    body: s.DecisionIn,
    session: Session = Depends(get_session),
    user: User = Depends(require_permission("decide")),
):
    """The binding record. Cites an immutable score snapshot.

    THE ACTOR COMES FROM THE SESSION. `decidedBy` used to be a field in the
    request body, so any caller could record a binding approval under a
    colleague's name and the audit trail would carry it as fact.

    An override — a decision contradicting the recommendation — requires a
    reason, enforced by a CHECK constraint as well as here.
    """
    vendor = _vendor_or_404(session, vendor_id)

    # Snapshot the score AS IT STANDS NOW, so the decision cites what the
    # system actually said rather than whatever a later recomputation gives.
    snapshot = record_score(session, vendor_id, policy=DEFAULT_POLICY)

    system_positive = snapshot.verdict == Verdict.POSITIVE.value
    is_override = (
        (body.decision == "Approved" and not system_positive)
        or (body.decision == "Rejected" and system_positive)
    )
    if is_override and not (body.overrideReason or "").strip():
        raise HTTPException(
            422,
            f"This decision contradicts the recommendation "
            f"({snapshot.verdict}). A reason is required — overrides are "
            f"expected and often correct, but the file has to say why.",
        )

    session.add(
        Decision(
            vendor_id=vendor_id, score_id=snapshot.id, decision=body.decision,
            remarks=body.remarks, decided_by=user.email,
            is_override=is_override, override_reason=body.overrideReason,
        )
    )
    vendor.stage = "decided"
    _audit(session, vendor_id, user.email, "DECISION_RECORDED",
           f"{body.decision.upper()} — {body.remarks}"
           + (f" · OVERRIDE: {body.overrideReason}" if is_override else ""))
    session.commit()
    return _serialise(session, vendor)


@router.get("/vendors/{vendor_id}/score")
def get_score(vendor_id: str, session: Session = Depends(get_session)):
    """Current score, plus the last snapshot if one exists."""
    _vendor_or_404(session, vendor_id)
    ratings = {
        row.param_id: row.value
        for row in session.scalars(
            select(ScanRating).where(ScanRating.vendor_id == vendor_id)
        )
    }
    scan = score_scan(ratings)
    gate = apply_policy(scan, policy=DEFAULT_POLICY)
    snapshot = latest_score(session, vendor_id)
    return {
        "live": {
            "weighted": scan.weighted, "best": scan.best, "pct": scan.pct,
            "applicable": scan.applicable, "total": scan.total,
            "verdict": gate.verdict.value, "gated": gate.gated,
            "reasons": gate.reasons, "coverageNote": scan.coverage_note,
            "policyVersion": gate.policy_version,
        },
        "lastSnapshot": (
            {
                "id": snapshot.id, "verdict": snapshot.verdict,
                "pct": float(snapshot.pct), "riskScore": snapshot.risk_score,
                "policyVersion": snapshot.policy_version,
                "computedAt": snapshot.computed_at,
            }
            if snapshot else None
        ),
    }


# =====================================================================
# Governance
# =====================================================================


@router.get("/audit", response_model=list[s.AuditOut])
def list_audit(vendorId: str | None = Query(None), limit: int = Query(500, le=2000),
               session: Session = Depends(get_session)):
    stmt = select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit)
    if vendorId:
        stmt = stmt.where(AuditLog.vendor_id == vendorId)
    return list(session.scalars(stmt))


@router.get("/cost-reference", response_model=list[s.CostRefOut])
def cost_reference():
    """Real unit prices with the derivation for each."""
    return [
        {"group": "FileSure", "item": "Company master / directors / filings / extractions",
         "unit": "₹1 per read", "source": "41200 paisa / 412 calls, from /v1/account/usage"},
        {"group": "FileSure", "item": "Company unlock (once per company per year)",
         "unit": "₹220", "source": "unlockPrice 22000 paisa — the rate card's ₹330 is wrong"},
        {"group": "FileSure", "item": "Director unlock", "unit": "₹10",
         "source": "unlockPrice 1000 paisa"},
        {"group": "FileSure", "item": "Filing document download", "unit": "₹0.10",
         "source": "19250 paisa / 1925 calls"},
        {"group": "FileSure", "item": "Full company refresh (async)", "unit": "₹150",
         "source": "priceChargedPaisa 15000"},
        {"group": "FileSure", "item": "Filings-only refresh", "unit": "₹5",
         "source": "priceChargedPaisa 500 · own ~6h cooldown · may return fromCache"},
        {"group": "FileSure", "item": "Unlock status check", "unit": "FREE",
         "source": "GET on the unlock path — always call before the POST"},
        {"group": "WhoisXML", "item": "WHOIS History (purchase mode)", "unit": "50 credits",
         "source": "500-credit Domain Research Suite pool"},
        {"group": "WhoisXML", "item": "Domain Reputation", "unit": "1 credit",
         "source": "50 trial credits"},
        {"group": "WhoisXML", "item": "SSL Certificates", "unit": "1 credit",
         "source": "100 trial credits · current certificate only"},
        {"group": "WhoisXML", "item": "Reverse WHOIS", "unit": "1 credit",
         "source": "shares the 500-credit pool"},
        {"group": "WhoisXML", "item": "Screenshot", "unit": "1 of only 10",
         "source": "tightest limit on the platform"},
        {"group": "archive.org", "item": "Availability, CDX, Advanced Search", "unit": "FREE",
         "source": "no key required"},
        {"group": "In-house", "item": "Duplicate, related party, director conflict",
         "unit": "FREE", "source": "computed over stored data"},
    ]


@router.get("/providers", response_model=list[s.ProviderStatusOut])
def provider_status():
    """Which providers are actually live.

    Said plainly, because a check that cannot run must never be mistaken
    for one that ran and found nothing.
    """
    settings = get_settings()
    unconfigured = sum(1 for c in CHECKS if not c.is_configured)
    return [
        {
            "provider": "filesure",
            "configured": settings.filesure_configured,
            "sandbox": settings.filesure_is_sandbox,
            "note": (
                "Sandbox key — real DINs return SANDBOX_ONLY and unlocks report "
                "sandbox:true. Not evidence the live path works."
                if settings.filesure_is_sandbox
                else "Live." if settings.filesure_configured
                else "No key set. MCA checks report not_configured."
            ),
        },
        {
            "provider": "whoisxml",
            "configured": settings.whoisxml_configured,
            "note": (
                "Live. Credits are per-product pools; screenshots are capped at 10."
                if settings.whoisxml_configured
                else "No key set. Domain checks report not_configured."
            ),
        },
        {
            "provider": "archive",
            "configured": True,
            "note": "Free, no key required.",
        },
        {
            "provider": "hooks",
            "configured": False,
            "note": (
                f"{unconfigured} checks have no provider at all, including GST "
                f"and all sanctions screening. They appear by name on every report."
            ),
        },
    ]


@router.get("/catalog")
def catalog():
    """The reference catalog, for a client that wants it from the server."""
    return {
        "checks": [
            {
                "id": c.id, "group": c.group, "name": c.name, "endpoint": c.endpoint,
                "provider": c.provider.value, "state": c.state.value,
                "note": c.note, "requires": list(c.requires), "feeds": list(c.feeds),
                "costPaisa": c.cost_paisa, "credits": c.credits,
                "screenshots": c.screenshots,
                "needsCompanyUnlock": c.needs_company_unlock,
                "needsDirectorUnlock": c.needs_director_unlock,
                "always": c.always, "admin": c.admin,
                "params": [
                    {"key": p.key, "label": p.label, "required": p.required,
                     "fromVendor": p.from_vendor, "fromResult": p.from_result,
                     "type": p.type, "options": list(p.options),
                     "default": p.default, "placeholder": p.placeholder}
                    for p in c.params
                ],
            }
            for c in CHECKS
        ],
        "scanParameters": [
            {"id": p.id, "pillar": p.pillar.value, "label": p.label,
             "source": p.source.value, "feed": p.feed, "fedBy": p.fed_by,
             "options": [{"value": v, "rating": r.value} for v, r in p.options]}
            for p in SCAN_PARAMETERS
        ],
        "surveillanceParameters": [
            {"id": p.id, "label": p.label, "hardGate": p.hard_gate,
             "options": [{"value": v, "rating": r.value} for v, r in p.options]}
            for p in SURVEILLANCE_PARAMETERS
        ],
    }
