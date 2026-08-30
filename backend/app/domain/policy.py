"""The coverage floor — OPEN DECISION §18.1, implemented as a policy object.

THE PROBLEM
-----------
SCAN excludes N/A parameters from both sides of the fraction, so a thin
audit is measured against a small bar. Azahan Advertising — an
unincorporated proprietorship with no premises and no web presence —
reaches exactly 60.0% on 6 of 18 parameters and is recommended "Positive
for Onboarding". A human overrode it to Rejected.

The score is not wrong. 0.90 of 1.50 really is 60%. What is wrong is that
the sentence "Positive for Onboarding" reads identically whether it rests
on six parameters or eighteen, and the heaviest pillar in the framework
(Assessment, 0.60) was never evaluated at all.

WHY THIS IS A POLICY OBJECT AND NOT AN `if`
-------------------------------------------
The client has not settled this yet, and it must be settled before the
first real vendor is scored: a rule that changes after vendors are on file
makes historical scores incomparable, which is the one thing an audit
product cannot afford. So the gate is configurable, every decision records
which policy version produced it, and switching policy is a deliberate act
with a re-scoring plan attached — not a code edit.

The default implements the handoff's own recommendation, (a) + (b):

  (a) no Positive verdict unless the Assessment pillar was evaluated
  (b) coverage stated next to every verdict, always

Option (c) — GST as a mandatory manual entry until the API exists — is
available as ``require_gst_evidence`` and is off by default, since it
changes what analysts must collect rather than how a score is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.scoring import ScanScore
from app.domain.types import Pillar


class Verdict(str, Enum):
    POSITIVE = "Positive for Onboarding"
    NEGATIVE = "Negative for Onboarding"
    NOT_SCORED = "Not Scored"
    #: Reached the threshold, but on too little evidence to stand behind.
    INSUFFICIENT_COVERAGE = "Insufficient Coverage — Senior Review"


@dataclass(frozen=True)
class CoveragePolicy:
    """Rules that gate a verdict, independent of the score itself.

    ``version`` is stored on every decision. Two vendors scored under
    different policy versions are not directly comparable, and the audit
    trail has to be able to say so.
    """

    version: str = "1.0"

    #: (a) The Assessment pillar carries 0.60 of 4.30. A "Positive" that
    #: never looked at it is a statement about paperwork, not about a vendor.
    #:
    #: This is a COUNT, not a boolean, and the distinction matters. Of the
    #: four Assessment parameters, only A3 (conflict of interest) is
    #: automated — it is computed in-house, costs nothing, and comes back
    #: "Positive" for essentially every vendor with no employee overlap.
    #: A floor of 1 would therefore be satisfied by the cheapest check in
    #: the catalog, which is exactly the loophole Azahan walks through.
    #: The substantive parameters are A1 (psychometric), A2 (site
    #: surveillance) and A4 (market references) — all human, all real work.
    #: A floor of 2 forces at least one of them.
    min_assessment_parameters: int = 2

    #: A floor on raw coverage. 6 of 18 is Azahan; 8 asks for a little more
    #: than a registry lookup and a domain check before a positive verdict.
    min_applicable_parameters: int = 8

    #: (c) Stopgap while the GST API is unconfigured. Off by default.
    require_gst_evidence: bool = False

    #: (b) Never presentational-only — the note travels with the verdict.
    always_state_coverage: bool = True


DEFAULT_POLICY = CoveragePolicy()

#: The prototype's behaviour: score alone decides, nothing is gated.
#: Kept so the fixtures can be reproduced exactly as the client signed them off.
PROTOTYPE_POLICY = CoveragePolicy(
    version="0.0-prototype",
    min_assessment_parameters=0,
    min_applicable_parameters=0,
    require_gst_evidence=False,
)


@dataclass
class GatedVerdict:
    """A verdict, the coverage behind it, and why it was or was not gated."""

    verdict: Verdict
    raw_verdict: Verdict
    scan: ScanScore
    policy_version: str
    gated: bool
    reasons: list[str]

    @property
    def headline(self) -> str:
        """The verdict as it must appear in the UI and the report.

        Coverage is not a tooltip. A reader who sees only this line should
        be unable to mistake a thin audit for a thorough one.
        """
        return f"{self.verdict.value} — {self.scan.coverage_note}"

    @property
    def is_positive(self) -> bool:
        return self.verdict is Verdict.POSITIVE


def apply_policy(
    scan: ScanScore,
    *,
    policy: CoveragePolicy = DEFAULT_POLICY,
    has_gst_evidence: bool = False,
) -> GatedVerdict:
    """Gate a SCAN result. Never changes the score — only what may be claimed.

    A gated verdict is not a rejection. It says the evidence gathered is too
    thin to support a positive recommendation, and routes the vendor to a
    senior analyst instead. The underlying score is unchanged and still shown.
    """
    raw = (
        Verdict.NOT_SCORED
        if not scan.is_scored
        else (Verdict.POSITIVE if scan.passed else Verdict.NEGATIVE)
    )

    reasons: list[str] = []

    # Only a would-be Positive can be gated. A Negative needs no floor —
    # thin evidence never manufactures a rejection.
    if raw is Verdict.POSITIVE:
        assessed = scan.pillars[Pillar.A].applicable
        if assessed < policy.min_assessment_parameters:
            reasons.append(
                f"Only {assessed} of 4 Assessment parameters were evaluated, "
                f"below the floor of {policy.min_assessment_parameters}. "
                f"Assessment carries weight 0.60 — the heaviest in the "
                f"framework — and site surveillance, market references and "
                f"the psychometric result are the substantive checks in it."
            )
        if scan.applicable < policy.min_applicable_parameters:
            reasons.append(
                f"Only {scan.applicable} of {scan.total} parameters were "
                f"applicable, below the floor of "
                f"{policy.min_applicable_parameters} required for a positive "
                f"recommendation."
            )
        if policy.require_gst_evidence and not has_gst_evidence:
            reasons.append(
                "No GST evidence on file. While the GST API is unconfigured "
                "this must be recorded manually before a positive verdict."
            )

    gated = bool(reasons)
    return GatedVerdict(
        verdict=Verdict.INSUFFICIENT_COVERAGE if gated else raw,
        raw_verdict=raw,
        scan=scan,
        policy_version=policy.version,
        gated=gated,
        reasons=reasons,
    )
