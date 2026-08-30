"""The three seeded vendors, used as regression fixtures.

These come from the signed-off prototype and their scores are the contract.
If a change to the scoring engine moves any number here, that change
re-scores every vendor already on file and needs a migration plan — the
test failure is the alarm, not an inconvenience to be edited away.

  #234478 Azahan Advertising   0.90 / 1.50 · 60.0% PASS   risk 50 DEEP REVIEW
  #234479 Meridian Packaging   3.80 / 3.90 · 97.4% PASS   risk 95 APPROVE
  #234480 Kaveri Traders       0.40 / 1.10 · 36.4% FAIL   risk 30 REJECT

Azahan is the uncomfortable one and it is kept deliberately: an
unincorporated proprietorship with no premises and no web presence that
reaches exactly the 60.0% threshold on 6 of 18 parameters. A human
overrode it to Rejected. It is the evidence for the coverage-floor
decision.
"""

from __future__ import annotations

from app.domain.types import CheckResult, CheckStatus, FieldType, ManualEntry

PASS, WARN, FAIL, SKIP = (
    CheckStatus.PASS,
    CheckStatus.WARN,
    CheckStatus.FAIL,
    CheckStatus.SKIP,
)


def _results(raw: dict[str, tuple[CheckStatus, str, str]]) -> dict[str, CheckResult]:
    return {
        cid: CheckResult(check_id=cid, status=status, value=value, detail=detail)
        for cid, (status, value, detail) in raw.items()
    }


# =====================================================================
# #234478 · Azahan Advertising — the thin-audit case
# =====================================================================

AZAHAN_SELECTED = [
    "ustatus", "master", "resolve", "dirs", "whois", "avail", "cdx", "dup", "conflict",
]

AZAHAN_CHECKS = _results({
    "resolve": (WARN, "No CIN found",
                "No MCA registration traced for this name — consistent with a sole proprietorship"),
    "master": (FAIL, "Not a registered company",
               "No CIN — entity is unincorporated, MCA holds no record"),
    "dirs": (SKIP, "N/A", "No directors — proprietorship"),
    "whois": (FAIL, "No domain", "No registered domain traced to this entity"),
    "avail": (FAIL, "Never archived",
              "archived_snapshots empty — no web presence on record"),
    "cdx": (SKIP, "N/A", "No domain to build a timeline from"),
    "dup": (PASS, "No duplicate", "No matching GST/PAN in the vendor master"),
    "conflict": (PASS, "No conflict", "No overlap with employee records"),
})

#: C4 is set by manual entry m6 (GST checked by hand = Active -> "No").
AZAHAN_SCAN = {
    "S1": "Individual/ Proprietorship", "S2": "< 3 Years", "S3": "No",
    "S4": "Manufacturer/ Services", "S5": None,
    "C1": None, "C2": None, "C3": None, "C4": "No", "C5": None,
    "A1": None, "A2": None, "A3": "Positive", "A4": None,
    "N1": None, "N2": None, "N3": None, "N4": None,
}

AZAHAN_MANUAL = [
    ManualEntry(
        key="Physical availability of office", value="No", type=FieldType.YES_NO,
        template_id="m1", entered_by="r.iyer", entered_at="2026-07-24 13:40",
        note="Address is a residential chawl; no commercial signage or office found.",
    ),
    ManualEntry(
        key="GST status (checked manually on the portal)", value="Active",
        type=FieldType.CHOICE, template_id="m6", entered_by="r.iyer",
        entered_at="2026-07-24 13:42",
        note="Verified on the GST portal by hand — API not configured.",
    ),
    ManualEntry(
        key="Years trading before application", value="2", type=FieldType.NUMBER,
        entered_by="r.iyer", entered_at="2026-07-24 13:45",
        note="Custom field. Stated by the vendor, not independently confirmed.",
    ),
]


# =====================================================================
# #234479 · Meridian Packaging — the healthy case
# =====================================================================

MERIDIAN_SELECTED = [
    "ustatus", "master", "dirs", "dprof", "charges", "filings", "fin",
    "whois", "reput", "ssl", "rwhois", "avail", "cdx", "dup", "rp", "conflict",
]

