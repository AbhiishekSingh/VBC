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
    S = "S"  # Stature        — capability
    C = "C"  # Compliance     — statutory
    A = "A"  # Assessment     — the psychometric test
    N = "N"  # Non Negotiable — the must-pass checks


#: Pillar weights, as the client's workbook computes them (row 14 of every
#: Outcome sheet).
#:
#: THESE CHANGE THROUGH A VERSION BUMP, NEVER THROUGH AN EDIT. This comment
#: used to read "MUST NOT change", which is why nobody changed them when the
#: client moved to the split below — the workbook carried 0.2/0.1/0.6/0.1 on a
#: row of its own labelled "Old Score", feeding nothing, while every one of
#: eight real assessments scored against 0.2/0.1/0.4/0.3.
#:
#: Altering a weight does not make a historical score WRONG, it makes it a
#: different vintage. `vendor_scores` is append-only and carries
#: `catalog_version_id`, so a score computed under the old weights stays
#: reconstructable. Bump the catalog version, change the number, leave the old
#: rows alone.
#:
#: The direction of the change is itself the finding: the client halved the
#: weight on the psychometric test and tripled it on the must-pass commercial
#: checks. Verified 5 Oct 2026 against eight assessments spanning Apr-Aug 2026.
PILLAR_WEIGHTS: dict[Pillar, float] = {
    Pillar.S: 0.2,
    Pillar.C: 0.1,
    Pillar.A: 0.4,
    Pillar.N: 0.3,
}

PILLAR_NAMES: dict[Pillar, tuple[str, str]] = {
    Pillar.S: ("Stature", "Capability"),
    Pillar.C: ("Compliance", "Statutory"),
    Pillar.A: ("Assessment", "Psychometric Test"),
    Pillar.N: ("Non Negotiable", "Must-pass"),
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
    #: Spellings that mean the same thing as a canonical option.
    #:
    #: The workbook writes ">10 Years"; this codebase wrote "> 10 Years" and
    #: put rows in the database under it. Both must resolve, or a rating an
    #: analyst recorded last month silently stops being readable — and an
    #: unreadable rating does not show as missing, it drops the parameter out
    #: of BOTH sides of the fraction and quietly lowers the bar the vendor is
    #: measured against. Canonical spelling is the workbook's; ours survive as
    #: aliases.
    aliases: tuple[tuple[str, str], ...] = ()
    #: A-pillar only: this sub-score's share of the psychometric test.
    #: Integrity 0.5, Business Acumen 0.3, Risk Taking 0.1, Problem Solving
    #: 0.1. See `score_scan` for why the A pillar cannot simply be counted.
    sub_weight: float = 0.0

    @property
    def weight(self) -> float:
        return PILLAR_WEIGHTS[self.pillar]

    @staticmethod
    def _key(value: str) -> str:
        """Compare on letters and digits only.

        Whitespace and punctuation around an option carry no meaning and are
        exactly where the two spellings diverge. Matching on the squashed form
        makes ">10 Years" and "> 10 Years" the same answer without needing an
        alias for every possible spacing.
        """
        return "".join(ch for ch in value.lower() if ch.isalnum())

    def rate(self, value: str | None) -> Rating | None:
        """Rating for a value, or None when the parameter is not applicable."""
        if value is None:
            return None
        key = self._key(value)
        for option, rating in self.options:
            if self._key(option) == key:
                return rating
        for alias, canonical in self.aliases:
            if self._key(alias) == key:
                for option, rating in self.options:
                    if option == canonical:
                        return rating
        return None

    def canonical(self, value: str | None) -> str | None:
        """The option spelling to store, for a value that may be an alias."""
        if value is None:
            return None
        key = self._key(value)
        for option, _ in self.options:
            if self._key(option) == key:
                return option
        for alias, target in self.aliases:
            if self._key(alias) == key:
                return target
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
