"""Clients — the firms Q1SSL performs due diligence for.

A client is never deleted. Vendors, scores, decisions and the audit trail
hang off it, and an audit record that can vanish because someone tidied up
a client list is not an audit record. Clients are DEACTIVATED instead, and
the foreign key is ondelete=RESTRICT so the database refuses too.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.api.deps import client_or_404, current_user
from app.db.models import AuditLog, Client, Decision, User, Vendor
from app.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["clients"])


def _out(session: Session, client: Client) -> s.ClientOut:
    vendor_count = session.scalar(
        select(func.count(Vendor.id)).where(Vendor.client_id == client.id)
    ) or 0
    decided = session.scalar(
        select(func.count(func.distinct(Decision.vendor_id)))
        .select_from(Decision)
        .join(Vendor, Vendor.id == Decision.vendor_id)
        .where(Vendor.client_id == client.id)
    ) or 0
    return s.ClientOut(
        id=client.id, name=client.name, legalName=client.legal_name,
        industry=client.industry, spoc=client.spoc, email=client.email,
        phone=client.phone, notes=client.notes, active=client.active,
        createdAt=client.created_at,
        vendorCount=vendor_count, decidedCount=decided,
    )


@router.get("/clients", response_model=list[s.ClientOut])
def list_clients(
    includeInactive: bool = Query(default=False),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    query = select(Client).order_by(Client.name)
    if not includeInactive:
        query = query.where(Client.active.is_(True))
    return [_out(session, c) for c in session.scalars(query).all()]


@router.get("/clients/{client_id}", response_model=s.ClientOut)
def get_client(
    client_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    return _out(session, client_or_404(session, client_id))


@router.post("/clients", response_model=s.ClientOut, status_code=201)
def create_client(
    body: s.ClientIn,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    name = body.name.strip()
    clash = session.scalar(select(Client).where(func.lower(Client.name) == name.lower()))
    if clash is not None:
        raise HTTPException(
            409,
            f"A client named {clash.name} already exists"
            + ("" if clash.active else " (deactivated — reactivate it instead)")
            + ".",
        )

    # Max numeric suffix, not the last row by string order — see
    # _next_vendor_id in routes.py for why that distinction bites.
    used = [
        int("".join(c for c in i if c.isdigit()) or 0)
        for i in session.scalars(select(Client.id)).all()
    ]
    client = Client(
        id=f"CL{(max(used) + 1) if used else 1:06d}", name=name,
        legal_name=body.legalName.strip() or name,
        industry=body.industry.strip(), spoc=body.spoc.strip(),
        email=body.email.strip(), phone=body.phone.strip(),
        notes=body.notes.strip(),
    )
    session.add(client)
    session.flush()
    session.add(
        AuditLog(vendor_id=None, actor=user.email, action="CLIENT_CREATED",
                 detail=f"{client.name} (#{client.id})")
    )
    session.commit()
    return _out(session, client)


@router.patch("/clients/{client_id}", response_model=s.ClientOut)
def update_client(
    client_id: str,
    body: s.ClientPatch,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    client = client_or_404(session, client_id)
    changes: list[str] = []
    for api_field, column in {
        "name": "name", "legalName": "legal_name", "industry": "industry",
        "spoc": "spoc", "email": "email", "phone": "phone",
        "notes": "notes", "active": "active",
    }.items():
        value = getattr(body, api_field, None)
        if value is None:
            continue
        if getattr(client, column) != value:
            changes.append(api_field)
        setattr(client, column, value)

    if changes:
        session.add(
            AuditLog(vendor_id=None, actor=user.email, action="CLIENT_UPDATED",
                     detail=f"{client.name}: {', '.join(changes)}")
        )
    session.commit()
    return _out(session, client)


@router.post("/clients/{client_id}/deactivate", response_model=s.ClientOut)
def deactivate_client(
    client_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Hide a client without destroying its history.

    There is deliberately no DELETE. Vendors, scores and decisions hang off
    a client; removing one would orphan an audit trail, and the foreign key
    refuses it anyway.
    """
    client = client_or_404(session, client_id)
    client.active = False
    session.add(
        AuditLog(vendor_id=None, actor=user.email, action="CLIENT_DEACTIVATED",
                 detail=f"{client.name} (#{client.id}) — history retained")
    )
    session.commit()
    return _out(session, client)
