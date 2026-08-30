"""Seed the reference catalog into the database.

Idempotent: safe to run on every deploy. The Python catalog is the source
of truth, the database holds a projection of it, and this closes the loop.

CATALOG VERSIONING
------------------
Every run computes a SHA-256 over the serialised catalog. If the hash is
unchanged, nothing new is recorded. If it has changed, a new
``catalog_versions`` row is written with the full snapshot, and every score
computed from then on cites that version.

This is what makes a historical score defensible. Storing the raw API
payloads proves what the evidence was; storing the catalog version proves
what the rules were. A score is a function of both, and without the second
half a rule change silently rewrites history.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.checks import CHECKS
from app.catalog.manual_fields import MANUAL_TEMPLATES
from app.catalog.risk import RISK_RULES
from app.catalog.scan import SCAN_PARAMETERS
from app.catalog.surveillance import SURVEILLANCE_PARAMETERS
from app.db.models import (
    CatalogVersion,
    CheckDefinitionRow,
    ManualFieldTemplate,
    RiskRuleRow,
    ScanParameterRow,
    SurveillanceParameterRow,
)


def serialise_catalog() -> dict:
    """The catalog as a plain, deterministically ordered structure."""
    return {
        "scan_parameters": [
            {
                "id": p.id,
                "pillar": p.pillar.value,
                "label": p.label,
                "source": p.source.value,
                "feed": p.feed,
                "fed_by": p.fed_by,
                "weight": p.weight,
                "options": [[v, r.value] for v, r in p.options],
            }
            for p in SCAN_PARAMETERS
        ],
        "surveillance_parameters": [
            {
                "id": p.id,
                "label": p.label,
                "hard_gate": p.hard_gate,
                "options": [[v, r.value] for v, r in p.options],
            }
            for p in SURVEILLANCE_PARAMETERS
        ],
        "checks": [
            {
                "id": c.id,
                "category": c.group,
                "provider": c.provider.value,
                "name": c.name,
                "endpoint": c.endpoint,
                "note": c.note,
                "state": c.state.value,
                "feeds_params": list(c.feeds),
                "requires": list(c.requires),
                "cost_paisa": c.cost_paisa,
                "credits": c.credits,
                "screenshots": c.screenshots,
                "needs_company_unlock": c.needs_company_unlock,
                "needs_director_unlock": c.needs_director_unlock,
                "always": c.always,
                "admin": c.admin,
                "params": [
                    {
                        "key": p.key,
                        "label": p.label,
                        "required": p.required,
                        "from_vendor": p.from_vendor,
                        "from_result": p.from_result,
                        "type": p.type,
                        "options": list(p.options),
                        "default": p.default,
                        "placeholder": p.placeholder,
                    }
                    for p in c.params
                ],
            }
            for c in CHECKS
        ],
        "risk_rules": [
            {"id": r.id, "points": r.points, "label": r.label, "needs": list(r.needs)}
            for r in RISK_RULES
        ],
        "manual_templates": [
            {
                "id": t.id,
                "label": t.label,
                "type": t.type.value,
                "category": t.category,
                "options": list(t.options),
                "maps_to": t.maps_to,
                "map_when": t.map_when,
                "hint": t.hint,
            }
            for t in MANUAL_TEMPLATES
        ],
    }


def catalog_hash(snapshot: dict | None = None) -> str:
    payload = json.dumps(snapshot or serialise_catalog(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def current_catalog_version(session: Session) -> CatalogVersion | None:
    digest = catalog_hash()
    return session.scalar(
        select(CatalogVersion).where(CatalogVersion.content_hash == digest)
    )


def seed(session: Session, *, note: str = "") -> CatalogVersion:
    """Seed or refresh the catalog. Returns the active catalog version."""
    snapshot = serialise_catalog()
    digest = catalog_hash(snapshot)

    version = session.scalar(
        select(CatalogVersion).where(CatalogVersion.content_hash == digest)
    )
    is_new = version is None
    if is_new:
        version = CatalogVersion(content_hash=digest, snapshot=snapshot, note=note)
        session.add(version)
        session.flush()

    # --- SCAN parameters ------------------------------------------------
    for order, p in enumerate(SCAN_PARAMETERS):
        row = session.get(ScanParameterRow, p.id) or ScanParameterRow(id=p.id)
        row.pillar = p.pillar.value
        row.label = p.label
        row.source_mode = p.source.value
        row.feed = p.feed
        row.fed_by = p.fed_by
        row.weight = p.weight
        row.options = [{"value": v, "rating": r.value} for v, r in p.options]
        row.sort_order = order
        session.merge(row)

    # --- surveillance ---------------------------------------------------
    for order, p in enumerate(SURVEILLANCE_PARAMETERS):
        row = session.get(SurveillanceParameterRow, p.id) or SurveillanceParameterRow(id=p.id)
        row.label = p.label
        row.hard_gate = p.hard_gate
        row.options = [{"value": v, "rating": r.value} for v, r in p.options]
        row.sort_order = order
        session.merge(row)

    # --- checks, hooks included -----------------------------------------
    for c in CHECKS:
        row = session.get(CheckDefinitionRow, c.id) or CheckDefinitionRow(id=c.id)
        row.category = c.group
        row.provider = c.provider.value
        row.name = c.name
        row.endpoint = c.endpoint
        row.note = c.note
        row.state = c.state.value
        row.feeds_params = list(c.feeds)
        row.requires = list(c.requires)
        row.cost_paisa = c.cost_paisa
        row.credits = c.credits
        row.screenshots = c.screenshots
        row.needs_company_unlock = c.needs_company_unlock
        row.needs_director_unlock = c.needs_director_unlock
        row.always = c.always
        row.admin = c.admin
        row.params = [
            {
                "key": p.key,
                "label": p.label,
                "required": p.required,
                "from_vendor": p.from_vendor,
                "from_result": p.from_result,
                "type": p.type,
                "options": list(p.options),
                "default": p.default,
                "placeholder": p.placeholder,
            }
            for p in c.params
        ]
        session.merge(row)

    # --- risk rules -----------------------------------------------------
    for order, r in enumerate(RISK_RULES):
        row = session.get(RiskRuleRow, r.id) or RiskRuleRow(id=r.id)
        row.points = r.points
        row.label = r.label
        row.needs = list(r.needs)
        row.sort_order = order
        session.merge(row)

    session.flush()

    # --- manual templates (after SCAN params, they FK to them) ----------
    for order, t in enumerate(MANUAL_TEMPLATES):
        row = session.get(ManualFieldTemplate, t.id) or ManualFieldTemplate(id=t.id)
        row.label = t.label
        row.type = t.type.value
        row.category = t.category
        row.options = list(t.options)
        row.maps_to = t.maps_to
        row.map_when = dict(t.map_when)
        row.hint = t.hint
        row.sort_order = order
        session.merge(row)

    session.flush()
    return version


def main() -> int:
    from app.db.session import session_scope

    with session_scope() as session:
        version = seed(session, note="seeded from CLI")
        print(f"OK   catalog version {version.id} · {version.content_hash[:12]}")
        print(
            f"     {len(SCAN_PARAMETERS)} SCAN · {len(SURVEILLANCE_PARAMETERS)} field · "
            f"{len(CHECKS)} checks · {len(RISK_RULES)} rules · "
            f"{len(MANUAL_TEMPLATES)} templates"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
