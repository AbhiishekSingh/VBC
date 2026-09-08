"""Core value types for the VBC domain.

No database, no HTTP, no framework imports. Everything in this package is
pure Python so the scoring maths can be tested in isolation and audited
without standing up infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Rating(str, Enum):
    """Green / Yellow / Red. A parameter with no value is not rated at all."""

    G = "G"
    Y = "Y"
    R = "R"


class Pillar(str, Enum):
    S = "S"  # Stature     — capability
    C = "C"  # Compliance  — statutory
    A = "A"  # Assessment  — diligence
    N = "N"  # Numbers     — financial


#: Pillar weights. These mirror the client's Excel workbook and MUST NOT change.
#: Altering a weight makes every historical score incomparable.
PILLAR_WEIGHTS: dict[Pillar, float] = {
    Pillar.S: 0.2,
    Pillar.C: 0.1,
    Pillar.A: 0.6,
    Pillar.N: 0.1,
}

PILLAR_NAMES: dict[Pillar, tuple[str, str]] = {
    Pillar.S: ("Stature", "Capability"),
    Pillar.C: ("Compliance", "Statutory"),
    Pillar.A: ("Assessment", "Diligence"),
    Pillar.N: ("Numbers", "Financial"),
}


class SourceMode(str, Enum):
    """Where a SCAN parameter's value comes from."""

    AUTO = "AUTO"    # filled by a live, configured check
    HUMAN = "HUMAN"  # analyst judgement or field work
    HOOK = "HOOK"    # would be automated by a check that is not configured yet


class CheckState(str, Enum):
    ACTIVE = "active"
    NOT_CONFIGURED = "not_configured"  # defined in the catalog, no provider wired up


class CheckStatus(str, Enum):
    """Outcome of running one check against one vendor.

    The distinction between the four non-result states is the whole point:
    in an audit product, silence must never look like a clean result.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"                                # not applicable to this vendor
    UNAVAILABLE = "unavailable"                  # provider errored after retries
    NOT_CONFIGURED = "not_configured"            # no provider exists
    SKIPPED_MISSING_INPUT = "skipped_missing_input"  # required input left blank

    @property
    def is_adverse(self) -> bool:
        return self in (CheckStatus.FAIL, CheckStatus.WARN)

    @property
    def was_examined(self) -> bool:
        """True only when the check actually produced evidence."""
        return self in (CheckStatus.PASS, CheckStatus.WARN, CheckStatus.FAIL)


class RuleState(str, Enum):
    """Why a risk rule did or did not participate in the ledger."""

    AVAILABLE = "available"
    NOT_SELECTED = "not_selected"        # check exists, analyst did not tick it
    NOT_CONFIGURED = "not_configured"    # no provider wired up


class Provider(str, Enum):
    FILESURE = "filesure"
    WHOISXML = "whoisxml"
    FINAGG = "finagg"
    ECOURTS = "ecourts"
    ARCHIVE = "archive"
    IN_HOUSE = "in_house"
    NONE = "none"


class FieldType(str, Enum):
    YES_NO = "Yes / No"
    CHOICE = "Choice"
    TEXT = "Text"
    NUMBER = "Number"
    DATE = "Date"


@dataclass(frozen=True)
class ScanParameter:
    """One of the 18 SCAN parameters.

    ``options`` is ordered; each entry maps a display value to its rating.
    A value not present in ``options`` rates as nothing and the parameter
    falls out of the calculation — the same as if it were never set.
    """

    id: str
    pillar: Pillar
    label: str
    source: SourceMode
    options: tuple[tuple[str, Rating], ...]
    feed: str = ""
    fed_by: str | None = None  # check id that fills this parameter

    @property
    def weight(self) -> float:
        return PILLAR_WEIGHTS[self.pillar]

    def rate(self, value: str | None) -> Rating | None:
        """Rating for a value, or None when the parameter is not applicable."""
        if value is None:
            return None
        for option, rating in self.options:
            if option == value:
                return rating
        return None

    @property
    def option_values(self) -> tuple[str, ...]:
        return tuple(o for o, _ in self.options)


@dataclass(frozen=True)
class SurveillanceParameter:
    """One of the 13 site-surveillance field parameters."""

    id: str
    label: str
    options: tuple[tuple[str, Rating], ...]
    hard_gate: bool = False

    def rate(self, value: str | None) -> Rating | None:
        if value is None:
            return None
        for option, rating in self.options:
            if option == value:
                return rating
        return None


@dataclass(frozen=True)
class CheckParam:
    """An input one check needs before it can be called."""

    key: str
    label: str
    required: bool = False
    from_vendor: str | None = None   # prefill from this vendor field
    from_result: str | None = None   # supplied by another check's result
    type: str = "text"
    options: tuple[str, ...] = ()
    default: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class CheckDefinition:
    """One of the 32 checks in the catalog."""

    id: str
    group: str
    name: str
    endpoint: str
    provider: Provider
    note: str = ""
    state: CheckState = CheckState.ACTIVE
    requires: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    params: tuple[CheckParam, ...] = ()
    cost_paisa: int = 0
    credits: int = 0
    screenshots: int = 0
    needs_company_unlock: bool = False
    needs_director_unlock: bool = False
    always: bool = False   # runs automatically, free
    admin: bool = False    # account housekeeping, not vendor evidence

    @property
    def is_configured(self) -> bool:
        return self.state is CheckState.ACTIVE


@dataclass(frozen=True)
class RiskRule:
    """One line of the 0-100 point ledger."""

    id: str
    points: int
    label: str
    needs: tuple[str, ...]


@dataclass(frozen=True)
class RiskBand:
    key: str
    label: str
    note: str
    min: int
    max: int


@dataclass(frozen=True)
class ManualFieldTemplate:
    """A field-library entry the organisation defines once."""

    id: str
    label: str
    type: FieldType
    category: str
    options: tuple[str, ...] = ()
    maps_to: str | None = None            # SCAN parameter id
    map_when: dict[str, str] = field(default_factory=dict)  # value -> option
    hint: str = ""


@dataclass
class CheckResult:
    """The stored outcome of one check for one vendor."""

    check_id: str
    status: CheckStatus
    value: str = ""
    detail: str = ""
    raw_response: dict | list | str | None = None
    cost_paisa: int = 0


@dataclass
class ManualEntry:
    """An analyst-stated fact. Never rendered as verified evidence."""

    key: str
    value: str
    type: FieldType
    entered_by: str
    entered_at: str
    template_id: str | None = None
    note: str = ""
