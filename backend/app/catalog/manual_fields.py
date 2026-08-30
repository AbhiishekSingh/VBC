"""The manual field library — everything an API cannot answer.

Two design rules carry the weight here:

1. ONE PARAMETER, ONE FIELD. "Physical availability of office" is
   deliberately NOT mapped to S5; "Office ownership" is. Two fields writing
   the same SCAN parameter would make the score depend on entry order.

2. ANALYST-STATED IS NOT VERIFIED. Every entry carries an analyst id and a
   timestamp and is rendered in its own block, never mixed into the sourced
   findings. Nobody independent confirmed it.

The worked example for why this module exists: Kaveri Traders' GSTIN is
suspended. With no GST provider configured, no automated check surfaces
that. An analyst recorded it by hand, m6 maps it to C4, and Kaveri drops
from 62.5% PASS to 36.4% FAIL. Manual fields are what close that gap.
"""

from __future__ import annotations

from app.domain.types import FieldType, ManualFieldTemplate

YES_NO, CHOICE, TEXT, NUMBER, DATE = (
    FieldType.YES_NO,
    FieldType.CHOICE,
    FieldType.TEXT,
    FieldType.NUMBER,
    FieldType.DATE,
)

PREMISES, COMPLIANCE, COMMERCIAL, CUSTOM = (
    "Premises",
    "Compliance",
    "Commercial",
    "Custom",
)

FIELD_CATEGORIES: tuple[str, ...] = (PREMISES, COMPLIANCE, COMMERCIAL, CUSTOM)

MANUAL_TEMPLATES: tuple[ManualFieldTemplate, ...] = (
    # ---- Premises ---------------------------------------------------------
    ManualFieldTemplate(
        id="m1",
        label="Physical availability of office",
        type=YES_NO,
        category=PREMISES,
        options=("Yes", "No"),
        # Intentionally unmapped: "is there an office" and "is it owned or
        # rented" are different questions. See rule 1 in the module docstring.
    ),
    ManualFieldTemplate(
        id="m2",
        label="Office ownership",
        type=CHOICE,
        category=PREMISES,
        options=("Owned", "Rented", "Shared", "Not verified"),
        maps_to="S5",
        map_when={"Owned": "Owned", "Rented": "Rented"},
    ),
    ManualFieldTemplate(
        id="m3",
        label="Signage / nameboard present at premises",
        type=YES_NO,
        category=PREMISES,
        options=("Yes", "No"),
    ),
    ManualFieldTemplate(
        id="m4", label="Staff present at time of visit", type=NUMBER, category=PREMISES
    ),
    ManualFieldTemplate(id="m5", label="Site visit date", type=DATE, category=PREMISES),
    # ---- Compliance -------------------------------------------------------
    ManualFieldTemplate(
        id="m6",
        label="GST status (checked manually on the portal)",
        type=CHOICE,
        category=COMPLIANCE,
        options=("Active", "Suspended", "Cancelled", "Not registered"),
        maps_to="C4",
        map_when={"Active": "No", "Suspended": "Yes", "Cancelled": "Yes"},
        hint="Stopgap until the GST API is configured",
    ),
    ManualFieldTemplate(
        id="m7", label="GST certificate collected", type=YES_NO,
        category=COMPLIANCE, options=("Yes", "No"),
    ),
    ManualFieldTemplate(
        id="m8", label="PAN card copy collected", type=YES_NO,
        category=COMPLIANCE, options=("Yes", "No"),
    ),
    ManualFieldTemplate(
        id="m9", label="Cancelled cheque / bank proof collected", type=YES_NO,
        category=COMPLIANCE, options=("Yes", "No"),
    ),
    ManualFieldTemplate(
        id="m10", label="Self-declaration signed by vendor", type=YES_NO,
        category=COMPLIANCE, options=("Yes", "No"),
    ),
    ManualFieldTemplate(
        id="m11", label="Principal authorisation letter (dealers only)",
        type=YES_NO, category=COMPLIANCE,
        options=("Yes", "No", "Not applicable"),
    ),
    # ---- Commercial -------------------------------------------------------
    ManualFieldTemplate(
        id="m12",
        label="Type of business",
        type=CHOICE,
        category=COMMERCIAL,
        options=("Manufacturer/ Services", "Wholesaler", "Retailer/ Trader"),
        maps_to="S4",
        map_when={
            "Manufacturer/ Services": "Manufacturer/ Services",
            "Wholesaler": "Wholesaler",
            "Retailer/ Trader": "Retailer/ Trader",
        },
    ),
    ManualFieldTemplate(
        id="m13", label="Credit period offered (days)", type=NUMBER, category=COMMERCIAL
    ),
    ManualFieldTemplate(
        id="m14", label="Named reference — company", type=TEXT, category=COMMERCIAL
    ),
    ManualFieldTemplate(
        id="m15",
        label="Reference feedback",
        type=CHOICE,
        category=COMMERCIAL,
        options=("Good", "Average", "Poor"),
        maps_to="A4",
        map_when={"Good": "Good", "Average": "Average", "Poor": "Poor"},
    ),
    ManualFieldTemplate(
        id="m16", label="Certifications held (ISO / FSSAI / other)",
        type=TEXT, category=COMMERCIAL,
    ),
    ManualFieldTemplate(
        id="m17", label="Years of dealing with us", type=NUMBER, category=COMMERCIAL
    ),
)

TEMPLATES_BY_ID: dict[str, ManualFieldTemplate] = {t.id: t for t in MANUAL_TEMPLATES}

assert len(MANUAL_TEMPLATES) == 17

# No two templates may write the same SCAN parameter — see rule 1.
_mapped = [t.maps_to for t in MANUAL_TEMPLATES if t.maps_to]
assert len(_mapped) == len(set(_mapped)), "two templates map to one SCAN parameter"
