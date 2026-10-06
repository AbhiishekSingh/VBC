"""Eight real SCAN assessments, as the client scored them.

GROUND TRUTH, NOT A FIXTURE SOMEONE INVENTED
---------------------------------------------
These are eight vendors the client's own analysts assessed by hand in their
Excel workbook between April and August 2026 - three rejected, five approved.
Every rating, every intermediate total and every verdict below was read out
of those workbooks, not computed here.

That makes this file the only independent check on `score_scan` that exists.
Everything else in the test suite asserts that the code does what the code
was written to do.

WHAT THE WORKBOOK ACTUALLY DOES, WHERE IT DIFFERS FROM THIS CODEBASE
---------------------------------------------------------------------
Read `test_workbook_parity.py` for the measured gap. In summary:

* Pillar weights are S 0.2 / C 0.1 / **A 0.4** / **N 0.3**. The workbook
  carries the 0.6 / 0.1 split this codebase uses on a row it labels
  "Old Score", and computes with neither that row nor anything derived
  from it.
* The A pillar is the FOUR PSYCHOMETRIC SUB-SCORES - Integrity 50%,
  Business Acumen 30%, Risk Taking 10%, Problem Solving 10% - blended as
  `applicable_count * sub_weight` per rating. It is not a count of
  parameters, and its totals are fractional (Innovatiview scores A = 1.2).
* Site Surveillance and Conflict of Interest sit in **N**, not A. The N
  pillar is titled "Non Negotiable", not "Numbers".
* The verdict test is strict: `weighted > tolerance_60`, not `>=`.

The ratings are recorded verbatim, INCLUDING the exact option spellings the
workbook uses (">10 Years", not "> 10 Years"). Those spellings are half the
point: a parameter whose option strings do not match is silently dropped
from both sides of the fraction, and the vendor is scored against a smaller
bar without anyone being told.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorkbookCase:
    """One vendor, as the client's workbook scored them."""

    name: str
    nature: str
    ratings: dict[str, str | None]
    applicable: int
    weighted: float
    best: float
    tolerance_60: float
    pillar_totals: dict[str, float]
    verdict: str
    note: str = ""

    @property
    def positive(self) -> bool:
        return self.verdict.startswith("Positive")


WARIS_ALI = WorkbookCase(
    name="Waris Ali",
    nature="Glass & aluminium services",
    note=(
        "Proprietorship, GST unregistered - all billing routed through NR Enterprises, itself already onboarded. Street View showed a different firm at the registered address."
    ),
    ratings={
        "S1": "Partnership/ Proprietorship",         # Constitution -> Red
        "S2": ">10 Years",                           # Vintage -> Green
        "S3": "No",                                  # Social Profiling (Yes - Cata -> Red
        "S4": "Manufacturer/ Services",              # Type of Business -> Green
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Unregistered",                        # GST Registration -> Red
        "C2": None,                                  # Filling Status -> #N/A
        "C3": None,                                  # Registration type -> #N/A
        "C4": None,                                  # Suspension (if any) -> #N/A
        "C5": None,                                  # GST Address -> #N/A
        "A1": None,                                  # Integrity - 50% -> #N/A
        "A2": None,                                  # Business Acumen - 30% -> #N/A
        "A3": None,                                  # Risk Taking - 10% -> #N/A
        "A4": None,                                  # Problem Solving - 10% -> #N/A
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Local",                               # Reach -> Red
    },
    applicable=7,
    weighted=0.7,
    best=1.5,
    tolerance_60=0.9,
    pillar_totals={"S": 2, "C": 0, "A": 0.0, "N": 1},
    verdict="Negative for Onboarding",
)

DR_MED = WorkbookCase(
    name="DR MED HOME HEALTH SERVICES",
    nature="X-ray & ECG testing services",
    note=(
        "GST cancelled suo-moto eff. 31-12-2022 after 6 months of non-filing; no social presence; GST address residential; reach limited to Tamil Nadu."
    ),
    ratings={
        "S1": "Individual/ Proprietorship",          # Constitution -> Red
        "S2": "3-10 Years",                          # Vintage -> Yellow
        "S3": "No",                                  # Social Profiling (Yes - Cata -> Red
        "S4": "Manufacturer/ Services",              # Type of Business -> Green
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Registered",                          # GST Registration -> Green
        "C2": "Current Default (0-3 months)",        # Filling Status -> Red
        "C3": "Regular",                             # Registration type -> Green
        "C4": "Yes",                                 # Suspension (if any) -> Red
        "C5": "Residential",                         # GST Address -> Yellow
        "A1": None,                                  # Integrity - 50% -> #N/A
        "A2": None,                                  # Business Acumen - 30% -> #N/A
        "A3": None,                                  # Risk Taking - 10% -> #N/A
        "A4": None,                                  # Problem Solving - 10% -> #N/A
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Local",                               # Reach -> Red
    },
    applicable=11,
    weighted=0.85,
    best=1.9,
    tolerance_60=1.14,
    pillar_totals={"S": 1.5, "C": 2.5, "A": 0.0, "N": 1},
    verdict="Negative for Onboarding",
)

