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
        options=(
            ("Listed/Public", G),
            ("Private Ltd", G),
            ("Partnership/LLP", Y),
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
        options=(("> 10 Years", G), ("3 - 10 Years", Y), ("< 3 Years", R)),
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
    # ---- C · Compliance (0.1) — every parameter waits on the GST API ------
    ScanParameter(
        id="C1",
        pillar=Pillar.C,
        label="GST Registration",
        source=SourceMode.HOOK,
        feed="GST API — not configured",
        fed_by="gst",
        options=(("Registered", G), ("Not Applicable", Y), ("Unregistered", R)),
    ),
    ScanParameter(
        id="C2",
        pillar=Pillar.C,
        label="Filing Status",
        source=SourceMode.HOOK,
        feed="GST API — not configured",
        fed_by="gst",
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
        source=SourceMode.HOOK,
        feed="GST API — not configured",
        fed_by="gst",
        options=(("Regular", G), ("Composite", Y)),
    ),
    ScanParameter(
        id="C4",
        pillar=Pillar.C,
        label="Suspension (if any)",
        source=SourceMode.HOOK,
        feed="GST API — not configured",
        fed_by="gst",
        options=(("No", G), ("Yes", R)),
    ),
    ScanParameter(
        id="C5",
        pillar=Pillar.C,
        label="GST Address",
        source=SourceMode.HOOK,
        feed="GST API — not configured",
        fed_by="gst",
        options=(("Commercial", G), ("Residential", Y)),
    ),
    # ---- A · Assessment (0.6) — the heaviest pillar, almost entirely human
    ScanParameter(
        id="A1",
        pillar=Pillar.A,
        label="Psychometric Test Result",
        source=SourceMode.HUMAN,
        feed="External assessment",
        options=(("On-board", G), ("Reject", R)),
    ),
    ScanParameter(
        id="A2",
        pillar=Pillar.A,
        label="Site Surveillance",
        source=SourceMode.HUMAN,
        feed="Site Surveillance module",
        options=(("Positive", G), ("Negative", R)),
    ),
    ScanParameter(
        id="A3",
        pillar=Pillar.A,
        label="Conflict of Interest (Employees)",
        source=SourceMode.AUTO,
        feed="Internal check over MCA director data",
        fed_by="conflict",
        options=(("Positive", G), ("Negative", R)),
    ),
    ScanParameter(
        id="A4",
        pillar=Pillar.A,
        label="Market References",
        source=SourceMode.HUMAN,
        feed="Analyst reference calls",
        options=(("Good", G), ("Average", Y), ("Poor", R)),
    ),
    # ---- N · Numbers (0.1) ------------------------------------------------
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
        label="Big Players in Clientele",
        source=SourceMode.HUMAN,
        feed="Reference check",
        options=(("More than 5", G), ("1 to 5", Y), ("Zero", R)),
    ),
    # N3 is an upgrade over the client's original workbook: turnover was an
    # analyst estimate, FileSure's XBRL extractions make it a filed fact.
    ScanParameter(
        id="N3",
        pillar=Pillar.N,
        label="Turnover of the Vendor",
        source=SourceMode.AUTO,
        feed="MCA filed financials (AOC-4)",
        fed_by="fin",
        options=(
            ("2 Cr / 1 Cr", G),
            ("> 50 Lac / 25 Lac", Y),
            ("< 50 Lac / 25 Lac", R),
        ),
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
