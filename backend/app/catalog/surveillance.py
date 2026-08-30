"""Site surveillance: 13 field parameters recorded by a person on the premises.

Pass needs >=60% positives on the same 2Y=1G arithmetic as SCAN, with one
override: V1 Existence of Premises is a HARD GATE. If nobody could confirm
the premises exist, the field result is Negative no matter what the other
twelve say.

The result writes SCAN parameter A2, which sits in the 0.6 Assessment pillar
and is the single heaviest-weighted parameter in the framework.
"""

from __future__ import annotations

from app.domain.types import Rating, SurveillanceParameter

G, Y, R = Rating.G, Rating.Y, Rating.R

SURVEILLANCE_PARAMETERS: tuple[SurveillanceParameter, ...] = (
    SurveillanceParameter(
        id="V1",
        label="Existence of Premises",
        hard_gate=True,
        options=(("Yes", G), ("No", R)),
    ),
    SurveillanceParameter(
        id="V2", label="Traceability", options=(("High", G), ("Low", R))
    ),
    SurveillanceParameter(
        id="V3",
        label="Genuinity — deals in the same materials",
        options=(("Yes", G), ("No", R)),
    ),
    SurveillanceParameter(id="V4", label="Capability", options=(("Yes", G), ("No", R))),
    SurveillanceParameter(
        id="V5",
        label="Market Position",
        options=(("Strong", G), ("Average", Y), ("Weak", R)),
    ),
    SurveillanceParameter(
        id="V6",
        label="Sample vs Quality Standards",
        options=(("Above Par", G), ("At Par", Y), ("Below Par", R)),
    ),
    SurveillanceParameter(
        id="V7",
        label="Rate of the Product",
        options=(("Positive", G), ("At Par", Y), ("Negative", R)),
    ),
    SurveillanceParameter(
        id="V8",
        label="Infrastructure",
        options=(("Satisfactory", G), ("Dis-satisfactory", R)),
    ),
    SurveillanceParameter(
        id="V9",
        label="Political Connection",
        options=(("Yes", G), ("NA", Y), ("No", R)),
    ),
    SurveillanceParameter(
        id="V10",
        label="Staff Strength",
        options=(("Strong", G), ("Average", Y), ("Weak", R)),
    ),
    SurveillanceParameter(
        id="V11",
        label="Certifications (ISO, FSSAI etc.)",
        options=(("Yes", G), ("NA", Y), ("No", R)),
    ),
    SurveillanceParameter(
        id="V12", label="Clientele (Competitor)", options=(("Yes", G), ("No", R))
    ),
    SurveillanceParameter(
        id="V13",
        label="Reach (Branches)",
        options=(("Pan India", G), ("State", Y), ("Local", R)),
    ),
)

SURVEILLANCE_BY_ID: dict[str, SurveillanceParameter] = {
    p.id: p for p in SURVEILLANCE_PARAMETERS
}

#: Percentage of positives required for a Positive field result.
SURVEILLANCE_THRESHOLD_PCT: float = 60.0

assert len(SURVEILLANCE_PARAMETERS) == 13
assert sum(1 for p in SURVEILLANCE_PARAMETERS if p.hard_gate) == 1
