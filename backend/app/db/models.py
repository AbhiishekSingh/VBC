"""The database schema.

Follows §13 of the project handoff, with one addition that §13 does not
have and that the product needs — see THE RECONSTRUCTION PROBLEM below.

THE RECONSTRUCTION PROBLEM
--------------------------
§13 says ``raw_response`` makes any historical score reconstructable from
the payload it was computed on. That is half the story. A score is a
function of two things: the evidence, and the rules applied to it. Storing
the evidence covers the first. But ``check_definitions``, ``scan_parameters``
and ``risk_rules`` are seeded, mutable tables — if someone corrects an
option string or a provider is enabled in 2027, a 2026 score can no longer
be reproduced even with every original byte on file, because the rules
themselves have moved.

For an ordinary application that is a curiosity. For an audit product it is
the whole ballgame: "why was this vendor onboarded" must be answerable years
later, in front of someone who is not inclined to take our word for it.

So this schema adds:

  * ``catalog_versions``  — an immutable, content-hashed snapshot of the
    catalog as it stood, written whenever the seeder detects a change.
  * ``vendor_scores``     — an immutable snapshot of a computed score,
    carrying the catalog version and coverage-policy version that produced
    it, plus the full pillar breakdown and risk ledger as JSONB.

A decision points at a score snapshot, not at a live recomputation. Two
vendors scored under different catalog or policy versions can then be
identified as not directly comparable, which is a fact the system should
know rather than something a person has to remember.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonB, created_at, money, updated_at

# =====================================================================
# CATALOG — seeded reference data
# =====================================================================


class CatalogVersion(Base):
    """An immutable snapshot of the catalog as it stood at one moment.

    Written by the seeder when the content hash of the catalog changes.
    Every score references the version it was computed under, so a rule
    change is visible rather than silently retroactive.
    """

    __tablename__ = "catalog_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: SHA-256 over the serialised catalog. Two identical catalogs produce
    #: one row; any change produces a new one.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: The full catalog as serialised at that moment — the authoritative
    #: record of what the rules actually were.
    snapshot: Mapped[dict] = mapped_column(JsonB, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at()


class CheckDefinitionRow(Base):
    """One of the 32 checks. The 9 hooks live here too, as ``not_configured``.

    They are seeded rather than omitted so a gap in coverage is a visible
    row that reports and queries can name. Silence must never look like a
    clean result.
    """

    __tablename__ = "check_definitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")

    feeds_params: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    requires: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    params: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)

    cost_paisa: Mapped[int] = money()
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    screenshots: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    needs_company_unlock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    needs_director_unlock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    always: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'not_configured')", name="state_enum"
        ),
        CheckConstraint("cost_paisa >= 0", name="cost_non_negative"),
    )


class ScanParameterRow(Base):
    """One of the 18 SCAN parameters. All five C-pillar hooks included."""

    __tablename__ = "scan_parameters"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    pillar: Mapped[str] = mapped_column(String(1), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    source_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    feed: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Ordered [{value, rating}] — the display strings are part of the
    #: audit contract, not presentation detail.
    options: Mapped[list] = mapped_column(JsonB, nullable=False)
    #: Denormalised from the pillar for query convenience. The pillar
    #: weights are the workbook's and must not be edited here.
    weight: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("pillar IN ('S', 'C', 'A', 'N')", name="pillar_enum"),
        CheckConstraint(
            "source_mode IN ('AUTO', 'HUMAN', 'HOOK')", name="source_mode_enum"
        ),
    )


class SurveillanceParameterRow(Base):
    """One of the 13 field parameters. Exactly one carries the hard gate."""

    __tablename__ = "surveillance_parameters"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JsonB, nullable=False)
    hard_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RiskRuleRow(Base):
    """One of the 13 ledger rules, including the four with no provider."""

    __tablename__ = "risk_rules"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    needs: Mapped[list] = mapped_column(JsonB, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ManualFieldTemplate(Base):
    """The organisation's field library.

    ``maps_to`` is UNIQUE where set: one SCAN parameter may be written by
    at most one template. Two templates writing the same parameter would
    make the score depend on data-entry order, which is why the constraint
    is in the database rather than left to the seeder to remember.
    """

    __tablename__ = "manual_field_templates"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    options: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    maps_to: Mapped[str | None] = mapped_column(
        ForeignKey("scan_parameters.id"), nullable=True
    )
    map_when: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("maps_to", name="uq_manual_field_templates_maps_to"),
    )


# =====================================================================
# VENDORS
# =====================================================================


class Client(Base):
    """A firm Q1SSL performs due diligence FOR — Reliance and its peers.

    The layer above vendors. Every vendor belongs to exactly one client, and
    an audit is always "this client's assessment of this vendor". Two clients
    can onboard the same company; they get separate assessments.
    """

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    industry: Mapped[str] = mapped_column(Text, nullable=False, default="")
    spoc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    vendors: Mapped[list[Vendor]] = relationship(back_populates="client")

    __table_args__ = (
        UniqueConstraint("name", name="uq_client_name"),
        Index("ix_clients_active", "active"),
    )


class User(Base):
    """Someone who can log in.

    ``password_hash`` is argon2 — never a plaintext or reversible value.

    ``role`` separates who may RUN checks from who may RECORD THE DECISION.
    That split is the product principle in the access layer: the system
    gathers, an analyst assesses, and a named human commits the binding
    outcome.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="analyst")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
        CheckConstraint("role IN ('analyst','approver','admin')", name="role_enum"),
    )