SHAMSUNNISA = WorkbookCase(
    name="Shamsunnisa Nabi Sarwar",
    nature="Electronic repair & service",
    note=(
        "Vendor email was a client-employee address. Only S1 was ever assessed."
    ),
    ratings={
        "S1": "Partnership/ Proprietorship",         # Constitution -> Red
        "S2": None,                                  # Vintage -> #N/A
        "S3": None,                                  # Social Profiling (Yes - Cata -> #N/A
        "S4": None,                                  # Type of Business -> #N/A
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": None,                                  # GST Registration -> #N/A
        "C2": None,                                  # Filling Status -> #N/A
        "C3": None,                                  # Registration type -> #N/A
        "C4": None,                                  # Suspension (if any) -> #N/A
        "C5": None,                                  # GST Address -> #N/A
        "A1": None,                                  # Integrity - 50% -> #N/A
        "A2": None,                                  # Business Acumen - 30% -> #N/A
        "A3": None,                                  # Risk Taking - 10% -> #N/A
        "A4": None,                                  # Problem Solving - 10% -> #N/A
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": None,                                  # Conflict of Interest (Employ -> #N/A
        "N4": None,                                  # Reach -> #N/A
    },
    applicable=1,
    weighted=0.0,
    best=0.2,
    tolerance_60=0.12,
    pillar_totals={"S": 0, "C": 0, "A": 0.0, "N": 0},
    verdict="Negative for Onboarding",
)

PULSEWAVE = WorkbookCase(
    name="Pulsewave Digital",
    nature="Marketing services",
    note=(
        "Unreachable after repeated attempts; contact and email matched another vendor code. Scored 1.34 against a 1.38 bar - negative by 0.04."
    ),
    ratings={
        "S1": None,                                  # Constitution -> #N/A
        "S2": None,                                  # Vintage -> #N/A
        "S3": None,                                  # Social Profiling (Yes - Cata -> #N/A
        "S4": None,                                  # Type of Business -> #N/A
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Unregistered",                        # GST Registration -> Red
        "C2": None,                                  # Filling Status -> #N/A
        "C3": None,                                  # Registration type -> #N/A
        "C4": None,                                  # Suspension (if any) -> #N/A
        "C5": None,                                  # GST Address -> #N/A
        "A1": "Non Vulnerable",                      # Integrity - 50% -> Green
        "A2": "Weak",                                # Business Acumen - 30% -> Red
        "A3": "Matured",                             # Risk Taking - 10% -> Green
        "A4": "Limited/ Active",                     # Problem Solving - 10% -> Yellow
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Local",                               # Reach -> Red
    },
    applicable=7,
    weighted=1.34,
    best=2.3,
    tolerance_60=1.38,
    pillar_totals={"S": 0, "C": 0, "A": 2.6, "N": 1},
    verdict="Negative for Onboarding",
)

DIAGNOSTIX = WorkbookCase(
    name="DiagnostiX Services Private Limited",
    nature="IT consulting and support",
    ratings={
        "S1": "Private Ltd",                         # Constitution -> Yellow
        "S2": "3-10 Years",                          # Vintage -> Yellow
        "S3": "Yes",                                 # Social Profiling (Yes - Cata -> Green
        "S4": "Manufacturer/ Services",              # Type of Business -> Green
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Registered",                          # GST Registration -> Green
        "C2": "Regular",                             # Filling Status -> Green
        "C3": "Regular",                             # Registration type -> Green
        "C4": "No",                                  # Suspension (if any) -> Green
        "C5": "Commercial",                          # GST Address -> Green
        "A1": None,                                  # Integrity - 50% -> #N/A
        "A2": None,                                  # Business Acumen - 30% -> #N/A
        "A3": None,                                  # Risk Taking - 10% -> #N/A
        "A4": None,                                  # Problem Solving - 10% -> #N/A
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Pan India",                           # Reach -> Green
    },
    applicable=11,
    weighted=1.7,
    best=1.9,
    tolerance_60=1.14,
    pillar_totals={"S": 3, "C": 5, "A": 0.0, "N": 2},
    verdict="Positive for Onboarding",
)

