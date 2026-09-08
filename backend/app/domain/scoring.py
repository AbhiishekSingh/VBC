"""The scoring engines. This module is the audit core of the platform.

Three independent calculations live here:

  * ``score_scan``          the weighted SCAN framework, mirroring the workbook
  * ``score_surveillance``  13 field parameters with a hard gate on premises
  * ``score_risk``          the 0-100 point ledger

None of them touch the database, the network, or a framework. They take
plain values and return plain results, so every number in this system can
be reproduced and defended from its inputs alone.

A NOTE ON CHANGING ANY OF THIS
------------------------------
These rules decide whether a real business gets onboarded, and scores are
compared across vendors and over time. Changing a weight, a threshold or
the treatment of N/A parameters silently re-scores history and makes past
decisions incomparable to present ones. Any change here is a versioned
migration with a re-scoring plan, never an edit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.catalog.checks import check
from app.catalog.risk import (
    RISK_BASELINE,
    RISK_MAX,
    RISK_MIN,
    RISK_RULES,
    RULE_TESTS,
    band_for,
)
from app.catalog.scan import SCAN_PARAMETERS
from app.catalog.surveillance import (
    SURVEILLANCE_PARAMETERS,
    SURVEILLANCE_THRESHOLD_PCT,
)
from app.domain.types import (
    CheckResult,
    Pillar,
    PILLAR_NAMES,
    PILLAR_WEIGHTS,
    Rating,
    RiskBand,
    RuleState,
)

#: Onboarding threshold: weighted must reach 60% of best achievable.
#: A 50% figure is also reported, as the workbook displays both.
TOLERANCE_PASS = 0.60
TOLERANCE_WATCH = 0.50

_PRECISION = 4


def _round(value: float) -> float:
    return round(value + 0.0, _PRECISION)


# =====================================================================
# SCAN
# =====================================================================


@dataclass
class PillarScore:
    key: Pillar
    name: str
    subtitle: str
    weight: float
    applicable: int = 0
    G: int = 0
    Y: int = 0
    R: int = 0

    @property
    def positives(self) -> int:
        """Two Yellows make one Green. An odd Yellow is simply not counted."""
        return self.G + self.Y // 2

    @property
    def weighted(self) -> float:
        return _round(self.positives * self.weight)

    @property
    def max(self) -> float:
        return _round(self.applicable * self.weight)


@dataclass
class ScanScore:
    pillars: dict[Pillar, PillarScore]
    weighted: float
    best: float
    tolerance_60: float
    tolerance_50: float
    applicable: int
    total: int
    pct: float
    passed: bool
    verdict: str
    assessment_evaluated: bool
    coverage_note: str

    @property
    def is_scored(self) -> bool:
        return self.best > 0


def score_scan(ratings: dict[str, str | None]) -> ScanScore:
    """Weighted SCAN calculation.

    ``ratings`` maps a SCAN parameter id to the analyst-visible option value,
    or ``None`` when the parameter is Not Applicable for this vendor.

    The arithmetic, exactly as the workbook does it:

        positives  = G + floor(Y / 2)          per pillar
        weighted   = sum(positives  * weight)
        best       = sum(applicable * weight)
        onboard    when weighted >= 0.60 * best

    N/A parameters leave BOTH sides of the fraction. That is the workbook's
    behaviour and it is deliberate — a vendor is not penalised for a check
    that could not apply to them. It also means a thin audit is measured
    against a small bar, which is why ``coverage_note`` and
    ``assessment_evaluated`` travel with every result: a 60% built on six
    parameters must never be presentable as a 60% built on eighteen.
    """
    pillars: dict[Pillar, PillarScore] = {}
    for pillar, weight in PILLAR_WEIGHTS.items():
        name, subtitle = PILLAR_NAMES[pillar]
        pillars[pillar] = PillarScore(
            key=pillar, name=name, subtitle=subtitle, weight=weight
        )

    for parameter in SCAN_PARAMETERS:
        rating = parameter.rate(ratings.get(parameter.id))
        if rating is None:
            continue  # not applicable — drops out of both sides
        bucket = pillars[parameter.pillar]
        bucket.applicable += 1
        setattr(bucket, rating.value, getattr(bucket, rating.value) + 1)

    weighted = _round(sum(p.weighted for p in pillars.values()))
    best = _round(sum(p.max for p in pillars.values()))
    applicable = sum(p.applicable for p in pillars.values())

    tol_60 = _round(best * TOLERANCE_PASS)
    tol_50 = _round(best * TOLERANCE_WATCH)
    pct = round((weighted / best) * 100, 1) if best > 0 else 0.0
    passed = best > 0 and weighted >= tol_60

    assessment_evaluated = pillars[Pillar.A].applicable > 0

    if best == 0:
        verdict = "Not Scored"
    elif passed:
        verdict = "Positive for Onboarding"
    else:
        verdict = "Negative for Onboarding"

    total = len(SCAN_PARAMETERS)
    coverage_note = (
        f"{pct:.1f}% achieved, based on {applicable} of {total} parameters"
    )

    return ScanScore(
        pillars=pillars,
        weighted=weighted,
        best=best,
        tolerance_60=tol_60,
        tolerance_50=tol_50,
        applicable=applicable,
        total=total,
        pct=pct,
        passed=passed,
        verdict=verdict,
        assessment_evaluated=assessment_evaluated,
        coverage_note=coverage_note,
    )


# =====================================================================
# Site surveillance
# =====================================================================


@dataclass
class SurveillanceScore:
    done: bool
    applicable: int = 0
    G: int = 0
    Y: int = 0
    R: int = 0
    positives: int = 0
    pct: float = 0.0
    gate_failed: bool = False
    passed: bool = False
    verdict: str = "Not conducted"

    @property
    def scan_value(self) -> str | None:
        """The value this result writes into SCAN parameter A2."""
        if not self.done:
            return None
        return "Positive" if self.passed else "Negative"


def score_surveillance(
    values: dict[str, str | None], *, done: bool = True
) -> SurveillanceScore:
    """13 field parameters, >=60% positives, hard gate on premises.

    The hard gate is the point of the whole module. If V1 Existence of
    Premises comes back Negative, the field result is Negative regardless
    of how well the other twelve scored — you cannot have a satisfactory
    site visit to a site that does not exist.
    """
    if not done:
        return SurveillanceScore(done=False)

    applicable = G = Y = R = 0
    gate_failed = False

    for parameter in SURVEILLANCE_PARAMETERS:
        rating = parameter.rate(values.get(parameter.id))
        if rating is None:
            continue
        applicable += 1
        if rating is Rating.G:
            G += 1
        elif rating is Rating.Y:
            Y += 1
        else:
            R += 1
            if parameter.hard_gate:
                gate_failed = True

    positives = G + Y // 2
    pct = round((positives / applicable) * 100, 1) if applicable else 0.0
    passed = not gate_failed and pct >= SURVEILLANCE_THRESHOLD_PCT

    return SurveillanceScore(
        done=True,
        applicable=applicable,
        G=G,
        Y=Y,
        R=R,
        positives=positives,
        pct=pct,
        gate_failed=gate_failed,
        passed=passed,
        verdict="Positive" if passed else "Negative",
    )


# =====================================================================
# 0-100 risk ledger
# =====================================================================


@dataclass
class LedgerLine:
    id: str
    label: str
    points: int
    needs: tuple[str, ...]
    state: RuleState
    applied: bool

    @property
    def contribution(self) -> int:
        return self.points if self.applied else 0

    @property
    def explanation(self) -> str:
        if self.state is RuleState.NOT_CONFIGURED:
            return "source not configured"
        if self.state is RuleState.NOT_SELECTED:
            return "check not selected for this vendor"
        return "applied" if self.applied else "condition not met"


@dataclass
class RiskScore:
    score: int
    raw: int
    baseline: int
    ledger: list[LedgerLine]
    band: RiskBand
    gained: int
    lost: int
    dead: int

    @property
    def participating(self) -> int:
        return len(self.ledger) - self.dead


def score_risk(
    checks: dict[str, CheckResult], selected: list[str] | None = None
) -> RiskScore:
    """The point ledger, with unavailable rules kept visible.

    A rule reports one of three states:

      * ``not_configured``  no provider is wired up for any check it reads
      * ``not_selected``    the checks exist but the analyst did not tick them
      * ``available``       it participated, whether or not it fired

    Only ``available`` rules move the score. The other two are reported with
    their reason so a reader can see the ledger is incomplete, rather than
    inferring from a silent zero that the vendor is clean.
    """
    selection = set(selected or [])
    ledger: list[LedgerLine] = []

    for rule in RISK_RULES:
        unconfigured = [n for n in rule.needs if not check(n).is_configured]
        unselected = [
            n for n in rule.needs if check(n).is_configured and n not in selection
        ]
        # A rule participates only when at least one of its sources both
        # EXISTS and was actually run for this vendor.
        #
        # Counting the two exclusions separately was not enough. A rule
        # reading two checks where one has no provider and the other was
        # deselected matched neither "all unconfigured" nor "all
        # unselected", so it reported AVAILABLE and contributed zero —
        # which reads as "we looked and found nothing" when nothing was
        # looked at. r13 (news + court) hit exactly that the moment court
        # gained a provider.
        ran = [
            n for n in rule.needs if check(n).is_configured and n in selection
        ]

        applied = False
        if len(unconfigured) == len(rule.needs):
            state = RuleState.NOT_CONFIGURED
        elif not ran:
            # Something exists but none of it ran.
            state = RuleState.NOT_SELECTED
        else:
            state = RuleState.AVAILABLE
            try:
                applied = bool(RULE_TESTS[rule.id](checks))
            except Exception:
                # A malformed payload must never crash scoring. The rule
                # simply does not fire and the finding stays visible.
                applied = False

        ledger.append(
            LedgerLine(
                id=rule.id,
                label=rule.label,
                points=rule.points,
                needs=rule.needs,
                state=state,
                applied=applied,
            )
        )

    raw = sum(line.contribution for line in ledger)
    score = max(RISK_MIN, min(RISK_MAX, RISK_BASELINE + raw))

    return RiskScore(
        score=score,
        raw=raw,
        baseline=RISK_BASELINE,
        ledger=ledger,
        band=band_for(score),
        gained=sum(l.points for l in ledger if l.applied and l.points > 0),
        lost=sum(l.points for l in ledger if l.applied and l.points < 0),
        dead=sum(1 for l in ledger if l.state is not RuleState.AVAILABLE),
    )