class Session(Base):
    """A logged-in session, server-side.

    The token is stored HASHED. A stolen database dump then yields no usable
    sessions — the same reason passwords are hashed.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_session_token"),
        Index("ix_sessions_user", "user_id"),
    )


class Vendor(Base):
    """A vendor under assessment, BELONGING TO ONE CLIENT.

    EVERY IDENTIFIER IS NULLABLE. Nothing is compulsory at intake — a
    locked scope decision. An analyst with only a name can still file the
    vendor, and what is missing is collected later where it is clear which
    API needs it.
    """

    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    material: Mapped[str] = mapped_column(Text, nullable=False, default="")
    spoc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    designation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    gst: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(12), nullable=True)
    cin: Mapped[str | None] = mapped_column(String(24), nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)

    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="intake")
    unlocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    surveillance_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    selected: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)

    submitted_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    client: Mapped[Client] = relationship(back_populates="vendors")
    checks: Mapped[list[VendorCheck]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )
    ratings: Mapped[list[ScanRating]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )
    manual_entries: Mapped[list[VendorManualEntry]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_vendors_client", "client_id"),
        Index("ix_vendors_gst", "gst"),
        Index("ix_vendors_pan", "pan"),
        Index("ix_vendors_cin", "cin"),
        # One client cannot add the same company twice. Two DIFFERENT
        # clients can — that is the point.
        Index("uq_client_cin", "client_id", "cin", unique=True,
              postgresql_where=text("cin IS NOT NULL")),
        CheckConstraint(
            "stage IN ('intake','select','running','manual','scoring',"
            "'report','review','decided')",
            name="stage_enum",
        ),
    )


class VendorCheckInput(Base):
    """An analyst's value for one parameter of one check."""

    __tablename__ = "vendor_check_inputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    check_id: Mapped[str] = mapped_column(ForeignKey("check_definitions.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("vendor_id", "check_id", "key", name="uq_vendor_check_input"),
    )


