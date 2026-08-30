"""Persisting and reconstructing scores.

The two functions that matter:

  ``record_score``      computes from stored rows and writes an immutable
                        snapshot citing the catalog and policy versions.

  ``reconstruct_score`` answers "what did we see, and what did we conclude"
                        for a score taken at any point in the past — from
                        the snapshot, not from a fresh computation.

The second is the one an auditor cares about, and it is why the snapshot
carries the pillar breakdown and full ledger rather than just the totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CatalogVersion,
    ScanRating,
    Vendor,
    VendorCheck,
    VendorScore,
)
from app.db.seed import catalog_hash
from app.domain.policy import CoveragePolicy, DEFAULT_POLICY, apply_policy
from app.domain.scoring import score_risk, score_scan
from app.domain.types import CheckResult, CheckStatus, Pillar


def load_check_results(session: Session, vendor_id: str) -> dict[str, CheckResult]:
    """Rehydrate stored check rows into the domain objects the engine takes."""
    rows = session.scalars(
        select(VendorCheck).where(VendorCheck.vendor_id == vendor_id)
    ).all()
    return {
        row.check_id: CheckResult(
            check_id=row.check_id,
            status=CheckStatus(row.status),
            value=row.value,
            detail=row.detail,
            raw_response=row.raw_response,
            cost_paisa=row.cost_paisa,
        )
        for row in rows
    }


def load_scan_ratings(session: Session, vendor_id: str) -> dict[str, str | None]:
    rows = session.scalars(
        select(ScanRating).where(ScanRating.vendor_id == vendor_id)
    ).all()
    return {row.param_id: row.value for row in rows}


def active_catalog_version(session: Session) -> CatalogVersion:
    """The catalog version matching the code currently running.

    A missing row means the database was never seeded against this build —
    scoring against it would cite rules that are not on file, so this
    raises rather than guessing.
    """
    digest = catalog_hash()
    version = session.scalar(
        select(CatalogVersion).where(CatalogVersion.content_hash == digest)
    )
    if version is None:
        raise RuntimeError(
            "No catalog version matches the running code. Run the seeder "
            "before scoring — a score that cannot cite its rules is not "
            "reconstructable."
        )
    return version


def record_score(
    session: Session,
    vendor_id: str,
    *,
    policy: CoveragePolicy = DEFAULT_POLICY,
) -> VendorScore:
    """Compute from stored rows and append an immutable snapshot."""
    version = active_catalog_version(session)

    ratings = load_scan_ratings(session, vendor_id)
    checks = load_check_results(session, vendor_id)
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise LookupError(f"Unknown vendor: {vendor_id}")

    scan = score_scan(ratings)
    gate = apply_policy(scan, policy=policy)
    risk = score_risk(checks, list(vendor.selected or []))

    snapshot = VendorScore(
        vendor_id=vendor_id,
        catalog_version_id=version.id,
        policy_version=gate.policy_version,
        weighted=scan.weighted,
        best=scan.best,
        pct=scan.pct,
        applicable=scan.applicable,
        total=scan.total,
        scan_passed=scan.passed,
        verdict=gate.verdict.value,
        raw_verdict=gate.raw_verdict.value,
        gated=gate.gated,
        gate_reasons=list(gate.reasons),
        coverage_note=scan.coverage_note,
        pillars={
            pillar.value: {
                "applicable": bucket.applicable,
                "G": bucket.G,
                "Y": bucket.Y,
                "R": bucket.R,
                "positives": bucket.positives,
                "weighted": bucket.weighted,
                "max": bucket.max,
                "weight": bucket.weight,
            }
            for pillar, bucket in scan.pillars.items()
        },
        risk_score=risk.score,
        risk_band=risk.band.label,
        risk_ledger=[
            {
                "id": line.id,
                "label": line.label,
                "points": line.points,
                "state": line.state.value,
                "applied": line.applied,
                "contribution": line.contribution,
                "explanation": line.explanation,
            }
            for line in risk.ledger
        ],
        risk_dead_rules=risk.dead,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


@dataclass
class ReconstructedScore:
    """A historical score, with everything needed to defend it."""

    snapshot: VendorScore
    catalog_version_id: int
    catalog_hash: str
    policy_version: str
    computed_at: datetime
    #: True when the catalog has changed since. The stored numbers are
    #: still authoritative for what was decided; they simply cannot be
    #: reproduced by re-running today's code.
    catalog_has_changed: bool

    @property
    def comparability_note(self) -> str:
        if not self.catalog_has_changed:
            return (
                "The catalog is unchanged since this score was taken, so it "
                "reproduces exactly against the current code."
            )
        return (
            "The catalog has changed since this score was taken. The stored "
            "figures remain the authoritative record of what was decided, but "
            "re-running today's rules would not reproduce them. Compare with "
            "scores from other catalog versions only with that in mind."
        )


def reconstruct_score(session: Session, score_id: int) -> ReconstructedScore:
    """Retrieve a historical score with its provenance."""
    snapshot = session.get(VendorScore, score_id)
    if snapshot is None:
        raise LookupError(f"Unknown score: {score_id}")

    version = session.get(CatalogVersion, snapshot.catalog_version_id)
    assert version is not None  # FK guarantees this

    return ReconstructedScore(
        snapshot=snapshot,
        catalog_version_id=version.id,
        catalog_hash=version.content_hash,
        policy_version=snapshot.policy_version,
        computed_at=snapshot.computed_at,
        catalog_has_changed=version.content_hash != catalog_hash(),
    )


def latest_score(session: Session, vendor_id: str) -> VendorScore | None:
    return session.scalar(
        select(VendorScore)
        .where(VendorScore.vendor_id == vendor_id)
        .order_by(VendorScore.computed_at.desc(), VendorScore.id.desc())
        .limit(1)
    )


def pillar_of(param_id: str) -> Pillar:
    from app.catalog.scan import scan_parameter

    return scan_parameter(param_id).pillar