INTECH = WorkbookCase(
    name="Intech System",
    nature="IT infrastructure and telecom",
    ratings={
        "S1": "Partnership/ Proprietorship",         # Constitution -> Red
        "S2": ">10 Years",                           # Vintage -> Green
        "S3": "Yes",                                 # Social Profiling (Yes - Cata -> Green
        "S4": "Manufacturer/ Services",              # Type of Business -> Green
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Registered",                          # GST Registration -> Green
        "C2": "Regular",                             # Filling Status -> Green
        "C3": "Regular",                             # Registration type -> Green
        "C4": "No",                                  # Suspension (if any) -> Green
        "C5": "Commercial",                          # GST Address -> Green
        "A1": None,                                  # Integrity - 50% -> #N/A
        "A2": None,                                  # Business Acumen - 30% -> #N/A
        "A3": None,                                  # Risk Taking - 10% -> #N/A
        "A4": None,                                  # Problem Solving - 10% -> #N/A
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Pan India",                           # Reach -> Green
    },
    applicable=11,
    weighted=1.7,
    best=1.9,
    tolerance_60=1.14,
    pillar_totals={"S": 3, "C": 5, "A": 0.0, "N": 2},
    verdict="Positive for Onboarding",
)

REVASSURE = WorkbookCase(
    name="RevAssure Business Management Services Pvt Ltd",
    nature="Accounts receivable management",
    ratings={
        "S1": "Private Ltd",                         # Constitution -> Yellow
        "S2": "3-10 Years",                          # Vintage -> Yellow
        "S3": "Yes",                                 # Social Profiling (Yes - Cata -> Green
        "S4": "Manufacturer/ Services",              # Type of Business -> Green
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Registered",                          # GST Registration -> Green
        "C2": "Regular",                             # Filling Status -> Green
        "C3": "Regular",                             # Registration type -> Green
        "C4": "No",                                  # Suspension (if any) -> Green
        "C5": "Commercial",                          # GST Address -> Green
        "A1": None,                                  # Integrity - 50% -> #N/A
        "A2": None,                                  # Business Acumen - 30% -> #N/A
        "A3": None,                                  # Risk Taking - 10% -> #N/A
        "A4": None,                                  # Problem Solving - 10% -> #N/A
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Pan India",                           # Reach -> Green
    },
    applicable=11,
    weighted=1.7,
    best=1.9,
    tolerance_60=1.14,
    pillar_totals={"S": 3, "C": 5, "A": 0.0, "N": 2},
    verdict="Positive for Onboarding",
)

INNOVATIVIEW = WorkbookCase(
    name="Innovatiview Rental Solutions Private Limited",
    nature="Security & surveillance for examinations",
    note=(
        "The only case with the psychometric test completed - the only exercise of the A pillar."
    ),
    ratings={
        "S1": "Private Ltd",                         # Constitution -> Yellow
        "S2": "3-10 Years",                          # Vintage -> Yellow
        "S3": "Yes",                                 # Social Profiling (Yes - Cata -> Green
        "S4": "Manufacturer/ Services",              # Type of Business -> Green
        "S5": None,                                  # Infrastructure -> #N/A
        "C1": "Registered",                          # GST Registration -> Green
        "C2": "Regular",                             # Filling Status -> Green
        "C3": "Regular",                             # Registration type -> Green
        "C4": "No",                                  # Suspension (if any) -> Green
        "C5": "Commercial",                          # GST Address -> Green
        "A1": "Vulnerable",                          # Integrity - 50% -> Red
        "A2": "Limited/ Opportunistic",              # Business Acumen - 30% -> Yellow
        "A3": "Limited/ Constructive",               # Risk Taking - 10% -> Yellow
        "A4": "Pro-active",                          # Problem Solving - 10% -> Green
        "N1": None,                                  # Credit Period Offered (Stand -> #N/A
        "N2": None,                                  # Site Surveliance - As per de -> #N/A
        "N3": "Negative",                            # Conflict of Interest (Employ -> Green
        "N4": "Pan India",                           # Reach -> Green
    },
    applicable=15,
    weighted=2.18,
    best=3.5,
    tolerance_60=2.1,
    pillar_totals={"S": 3, "C": 5, "A": 1.2, "N": 2},
    verdict="Positive for Onboarding",
)

#: Every case, in the order they were assessed.
WORKBOOK_CASES: tuple[WorkbookCase, ...] = (
    WARIS_ALI, DR_MED, SHAMSUNNISA, PULSEWAVE,
    DIAGNOSTIX, INTECH, REVASSURE, INNOVATIVIEW,
)

assert len(WORKBOOK_CASES) == 8
#: FOUR negative, four positive — not the 5/3 the folder names imply.
#: `Pulsewave Digital.xlsx` was filed under "Positive SCAN cases", and its own
#: Outcome sheet reads "Negative for Onboarding" (1.34 against a 1.38 bar).
#: The tracker agrees with the workbook. The folder is simply misfiled, and
#: that is itself the argument for computing the verdict rather than typing it.
assert sum(1 for c in WORKBOOK_CASES if c.positive) == 4
assert sum(1 for c in WORKBOOK_CASES if not c.positive) == 4