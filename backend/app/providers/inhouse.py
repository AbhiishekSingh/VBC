"""In-house checks: duplicate vendor, related party, director conflict.

No external API, no cost. Computed over data already held.

These were stubs in the prototype. Real matching matters because all three
answer questions an external provider cannot: whether this "new" vendor is
already on the books under another name, whether it shares a director with
an existing supplier, and whether an employee sits on its board.

A MATCH IS NOT A VERDICT. A shared director between a vendor and an
existing supplier is frequently a legitimate group structure. The check
surfaces it as a disclosure to record, and the analyst decides. Every match
carries the rule that fired and a confidence, so a reader can weigh it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Vendor, VendorCheck


@dataclass
class MatchResult:
    matched: bool
    compared_against: int
    matches: list[dict] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)

    def as_payload(self) -> dict:
        return {
            "matched": self.matched,
            "comparedAgainst": self.compared_against,
            "matches": self.matches,
            "rules": self.rules,
        }


# ---------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------

#: Suffixes that carry no identifying information. "Meridian Packaging
#: Private Limited" and "Meridian Packaging Pvt Ltd" are the same business.
_LEGAL_SUFFIXES = (
    "private limited", "pvt ltd", "pvt. ltd.", "p ltd", "limited", "ltd",
    "llp", "limited liability partnership", "and company", "& co", "and co",
    "enterprises", "enterprise", "industries", "trading company",
)


def normalise_name(name: str | None) -> str:
    """Strip case, punctuation and legal suffixes for comparison."""
    if not name:
        return ""
    text = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in sorted(_LEGAL_SUFFIXES, key=len, reverse=True):
        if text.endswith(" " + suffix):
            text = text[: -(len(suffix) + 1)].strip()
    return text


def pin_from_address(address: str | None) -> str | None:
    """Indian PIN codes are six digits, and are the most reliable part of a
    free-text address for matching."""
    if not address:
        return None
    match = re.search(r"\b(\d{6})\b", address)
    return match.group(1) if match else None


def pan_from_gstin(gstin: str | None) -> str | None:
    """A GSTIN embeds the PAN at positions 3-12.

    So a vendor submitted with only a GSTIN can still be matched against one
    submitted with only a PAN — which is the common real-world case.
    """
    if not gstin or len(gstin) < 15:
        return None
    candidate = gstin[2:12].upper()
    return candidate if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", candidate) else None


# ---------------------------------------------------------------------
# Duplicate vendor
# ---------------------------------------------------------------------


def check_duplicate(session: Session, vendor: Vendor) -> MatchResult:
    """Is this vendor already on the books under another record?

    Rules run strongest-first. An exact GSTIN or CIN match is conclusive; a
    normalised name plus the same PIN code is a strong signal that still
    wants a human look.
    """
    others = session.scalars(select(Vendor).where(Vendor.id != vendor.id)).all()
    matches: list[dict] = []
    rules: list[dict] = []

    vendor_pan = (vendor.pan or "").upper() or pan_from_gstin(vendor.gst)
    vendor_name = normalise_name(vendor.name) or normalise_name(vendor.legal_name)
    vendor_pin = pin_from_address(vendor.address)

    def add(rule: str, other: Vendor, confidence: str, detail: str) -> None:
        matches.append(
            {
                "rule": rule, "vendorId": other.id, "vendorName": other.name,
                "confidence": confidence, "detail": detail,
            }
        )

    for other in others:
        if vendor.gst and other.gst and vendor.gst.upper() == other.gst.upper():
            add("exact GSTIN", other, "conclusive", f"Both carry GSTIN {vendor.gst}")
            continue
        if vendor.cin and other.cin and vendor.cin.upper() == other.cin.upper():
            add("exact CIN", other, "conclusive", f"Both carry CIN {vendor.cin}")
            continue

        other_pan = (other.pan or "").upper() or pan_from_gstin(other.gst)
        if vendor_pan and other_pan and vendor_pan == other_pan:
            add("exact PAN", other, "conclusive",
                f"Both resolve to PAN {vendor_pan} (a GSTIN embeds its PAN)")
            continue

        other_name = normalise_name(other.name) or normalise_name(other.legal_name)
        if vendor_name and other_name and vendor_name == other_name:
            other_pin = pin_from_address(other.address)
            if vendor_pin and other_pin and vendor_pin == other_pin:
                add("normalised name + PIN", other, "strong",
                    f"Same trading name and PIN code {vendor_pin}")
            else:
                add("normalised name", other, "possible",
                    "Same trading name once legal suffixes are removed; "
                    "addresses differ, so this may be a branch or a coincidence")
            continue

        if vendor.domain and other.domain and vendor.domain.lower() == other.domain.lower():
            add("shared domain", other, "strong", f"Both use {vendor.domain}")

    for rule in ("exact GSTIN", "exact CIN", "exact PAN", "normalised name + PIN",
                 "normalised name", "shared domain"):
        rules.append({"rule": rule, "hit": any(m["rule"] == rule for m in matches)})

    return MatchResult(bool(matches), len(others), matches, rules)


# ---------------------------------------------------------------------
# Related party
# ---------------------------------------------------------------------


def check_related_party(session: Session, vendor: Vendor) -> MatchResult:
    """Shared directors or addresses with an existing vendor.

    Reads directors out of the stored ``dirs`` payload rather than calling
    MCA again — the data is already on file and paid for.

    A genuine group relationship is a DISCLOSURE, not a disqualification.
    The wording of every match says so.
    """
    our_dins = _dins_for(session, vendor.id)
    our_pin = pin_from_address(vendor.address)

    others = session.scalars(select(Vendor).where(Vendor.id != vendor.id)).all()
    matches: list[dict] = []

    for other in others:
        shared = our_dins & _dins_for(session, other.id)
        for din in sorted(shared):
            matches.append(
                {
                    "type": "shared_director", "din": din,
                    "vendorId": other.id, "vendorName": other.name,
                    "confidence": "exact DIN match",
                    "detail": (
                        f"DIN {din} sits on the board of both. Where this is a "
                        f"genuine group relationship it should be recorded as a "
                        f"disclosure rather than treated as disqualifying."
                    ),
                }
            )
        if our_pin and not shared:
            other_pin = pin_from_address(other.address)
            if other_pin and other_pin == our_pin:
                matches.append(
                    {
                        "type": "shared_address", "vendorId": other.id,
                        "vendorName": other.name, "confidence": "same PIN code",
                        "detail": (
                            f"Both registered in PIN {our_pin}. A shared PIN in a "
                            f"dense commercial area is weak on its own."
                        ),
                    }
                )

    return MatchResult(
        bool(matches), len(others), matches,
        [
            {"rule": "shared director DIN", "hit": any(m["type"] == "shared_director" for m in matches)},
            {"rule": "shared registered PIN", "hit": any(m["type"] == "shared_address" for m in matches)},
        ],
    )


# ---------------------------------------------------------------------
# Director conflict of interest — feeds SCAN A3
# ---------------------------------------------------------------------


def check_conflict(
    session: Session, vendor: Vendor, employee_register: list[dict] | None = None
) -> MatchResult:
    """Overlap between vendor directors and our own employee records.

    ``employee_register`` is a list of ``{name, pan, din}``. Until an HR
    system is connected it arrives empty, and THAT IS REPORTED HONESTLY:
    a check run against an empty register has examined nothing, and must
    not return "no conflict found" as though it had.
    """
    register = employee_register or []
    directors = _directors_for(session, vendor.id)

    if not register:
        return MatchResult(
            matched=False,
            compared_against=0,
            matches=[],
            rules=[
                {
                    "rule": "director DIN / PAN vs employee register",
                    "hit": False,
                    "note": (
                        "No employee register is connected, so nothing was "
                        "compared. This is a coverage gap, not a clean result."
                    ),
                }
            ],
        )

    matches: list[dict] = []
    by_pan = {str(e.get("pan", "")).upper(): e for e in register if e.get("pan")}
    by_din = {str(e.get("din", "")): e for e in register if e.get("din")}
    by_name = {normalise_name(e.get("name")): e for e in register if e.get("name")}

    for director in directors:
        din = str(director.get("din") or "")
        pan = str(director.get("pan") or "").upper()
        name = normalise_name(director.get("name"))

        if din and din in by_din:
            matches.append({"rule": "DIN match", "din": din,
                            "employee": by_din[din].get("name"), "confidence": "conclusive"})
        elif pan and pan in by_pan:
            matches.append({"rule": "PAN match", "din": din,
                            "employee": by_pan[pan].get("name"), "confidence": "conclusive"})
        elif name and name in by_name:
            matches.append({"rule": "name match", "din": din,
                            "employee": by_name[name].get("name"), "confidence": "possible",
                            "detail": "Name match only — verify before acting."})

    return MatchResult(
        bool(matches), len(register), matches,
        [
            {"rule": "director DIN vs employee register", "hit": any(m["rule"] == "DIN match" for m in matches)},
            {"rule": "director PAN vs employee register", "hit": any(m["rule"] == "PAN match" for m in matches)},
            {"rule": "director name vs employee register", "hit": any(m["rule"] == "name match" for m in matches)},
        ],
    )


# ---------------------------------------------------------------------


def _directors_for(session: Session, vendor_id: str) -> list[dict]:
    """Directors from the stored ``dirs`` payload — no extra MCA call."""
    row = session.scalar(
        select(VendorCheck).where(
            VendorCheck.vendor_id == vendor_id, VendorCheck.check_id == "dirs"
        )
    )
    if not row or not isinstance(row.raw_response, dict):
        return []
    directors = row.raw_response.get("directors")
    return directors if isinstance(directors, list) else []


def _dins_for(session: Session, vendor_id: str) -> set[str]:
    return {
        str(d.get("din")) for d in _directors_for(session, vendor_id) if d.get("din")
    }
