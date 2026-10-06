"""The SCAN framework: 18 parameters across 4 weighted pillars.

This mirrors the client's Excel workbook exactly. Options, their order and
their ratings are part of the audit contract — changing any of them changes
historical scores and must be treated as a versioned migration, not an edit.
"""

from __future__ import annotations

from app.domain.types import Pillar, Rating, ScanParameter, SourceMode

G, Y, R = Rating.G, Rating.Y, Rating.R

SCAN_PARAMETERS: tuple[ScanParameter, ...] = (
    # ---- S · Stature (0.2) ------------------------------------------------
    ScanParameter(
        id="S1",
        pillar=Pillar.S,
        label="Constitution",
        source=SourceMode.AUTO,
        feed="MCA company status",
        fed_by="master",
        #: "Private Ltd" is YELLOW, not Green. It was Green here until
        #: 5 Oct 2026, which handed a free positive to every private limited
        #: company — i.e. to almost every vendor. The workbook's Green is
        #: Listed/Public alone: a company answerable to a regulator and a
        #: public filing calendar is a different proposition from one that
        #: is not, and the middle tier is the ordinary case.
        #:
        #: The workbook offers three tiers and spells the bottom one
        #: "Partnership/ Proprietorship" in some files and "Individual/
        #: Proprietorship" in others; both are its Red column. "Partnership/
        #: LLP" is this codebase's own addition, rated Yellow, and is kept
        #: because an analyst has already recorded a judgement under it — an
        #: LLP is a filed, audited entity and does not belong in the same tier
        #: as a sole proprietor.
        options=(
            ("Listed/Public", G),
            ("Private Ltd", Y),
            ("Partnership/LLP", Y),
            ("Partnership/ Proprietorship", R),
            ("Individual/ Proprietorship", R),
        ),
    ),
    ScanParameter(
        id="S2",
        pillar=Pillar.S,
        label="Vintage",
        source=SourceMode.AUTO,
        feed="MCA incorporation date",
        fed_by="master",
        #: The workbook writes ">10 Years"; this codebase wrote "> 10 Years"
        #: and has rows in the database under it. `ScanParameter.rate` compares
        #: on letters and digits only, so both resolve without an alias — but
        #: the canonical spelling here is now the workbook's, because that is
        #: the one an analyst will be looking at.
        options=((">10 Years", G), ("3-10 Years", Y), ("< 3 Years", R)),
    ),
    ScanParameter(
        id="S3",
        pillar=Pillar.S,
        label="Social Profiling (website, catalogue, directories)",
        source=SourceMode.AUTO,
        feed="Domain + archive evidence",
        fed_by="cdx",
        options=(("Yes", G), ("No", R)),
    ),
    ScanParameter(
        id="S4",
        pillar=Pillar.S,
        label="Type of Business",
        source=SourceMode.HUMAN,
        feed="Analyst classification",
        options=(
            ("Manufacturer/ Services", G),
            ("Wholesaler", Y),
            ("Retailer/ Trader", R),
        ),
    ),
    ScanParameter(
        id="S5",
        pillar=Pillar.S,
        label="Infrastructure",
        source=SourceMode.HUMAN,
        feed="Site surveillance",
        options=(("Owned", G), ("Rented", Y)),
    ),
    # ---- C · Compliance (0.1) — live via FinAGG GSP (Common APIs) --------
    #
    # C1, C3, C4, C5 come from one search call; C2 from returns metadata.
    # Neither needs the taxpayer's consent. C5 is the weak one: GSTN has
    # no residential flag, so it is set only when the nature-of-business
    # field positively indicates commercial premises, and left for an
    # analyst otherwise rather than inferred.
    ScanParameter(
        id="C1",
        pillar=Pillar.C,
        label="GST Registration",
        source=SourceMode.AUTO,
        feed="FinAGG GSP — common search",
        fed_by="gst",
        options=(("Registered", G), ("Not Applicable", Y), ("Unregistered", R)),
    ),
    ScanParameter(
        id="C2",
        pillar=Pillar.C,
        label="Filing Status",
        source=SourceMode.AUTO,
        feed="FinAGG GSP — returns metadata",
        fed_by="gstret",
        options=(
            ("Regular", G),
            ("History of Default", Y),
            ("Current Default (0-3 months)", R),
        ),
    ),
    ScanParameter(
        id="C3",
        pillar=Pillar.C,
        label="Registration Type",
        source=SourceMode.AUTO,
        feed="FinAGG GSP — common search",
        fed_by="gst",
        options=(("Regular", G), ("Composite", Y)),
    ),
    ScanParameter(
        id="C4",
        pillar=Pillar.C,
        label="Suspension (if any)",
        source=SourceMode.AUTO,
        feed="FinAGG GSP — common search",
        fed_by="gst",
        options=(("No", G), ("Yes", R)),
    ),
    ScanParameter(
        id="C5",
        pillar=Pillar.C,
        label="GST Address",
        source=SourceMode.AUTO,
        feed="FinAGG GSP — common search",
        fed_by="gst",
        options=(("Commercial", G), ("Residential", Y)),
    ),
    # ---- A · Assessment (0.4) — the psychometric test, and nothing else ----
    #
    # This pillar IS the psychometric test, broken into its four dimensions
    # with their own internal weights. It is not a mixed bag of assessment
    # activities: site surveillance and conflict of interest sit in N, where
    # the workbook puts them.
    #
    # The sub-weights are why `score_scan` cannot simply count this pillar.
    # Each rated dimension contributes `applicable_count * sub_weight` to its
    # colour, so pillar totals come out fractional — Innovatiview scores 1.2,
    # which no count of four parameters can produce.
    #
    # Integrity carries half the test on its own. A vendor can be capable,
    # commercially sharp and a good problem-solver, and one Vulnerable on
    # integrity still takes 50% of the pillar off them. That is the client's
    # judgement about what matters, expressed as arithmetic.
    ScanParameter(
        id="A1",
        pillar=Pillar.A,
        label="Integrity",
        source=SourceMode.HUMAN,
        feed="Psychometric test — 50%",
        sub_weight=0.5,
        options=(("Non Vulnerable", G), ("Vulnerable", R)),
    ),
    ScanParameter(
        id="A2",
        pillar=Pillar.A,
        label="Business Acumen",
        source=SourceMode.HUMAN,
        feed="Psychometric test — 30%",
        sub_weight=0.3,
        options=(("Matured", G), ("Limited/ Opportunistic", Y), ("Weak", R)),
    ),
    ScanParameter(
        id="A3",
        pillar=Pillar.A,
        label="Risk Taking",
        source=SourceMode.HUMAN,
        feed="Psychometric test — 10%",
        sub_weight=0.1,
        options=(("Matured", G), ("Limited/ Constructive", Y), ("Weak", R)),
    ),
    ScanParameter(
        id="A4",
        pillar=Pillar.A,
        label="Problem Solving",
        source=SourceMode.HUMAN,
        feed="Psychometric test — 10%",
        sub_weight=0.1,
        options=(("Pro-active", G), ("Limited/ Active", Y), ("Weak", R)),
    ),
    # ---- N · Non Negotiable (0.3) -----------------------------------------
    #
    # Not "Numbers". These are the must-pass checks, and the client tripled
    # their weight when they halved the psychometric test's.
    ScanParameter(
        id="N1",
        pillar=Pillar.N,
        label="Credit Period Offered",
        source=SourceMode.HUMAN,
        feed="Commercial terms",
        options=(
            ("Better than Industry", G),
            ("Industry", Y),
            ("Lower than Industry", R),
        ),
    ),
    ScanParameter(
        id="N2",
        pillar=Pillar.N,
        label="Site Surveillance",
        source=SourceMode.HUMAN,
        feed="Site Surveillance module",
        options=(("Positive", G), ("Negative", R)),
    ),
    #: THE RATINGS HERE ARE THE REVERSE OF WHAT THEY READ LIKE, and were
    #: inverted in this codebase until 5 Oct 2026.
    #:
    #: "Negative" is the GOOD answer: the conflict-of-interest check came back
    #: negative, i.e. no client employee was found behind this vendor. A
    #: vendor WITH a conflict scored Green here. That is the single most
    #: consequential rating in the file to have backwards, because the whole
    #: point of the check is to catch an employee quietly selling to their own
    #: employer.
    ScanParameter(
        id="N3",
        pillar=Pillar.N,
        label="Conflict of Interest (Employees)",
        source=SourceMode.AUTO,
        feed="Internal check over MCA director data",
        fed_by="conflict",
        options=(("Negative", G), ("Positive", R)),
    ),
    ScanParameter(
        id="N4",
        pillar=Pillar.N,
        label="Reach",
        source=SourceMode.HUMAN,
        feed="Analyst assessment",
        options=(("Pan India", G), ("State", Y), ("Local", R)),
    ),
)

