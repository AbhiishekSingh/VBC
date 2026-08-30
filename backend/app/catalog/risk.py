"""The 0-100 risk score: a transparent point ledger, independent of SCAN.

Baseline is 50, not 0. With GST and sanctions unconfigured, the positive
rules available in Phase 1 total +70 against -45 of negatives, so a scale
starting at 0 could never reach its own upper bands and every vendor would
read as high-risk for reasons that have nothing to do with the vendor.

Rules whose source is missing report WHY they did not participate rather
than silently scoring zero. The ledger stays whole, so enabling GST later
brings dead rules to life without renumbering anything.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.domain.types import CheckResult, CheckStatus, RiskBand, RiskRule

RISK_BASELINE = 50
RISK_MIN, RISK_MAX = 0, 100


class HasChecks(Protocol):
    """Anything that can answer 'what happened with check X'."""

    checks: dict[str, CheckResult]


def _status(checks: dict[str, CheckResult], check_id: str) -> CheckStatus | None:
    result = checks.get(check_id)
    return result.status if result else None


def _passed(checks: dict[str, CheckResult], check_id: str) -> bool:
    return _status(checks, check_id) is CheckStatus.PASS


def _adverse(checks: dict[str, CheckResult], check_id: str) -> bool:
    status = _status(checks, check_id)
    return status is not None and status.is_adverse


def _domain_older_than_2y(checks: dict[str, CheckResult]) -> bool:
    """Domain age is carried in the whois result's display value.

    Parsing a rendered string is a compromise inherited from the prototype.
    Once the WhoisXML adapter lands, this reads ``createdDateNormalized``
    from the stored raw payload instead — see providers/whoisxml.py.
    """
    import re

    result = checks.get("whois")
    if not result or result.status is not CheckStatus.PASS:
        return False
    match = re.search(r"(\d+)\s*yrs?", str(result.value), re.IGNORECASE)
    return bool(match) and int(match.group(1)) >= 2


#: Rule id -> predicate. Kept separate from the RiskRule dataclass so the
#: rules themselves stay serialisable and seedable into the database.
RULE_TESTS: dict[str, Callable[[dict[str, CheckResult]], bool]] = {
    "r1": lambda c: _passed(c, "master"),
    "r2": lambda c: _passed(c, "filings"),
    "r3": lambda c: _passed(c, "fin"),
    "r4": _domain_older_than_2y,
    "r5": lambda c: _passed(c, "cdx"),
    "r6": lambda c: _passed(c, "ssl"),
    "r7": lambda c: _adverse(c, "charges"),
    "r8": lambda c: _adverse(c, "dup"),
    "r9": lambda c: _adverse(c, "rp"),
    # The four below have no configured source in Phase 1. They are kept in
    # the ledger deliberately, reported as not_configured, never as false.
    "r10": lambda c: False,
    "r11": lambda c: False,
    "r12": lambda c: False,
    "r13": lambda c: False,
}

RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule("r1", +20, "MCA registered and active", ("master",)),
    RiskRule("r2", +10, "Filings current", ("filings",)),
    RiskRule("r3", +15, "Filed financials show positive net worth", ("fin",)),
    RiskRule("r4", +10, "Domain older than 2 years", ("whois",)),
    RiskRule("r5", +10, "Continuous web presence, no outages", ("cdx",)),
    RiskRule("r6", +5, "Valid SSL from a trusted CA", ("ssl",)),
    RiskRule("r7", -15, "Open charge against the company", ("charges",)),
    RiskRule("r8", -20, "Duplicate vendor detected", ("dup",)),
    RiskRule("r9", -10, "Related party overlap", ("rp",)),
    RiskRule("r10", +40, "GST active", ("gst",)),
    RiskRule("r11", -25, "GST suspended", ("gst",)),
    RiskRule("r12", -50, "Sanctions / defaulter match", ("ofac", "rbi", "eusanc")),
    RiskRule("r13", -15, "Adverse news or court records", ("news", "court")),
)

RISK_BANDS: tuple[RiskBand, ...] = (
    RiskBand("approve", "APPROVE", "Low risk. Standard onboarding.", 80, 100),
    RiskBand("conditional", "CONDITIONAL",
             "Medium risk. Verify specific concerns with the vendor.", 60, 79),
    RiskBand("deep", "DEEP REVIEW",
             "Significant risks. Senior analyst review required.", 40, 59),
    RiskBand("reject", "REJECT", "High risk profile. Decline or escalate.", 0, 39),
)


def band_for(score: int) -> RiskBand:
    for band in RISK_BANDS:
        if band.min <= score <= band.max:
            return band
    return RISK_BANDS[-1]


assert len(RISK_RULES) == 13
assert set(RULE_TESTS) == {r.id for r in RISK_RULES}