class VendorCheck(Base):
    """The outcome of running one check for one vendor.

    ``raw_response`` MUST hold the real payload in production, not a
    template. It is what makes a historical finding defensible: the score
    can be recomputed from the exact bytes it was derived from.

    PII NOTE — director profiles carry PAN and masked contact details, so
    this column holds personal data. It needs a retention policy and
    restricted read access before go-live; see the note in db/README.md.
    Deleting it is not an option (it is the evidence), so the control has
    to be access and retention rather than omission.
    """

    __tablename__ = "vendor_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    check_id: Mapped[str] = mapped_column(ForeignKey("check_definitions.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_response: Mapped[dict | None] = mapped_column(JsonB, nullable=True)

    cost_paisa: Mapped[int] = money()
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    fetched_at: Mapped[datetime] = created_at()

    vendor: Mapped[Vendor] = relationship(back_populates="checks")

    __table_args__ = (
        UniqueConstraint("vendor_id", "check_id", name="uq_vendor_check"),
        CheckConstraint(
            "status IN ('pass','warn','fail','skip','unavailable',"
            "'not_configured','skipped_missing_input')",
            name="status_enum",
        ),
        CheckConstraint("cost_paisa >= 0", name="cost_non_negative"),
        Index("ix_vendor_checks_vendor", "vendor_id"),
    )


class ScanRating(Base):
    """One SCAN parameter's value for one vendor.

    ``set_by`` records provenance: ``system`` for an automated check, an
    analyst id for a human judgement, or ``manual_field:<id>`` when a
    library entry wrote it. Without this the score is a number nobody can
    account for.
    """

    __tablename__ = "scan_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    param_id: Mapped[str] = mapped_column(ForeignKey("scan_parameters.id"), nullable=False)
    #: NULL means Not Applicable — the parameter leaves both sides of the
    #: calculation. This is a real state, not missing data.
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[str | None] = mapped_column(String(1), nullable=True)
    set_by: Mapped[str] = mapped_column(String(64), nullable=False)
    set_at: Mapped[datetime] = created_at()

    vendor: Mapped[Vendor] = relationship(back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("vendor_id", "param_id", name="uq_vendor_scan_param"),
        CheckConstraint("rating IS NULL OR rating IN ('G','Y','R')", name="rating_enum"),
    )


class VendorManualEntry(Base):
    """An analyst-stated fact. Never rendered as verified evidence."""

    __tablename__ = "vendor_manual_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("manual_field_templates.id"), nullable=True
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    entered_by: Mapped[str] = mapped_column(String(64), nullable=False)
    entered_at: Mapped[datetime] = created_at()

    vendor: Mapped[Vendor] = relationship(back_populates="manual_entries")

    __table_args__ = (Index("ix_manual_entries_vendor", "vendor_id"),)


class SurveillanceEntry(Base):
    """One field observation for one vendor."""

    __tablename__ = "surveillance_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    param_id: Mapped[str] = mapped_column(
        ForeignKey("surveillance_parameters.id"), nullable=False
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    observed_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("vendor_id", "param_id", name="uq_vendor_surveillance_param"),
    )


# =====================================================================
# SCORES — immutable snapshots
# =====================================================================


class VendorScore(Base):
    """An immutable record of a score as computed at one moment.

    Never updated. A rescore writes a new row, so the history of how a
    vendor's assessment moved is itself on file.

    The three ``*_version`` columns are what make this reconstructable:
    together they pin the evidence, the rules and the verdict policy.
    """

    __tablename__ = "vendor_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    catalog_version_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_versions.id"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # SCAN
    weighted: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    best: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    pct: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    applicable: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: The gated verdict — what may actually be claimed.
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    #: The ungated verdict, kept so a gate can be audited after the fact.
    raw_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    gated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gate_reasons: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    coverage_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pillars: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)

    # 0-100 ledger
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_band: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_ledger: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    risk_dead_rules: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    computed_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="risk_range"),
        CheckConstraint("weighted >= 0 AND best >= 0", name="scan_non_negative"),
        CheckConstraint("weighted <= best", name="weighted_within_best"),
        Index("ix_vendor_scores_vendor", "vendor_id", "computed_at"),
    )