#: Dropped from the catalogue on 5 Oct 2026, because the client's live
#: workbook does not have them. Recorded rather than deleted silently: each
#: was a reasonable idea, and someone will propose them again.
#:
#:   A4 Market References        — analyst reference calls
#:   N2 Big Players in Clientele — reference check
#:   N3 Turnover of the Vendor   — this codebase's own upgrade, turning an
#:                                 analyst estimate into a filed XBRL fact.
#:                                 Genuinely better than what it replaced, and
#:                                 still not in the client's model.
#:
#: Turnover is the one worth arguing for. If the client wants it back it is a
#: new parameter under a new id, not a revival of N3 — that id now means
#: Conflict of Interest, and reusing it would make two different questions
#: share one column of history.
RETIRED_PARAMETERS: tuple[str, ...] = (
    "Market References",
    "Big Players in Clientele",
    "Turnover of the Vendor",
)

SCAN_BY_ID: dict[str, ScanParameter] = {p.id: p for p in SCAN_PARAMETERS}


def scan_parameter(param_id: str) -> ScanParameter:
    try:
        return SCAN_BY_ID[param_id]
    except KeyError:
        raise KeyError(f"Unknown SCAN parameter: {param_id!r}") from None


#: Best achievable when every one of the 18 parameters is applicable.
#: Kept as a module constant so a drifted catalog fails loudly in tests.
BEST_ACHIEVABLE_ALL: float = round(
    sum(p.weight for p in SCAN_PARAMETERS), 4
)

assert len(SCAN_PARAMETERS) == 18, "SCAN must define exactly 18 parameters"
assert BEST_ACHIEVABLE_ALL == 4.3, f"expected 4.30, got {BEST_ACHIEVABLE_ALL}"
