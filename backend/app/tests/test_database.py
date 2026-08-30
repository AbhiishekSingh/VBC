"""Database tests, against a real PostgreSQL server.

Not SQLite. The schema relies on JSONB, CHECK constraints and triggers, and
a SQLite approximation would pass while the production database rejected
the same operation — which is the least useful kind of green test.

Skipped automatically when no server is reachable, so the suite still runs
in environments without one.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import (
    AuditLog,
    CatalogVersion,
    CheckDefinitionRow,
    Decision,
    ManualFieldTemplate,
    ScanParameterRow,
    ScanRating,
    Unlock,
    Vendor,
    VendorCheck,
    VendorScore,
)
from app.db.seed import catalog_hash, seed
from app.db.scoring_store import (
    latest_score,
    load_check_results,
    load_scan_ratings,
    reconstruct_score,
    record_score,
)
from app.domain.policy import DEFAULT_POLICY, PROTOTYPE_POLICY
from app.tests import fixtures as fx
from app.tests.conftest import DEFAULT_CLIENT_ID

TEST_URL = os.environ.get(
    "VBC_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres@/vbc_test?host=/tmp/pgsock&port=5433",
)


def _server_available() -> bool:
    try:
        create_engine(TEST_URL).connect().close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_available(), reason="no PostgreSQL server reachable"
)


# NOTE: the engine/session/seeded fixtures now live in conftest.py, so
# every test module can reach a real database. They were defined here and
# nowhere else, which is part of why the client layer and the timestamp
# defects went untested for so long.
def make_vendor(session, fixture_id="234479", **overrides) -> Vendor:
    vendor = Vendor(
        id=fixture_id,
        client_id=overrides.get("client_id", DEFAULT_CLIENT_ID),
        name=overrides.get("name", "Meridian Packaging Pvt Ltd"),
        legal_name="MERIDIAN PACKAGING PRIVATE LIMITED",
        cin=overrides.get("cin", "U21029MH2013PTC245119"),
        domain=overrides.get("domain", "meridianpack.in"),
        stage="scoring",
        selected=overrides.get("selected", fx.MERIDIAN_SELECTED),
    )
    session.add(vendor)
    session.flush()
    return vendor


# =====================================================================
# Seeding
# =====================================================================


class TestSeeding:
    def test_seeds_the_whole_catalog(self, session, seeded):
        assert session.scalar(select(CheckDefinitionRow).where(CheckDefinitionRow.id == "master"))
        assert len(session.scalars(select(CheckDefinitionRow)).all()) == 34
        assert len(session.scalars(select(ScanParameterRow)).all()) == 18
        assert len(session.scalars(select(ManualFieldTemplate)).all()) == 17

    def test_hooks_are_seeded_not_omitted(self, session, seeded):
        """A gap in coverage must be a visible row, not an absence."""
        hooks = session.scalars(
            select(CheckDefinitionRow).where(CheckDefinitionRow.state == "not_configured")
        ).all()
        assert len(hooks) == 9
        assert {h.id for h in hooks} >= {"gst", "ofac", "rbi", "news", "court"}

    def test_gst_hook_still_declares_what_it_would_fill(self, session, seeded):
        gst = session.get(CheckDefinitionRow, "gst")
        assert gst.feeds_params == ["C1", "C2", "C3", "C4", "C5"]
        assert gst.state == "not_configured"

    def test_is_idempotent(self, session, seeded):
        before = session.scalars(select(CatalogVersion)).all()
        seed(session)
        session.commit()
        after = session.scalars(select(CatalogVersion)).all()
        assert len(before) == len(after), "re-seeding an unchanged catalog made a new version"

    def test_catalog_version_records_a_content_hash(self, session, seeded):
        assert seeded.content_hash == catalog_hash()
        assert len(seeded.content_hash) == 64
        assert seeded.snapshot["scan_parameters"][0]["id"] == "S1"


# =====================================================================
# Constraints
# =====================================================================


class TestConstraints:
    def test_one_scan_parameter_cannot_be_written_by_two_templates(self, session, seeded):
        """Otherwise the score would depend on data-entry order."""
        session.add(
            ManualFieldTemplate(
                id="m99", label="Another office ownership field", type="Choice",
                category="Premises", options=["Owned"], maps_to="S5", map_when={},
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_invalid_check_status_is_rejected(self, session, seeded):
        make_vendor(session)
        session.add(
            VendorCheck(vendor_id="234479", check_id="master", status="probably_fine")
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_risk_score_outside_0_100_is_rejected(self, session, seeded):
        make_vendor(session)
        session.add(
            VendorScore(
                vendor_id="234479", catalog_version_id=seeded.id, policy_version="1.0",
                weighted=1, best=2, pct=50, applicable=5, total=18, scan_passed=False,
                verdict="x", raw_verdict="x", risk_score=140, risk_band="APPROVE",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_weighted_cannot_exceed_best(self, session, seeded):
        """A score above its own ceiling is arithmetically impossible."""
        make_vendor(session)
        session.add(
            VendorScore(
                vendor_id="234479", catalog_version_id=seeded.id, policy_version="1.0",
                weighted=5, best=2, pct=250, applicable=5, total=18, scan_passed=True,
                verdict="x", raw_verdict="x", risk_score=50, risk_band="DEEP REVIEW",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_an_override_without_a_reason_cannot_be_recorded(self, session, seeded):
        make_vendor(session)
        score = record_score(session, "234479")
        session.add(
            Decision(
                vendor_id="234479", score_id=score.id, decision="Approved",
                remarks="Approving this one despite the recommendation.",
                decided_by="a.mehta", is_override=True, override_reason=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_an_override_with_a_reason_is_fine(self, session, seeded):
        make_vendor(session)
        score = record_score(session, "234479")
        session.add(
            Decision(
                vendor_id="234479", score_id=score.id, decision="Rejected",
                remarks="Rejected on grounds the score does not capture.",
                decided_by="r.iyer", is_override=True,
                override_reason="Unincorporated proprietorship with no premises.",
            )
        )
        session.flush()  # no raise

    def test_empty_remarks_are_rejected(self, session, seeded):
        make_vendor(session)
        score = record_score(session, "234479")
        session.add(
            Decision(
                vendor_id="234479", score_id=score.id, decision="Approved",
                remarks="ok", decided_by="a.mehta",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

    def test_a_check_cannot_be_recorded_twice_for_one_vendor(self, session, seeded):
        make_vendor(session)
        session.add(VendorCheck(vendor_id="234479", check_id="master", status="pass"))
        session.flush()
        session.add(VendorCheck(vendor_id="234479", check_id="master", status="fail"))
        with pytest.raises(IntegrityError):
            session.flush()


# =====================================================================
# Immutability — enforced by the database, not by convention
# =====================================================================


class TestImmutability:
    def test_audit_entries_cannot_be_updated(self, session, seeded):
        session.add(AuditLog(actor="a.mehta", action="TEST", detail="original"))
        session.commit()
        with pytest.raises(DatabaseError):
            session.execute(text("UPDATE audit_log SET detail = 'edited'"))
        session.rollback()

    def test_audit_entries_cannot_be_deleted(self, session, seeded):
        session.add(AuditLog(actor="a.mehta", action="TEST", detail="keep me"))
        session.commit()
        with pytest.raises(DatabaseError):
            session.execute(text("DELETE FROM audit_log"))
        session.rollback()

    def test_the_error_says_what_to_do_instead(self, session, seeded):
        session.add(AuditLog(actor="a.mehta", action="TEST", detail="x"))
        session.commit()
        with pytest.raises(DatabaseError) as exc:
            session.execute(text("UPDATE audit_log SET detail = 'y'"))
        assert "append-only" in str(exc.value)
        assert "correcting entry" in str(exc.value)
        session.rollback()

    def test_score_snapshots_cannot_be_updated(self, session, seeded):
        make_vendor(session)
        score = record_score(session, "234479")
        session.commit()
        with pytest.raises(DatabaseError):
            session.execute(
                text("UPDATE vendor_scores SET risk_score = 99 WHERE id = :i"),
                {"i": score.id},
            )
        session.rollback()

    def test_decisions_cannot_be_rewritten(self, session, seeded):
        make_vendor(session)
        score = record_score(session, "234479")
        session.add(
            Decision(
                vendor_id="234479", score_id=score.id, decision="Approved",
                remarks="Approved on filed financials and a site visit.",
                decided_by="a.mehta",
            )
        )
        session.commit()
        with pytest.raises(DatabaseError):
            session.execute(text("UPDATE decisions SET decision = 'Rejected'"))
        session.rollback()

    def test_catalog_versions_cannot_be_edited(self, session, seeded):
        with pytest.raises(DatabaseError):
            session.execute(text("UPDATE catalog_versions SET snapshot = '{}'::jsonb"))
        session.rollback()

    def test_truncate_bypasses_the_append_only_guard(self, session, seeded):
        """A real limitation of trigger-based immutability, asserted so it
        is not forgotten.

        PostgreSQL fires row-level BEFORE DELETE triggers for DELETE but NOT
        for TRUNCATE. So the triggers stop an application bug or a careless
        UPDATE; they do not stop a role that holds TRUNCATE privilege from
        emptying the audit trail entirely.

        The mitigation is privilege, not triggers: the application role must
        be granted only SELECT and INSERT on audit_log, and must not own the
        table (an owner can always TRUNCATE, and can drop the triggers).
        See db/immutability.sql for the GRANT block that does this, and
        db/README.md for the deployment note.
        """
        session.add(AuditLog(actor="a.mehta", action="TEST", detail="x"))
        session.commit()

        # Running as the owner in tests, this SUCCEEDS — which is the point.
        session.execute(text("TRUNCATE audit_log"))
        assert session.scalar(select(AuditLog)) is None
        session.rollback()


# =====================================================================
# Round trip — the fixtures must survive the database
# =====================================================================


class TestRoundTrip:
    def _load_meridian(self, session):
        vendor = make_vendor(session)
        for check_id, result in fx.MERIDIAN_CHECKS.items():
            session.add(
                VendorCheck(
                    vendor_id=vendor.id, check_id=check_id, status=result.status.value,
                    value=result.value, detail=result.detail,
                    raw_response={"sample": True, "checkId": check_id},
                )
            )
        for param_id, value in fx.MERIDIAN_SCAN.items():
            session.add(
                ScanRating(
                    vendor_id=vendor.id, param_id=param_id, value=value,
                    set_by="system" if value else "system",
                )
            )
        session.flush()
        return vendor

    def test_scores_computed_from_stored_rows_match_the_fixture(self, session, seeded):
        self._load_meridian(session)
        score = record_score(session, "234479")
        assert float(score.weighted) == 3.80
        assert float(score.best) == 3.90
        assert float(score.pct) == 97.4
        assert score.applicable == 14
        assert score.risk_score == 95
        assert score.risk_band == "APPROVE"

    def test_azahan_is_gated_when_scored_from_the_database(self, session, seeded):
        vendor = Vendor(
            id="234478", client_id=DEFAULT_CLIENT_ID,
            name="Azahan Advertising", legal_name="AZAHAN ADVERTISING",
            stage="scoring", selected=fx.AZAHAN_SELECTED,
        )
        session.add(vendor)
        for check_id, result in fx.AZAHAN_CHECKS.items():
            session.add(
                VendorCheck(vendor_id="234478", check_id=check_id,
                            status=result.status.value, value=result.value)
            )
        for param_id, value in fx.AZAHAN_SCAN.items():
            session.add(ScanRating(vendor_id="234478", param_id=param_id,
                                   value=value, set_by="system"))
        session.flush()

        gated = record_score(session, "234478", policy=DEFAULT_POLICY)
        assert float(gated.pct) == 60.0
        assert gated.gated is True
        assert gated.verdict == "Insufficient Coverage — Senior Review"
        assert gated.raw_verdict == "Positive for Onboarding"
        assert len(gated.gate_reasons) == 2

        ungated = record_score(session, "234478", policy=PROTOTYPE_POLICY)
        assert ungated.verdict == "Positive for Onboarding"
        assert ungated.gated is False

    def test_raw_payloads_survive_the_round_trip(self, session, seeded):
        self._load_meridian(session)
        session.commit()
        loaded = load_check_results(session, "234479")
        assert loaded["master"].raw_response == {"sample": True, "checkId": "master"}
        assert loaded["master"].status.value == "pass"

    def test_null_ratings_round_trip_as_not_applicable(self, session, seeded):
        """NULL must survive as N/A, not decay into an empty string."""
        self._load_meridian(session)
        session.commit()
        ratings = load_scan_ratings(session, "234479")
        assert ratings["C1"] is None
        assert ratings["S1"] == "Private Ltd"

    def test_the_ledger_is_stored_whole(self, session, seeded):
        self._load_meridian(session)
        score = record_score(session, "234479")
        assert len(score.risk_ledger) == 13
        gst_rule = next(r for r in score.risk_ledger if r["id"] == "r10")
        assert gst_rule["state"] == "not_configured"
        assert gst_rule["explanation"] == "source not configured"
        assert score.risk_dead_rules == 4

    def test_pillar_breakdown_is_stored(self, session, seeded):
        self._load_meridian(session)
        score = record_score(session, "234479")
        assert score.pillars["A"]["applicable"] == 4
        assert score.pillars["A"]["weight"] == 0.6
        assert score.pillars["C"]["applicable"] == 1


# =====================================================================
# Reconstruction — the point of the whole design
# =====================================================================


class TestReconstruction:
    def test_a_score_can_be_retrieved_with_its_provenance(self, session, seeded):
        make_vendor(session)
        for param_id, value in fx.MERIDIAN_SCAN.items():
            session.add(ScanRating(vendor_id="234479", param_id=param_id,
                                   value=value, set_by="system"))
        session.flush()
        score = record_score(session, "234479")
        session.commit()

        rebuilt = reconstruct_score(session, score.id)
        assert rebuilt.catalog_hash == catalog_hash()
        assert rebuilt.policy_version == "1.0"
        assert rebuilt.catalog_has_changed is False
        assert "reproduces exactly" in rebuilt.comparability_note

    def test_a_changed_catalog_is_detected(self, session, seeded):
        """A score taken under older rules is flagged as not reproducible.

        Written by inserting a score that cites an older catalog version,
        because the snapshot cannot be edited after the fact — which is the
        property being relied on. (An earlier draft of this test tried to
        UPDATE the score's catalog_version_id and the trigger refused it,
        which was the schema working correctly.)
        """
        make_vendor(session)
        session.flush()

        # A catalog as it stood before, say, GST got a provider.
        older = CatalogVersion(
            content_hash="0" * 64,
            snapshot={"note": "the catalog before GST was configured"},
        )
        session.add(older)
        session.flush()

        historical = VendorScore(
            vendor_id="234479", catalog_version_id=older.id,
            policy_version="1.0", weighted=3.8, best=3.9, pct=97.4,
            applicable=14, total=18, scan_passed=True,
            verdict="Positive for Onboarding", raw_verdict="Positive for Onboarding",
            risk_score=95, risk_band="APPROVE",
        )
        session.add(historical)
        session.flush()

        rebuilt = reconstruct_score(session, historical.id)
        assert rebuilt.catalog_has_changed is True
        assert "would not reproduce them" in rebuilt.comparability_note
        # The stored figures are untouched and remain the record.
        assert float(rebuilt.snapshot.weighted) == 3.8

    def test_rescoring_appends_rather_than_overwrites(self, session, seeded):
        make_vendor(session)
        for param_id, value in fx.MERIDIAN_SCAN.items():
            session.add(ScanRating(vendor_id="234479", param_id=param_id,
                                   value=value, set_by="system"))
        session.flush()

        first = record_score(session, "234479")
        # An analyst revises a rating.
        rating = session.scalar(
            select(ScanRating).where(
                ScanRating.vendor_id == "234479", ScanRating.param_id == "A4"
            )
        )
        rating.value = "Poor"
        session.flush()
        second = record_score(session, "234479")

        assert first.id != second.id
        assert float(first.weighted) != float(second.weighted)
        assert latest_score(session, "234479").id == second.id
        # The original is still on file, unchanged.
        assert float(session.get(VendorScore, first.id).weighted) == 3.80

    def test_scoring_without_a_seeded_catalog_refuses(self, session):
        """A score that cannot cite its rules is not reconstructable."""
        make_vendor(session, fixture_id="999999")
        session.flush()
        # Hide the catalog version without deleting it (the trigger forbids
        # UPDATE, and DELETE would cascade into other tests' fixtures).
        session.execute(
            text("ALTER TABLE catalog_versions RENAME TO catalog_versions_hidden")
        )
        session.execute(
            text("CREATE TABLE catalog_versions AS "
                 "SELECT * FROM catalog_versions_hidden WHERE false")
        )
        try:
            with pytest.raises(RuntimeError, match="No catalog version"):
                record_score(session, "999999")
        finally:
            session.execute(text("DROP TABLE catalog_versions"))
            session.execute(
                text("ALTER TABLE catalog_versions_hidden RENAME TO catalog_versions")
            )
            session.commit()


# =====================================================================
# Operations
# =====================================================================


class TestUnlocks:
    def test_a_valid_unlock_is_findable_before_buying_another(self, session, seeded):
        """Unlocks are the cost driver — three outweigh 1,925 downloads."""
        make_vendor(session)
        session.add(
            Unlock(
                scope="company", identifier="U21029MH2013PTC245119",
                vendor_id="234479", cost_paisa=22_000,
                expires_at=datetime.now(timezone.utc) + timedelta(days=365),
            )
        )
        session.flush()

        found = session.scalar(
            select(Unlock).where(
                Unlock.scope == "company",
                Unlock.identifier == "U21029MH2013PTC245119",
                Unlock.expires_at > datetime.now(timezone.utc),
            )
        )
        assert found is not None
        assert found.cost_paisa == 22_000

    def test_an_expired_unlock_does_not_match(self, session, seeded):
        session.add(
            Unlock(
                scope="company", identifier="U99999MH2013PTC000000", cost_paisa=22_000,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        session.flush()
        found = session.scalar(
            select(Unlock).where(
                Unlock.identifier == "U99999MH2013PTC000000",
                Unlock.expires_at > datetime.now(timezone.utc),
            )
        )
        assert found is None

    def test_money_is_stored_as_integer_paisa(self, session, seeded):
        """Never a float. 22000 paisa, not 220.00 rupees."""
        session.add(
            Unlock(
                scope="company", identifier="U11111MH2013PTC000000", cost_paisa=22_000,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        session.flush()
        row = session.scalar(
            select(Unlock).where(Unlock.identifier == "U11111MH2013PTC000000")
        )
        assert isinstance(row.cost_paisa, int)
        assert row.cost_paisa == 22_000