MERIDIAN_CHECKS = _results({
    "master": (PASS, "ACTIVE · U21029MH2013PTC245119",
               "Incorporated 04-Jun-2013 · Private Limited · paid-up ₹1.2 Cr"),
    "dirs": (PASS, "2 directors",
             "R. Deshmukh (DIN 03412887), S. Deshmukh (DIN 03412901) — both active"),
    "dprof": (PASS, "Profiles retrieved",
              "S. Deshmukh holds 3 other directorships, all active"),
    "charges": (WARN, "1 open charge ₹2.4 Cr",
                "HDFC Bank, created 15-Mar-2022, not satisfied. 4 earlier charges closed."),
    "filings": (PASS, "Filings current",
                "AOC-4 and MGT-7 filed for FY2024 on 30-Sep-2024"),
    "fin": (PASS, "Revenue ₹41.2 Cr · PAT ₹1.8 Cr",
            "AOC-4 FY2023-24 standalone · net worth ₹8.9 Cr"),
    "whois": (PASS, "Domain age 11 yrs",
              "meridianpack.in registered 2015, renewed to 2028"),
    "reput": (PASS, "Trust score 91.2", "No blacklist, phishing or malware flags"),
    "ssl": (PASS, "Valid SSL", "Let's Encrypt · valid chain · HTTPS enforced"),
    "rwhois": (PASS, "3 domains, same owner", "All three are Meridian group brands"),
    "avail": (PASS, "Archived since 2015",
              "First capture 12-Aug-2015 · last capture 03-Aug-2026"),
    "cdx": (PASS, "412 captures, no outages", "Continuous presence since 2015"),
    "dup": (PASS, "No duplicate", "No matching GST/PAN in the vendor master"),
    "rp": (WARN, "Possible related party",
           "Director S. Deshmukh is also a director at vendor Meridian Logistics"),
    "conflict": (PASS, "No conflict", "No overlap with employee records"),
})

MERIDIAN_SCAN = {
    "S1": "Private Ltd", "S2": "> 10 Years", "S3": "Yes",
    "S4": "Manufacturer/ Services", "S5": "Owned",
    "C1": None, "C2": None, "C3": None, "C4": "No", "C5": None,
    "A1": "On-board", "A2": "Positive", "A3": "Positive", "A4": "Good",
    "N1": "Industry", "N2": "More than 5", "N3": "2 Cr / 1 Cr", "N4": "State",
}

MERIDIAN_SURVEILLANCE = {
    "V1": "Yes", "V2": "High", "V3": "Yes", "V4": "Yes", "V5": "Strong",
    "V6": "At Par", "V7": "At Par", "V8": "Satisfactory", "V9": "NA",
    "V10": "Strong", "V11": "Yes", "V12": "Yes", "V13": "State",
}


# =====================================================================
# #234480 · Kaveri Traders — caught only by a manual entry
# =====================================================================

KAVERI_SELECTED = [
    "ustatus", "master", "resolve", "whois", "reput", "ssl", "avail", "cdx", "dup",
]

KAVERI_CHECKS = _results({
    "resolve": (WARN, "No CIN found", "Partnership firm — not registered with MCA"),
    "master": (FAIL, "Not a registered company",
               "No CIN — MCA holds no record for a partnership firm"),
    "whois": (WARN, "Domain age 8 months",
              "kaveritraders.co.in registered Nov-2025 · registrant privacy-protected"),
    "reput": (WARN, "Trust score 54.8",
              "Recently registered domain · registrant details redacted"),
    "ssl": (FAIL, "Self-signed certificate", "Certificate not issued by a trusted CA"),
    "avail": (WARN, "Archived since Dec-2025", "First capture 14-Dec-2025"),
    "cdx": (WARN, "19 captures, 1 outage",
            "Site returned 403 for a 6-week period, Feb–Mar 2026"),
    "dup": (WARN, "Possible duplicate",
            "Similar name and same PIN code as existing vendor #231902"),
})

#: C4 is "Yes" (suspended) purely because of manual entry m6. Without it
#: this vendor scores 62.5% and passes.
KAVERI_SCAN = {
    "S1": "Partnership/LLP", "S2": "< 3 Years", "S3": "Yes",
    "S4": "Retailer/ Trader", "S5": "Rented",
    "C1": None, "C2": None, "C3": None, "C4": "Yes", "C5": None,
    "A1": None, "A2": None, "A3": None, "A4": None,
    "N1": None, "N2": None, "N3": None, "N4": None,
}

#: The same vendor with the manual GST entry removed — the counterfactual
#: that proves manual fields carry real weight.
KAVERI_SCAN_WITHOUT_MANUAL_GST = {**KAVERI_SCAN, "C4": None}