class Decision(Base):
    """The binding outcome, recorded by a named human.

    Points at the score SNAPSHOT rather than at a live recomputation, so
    "what did the system say when this was decided" has an answer that
    cannot drift.

    ``override_reason`` is required whenever the decision contradicts the
    recommendation — not to discourage overrides (Azahan was overridden and
    the human was right) but so the file records why.
    """

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    score_id: Mapped[int] = mapped_column(ForeignKey("vendor_scores.id"), nullable=False)

    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    remarks: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = created_at()

    __table_args__ = (
        CheckConstraint(
            "decision IN ('Approved','Conditional','Rejected')", name="decision_enum"
        ),
        CheckConstraint("length(remarks) >= 10", name="remarks_substantive"),
        # An override without a reason is not recordable.
        CheckConstraint(
            "NOT is_override OR (override_reason IS NOT NULL "
            "AND length(override_reason) >= 10)",
            name="override_needs_reason",
        ),
        Index("ix_decisions_vendor", "vendor_id"),
    )


# =====================================================================
# OPERATIONS
# =====================================================================


class Unlock(Base):
    """A paid FileSure unlock and its expiry.

    Recorded so the free GET can be skipped when a valid unlock is already
    known, and so nobody buys a second one for the same company inside the
    year. Unlocks are the cost driver — three of them outweigh 1,925 filing
    downloads.
    """

    __tablename__ = "unlocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    #: CIN for a company unlock, DIN for a director unlock.
    identifier: Mapped[str] = mapped_column(String(32), nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    cost_paisa: Mapped[int] = money()
    unlocked_at: Mapped[datetime] = created_at()
    #: TIMESTAMPTZ. Declared without timezone=True this became a naive
    #: TIMESTAMP: the UTC offset was silently DROPPED on write, and any
    #: Python comparison against an aware now() raised TypeError. Worse in
    #: SQL, where it does not raise — PostgreSQL reinterprets the naive
    #: value in the server's own TimeZone setting, so on a non-UTC server
    #: this expiry is wrong by that offset. It decides whether to spend
    #: ₹220 again, so "wrong by five and a half hours" is a duplicate
    #: charge or a company treated as unlocked when it is not.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("scope IN ('company','director')", name="scope_enum"),
        Index("ix_unlocks_lookup", "scope", "identifier", "expires_at"),
    )


class Job(Base):
    """An async FileSure refresh job.

    ``POST /update`` charges ₹150 at trigger time and returns immediately
    with ``status: pending``. Reading master data before the job completes
    returns the stale values you just paid to replace, so the poll state
    lives here rather than in memory. ``cooldown_until`` is roughly 48h —
    inside that window a re-audit cannot get fresh MCA data at any price.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    cin: Mapped[str] = mapped_column(String(24), nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    stages: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    cost_paisa: Mapped[int] = money()
    #: True when the provider billed but served cached data — the
    #: filings/refresh endpoint can do exactly that.
    from_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_at: Mapped[datetime] = created_at()
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Same defect as unlocks.expires_at, guarding the ₹5 filings refresh.
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed')", name="job_status_enum"
        ),
        Index("ix_jobs_cin", "cin", "requested_at"),
    )


class AuditLog(Base):
    """Append-only. Never updated, never deleted.

    Enforced by a database trigger, not by convention — see migration
    ``0002_audit_immutability``. Application code cannot be the only thing
    standing between an audit trail and a quiet edit, because application
    code is exactly what an investigation would be questioning.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = created_at()
    vendor_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context: Mapped[dict | None] = mapped_column(JsonB, nullable=True)

    __table_args__ = (
        Index("ix_audit_vendor_ts", "vendor_id", "ts"),
        Index("ix_audit_ts", "ts"),
    )


class FieldVisit(Base):
    """When surveillance was conducted and by whom."""

    __tablename__ = "field_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    visited_on: Mapped[Date] = mapped_column(Date, nullable=True)
    conducted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pct: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    gate_failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    filed_at: Mapped[datetime] = created_at()
