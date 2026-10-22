"""Input formats, defined ONCE for the form and the API.

WHY THIS IS A DOMAIN MODULE AND NOT A REACT FORM
------------------------------------------------
Every one of these fields is an argument to a paid call. A typo in a GSTIN
is ₹5 spent to be told the GSTIN was wrong, and the analyst learns it a
minute later, after the run.

So the rules have to run in the browser, where they can stop the call
before it is made. But if they ONLY run in the browser, the API still
accepts anything from any other caller, and the two definitions drift
until they disagree about which identifiers are valid. That disagreement
is invisible until an LLP cannot be audited.

One definition, here. The form gets it through codegen, the same way it
already gets the catalog.

BLOCK VERSUS WARN
-----------------
BLOCK stops the run and sends the analyst back to the field. Reserved for
the four identifiers whose format is unambiguous, documented, and
self-checking: get one wrong and the call is certain to fail.

WARN says what looks wrong and lets the analyst proceed. Everything else
is here, because our pattern being unhappy is not proof the input is
wrong. Court codes and CNRs vary by state and our knowledge of them is
incomplete; refusing to run on a shape we have not seen before would make
this module a source of outages rather than a guard against waste.

That asymmetry is deliberate. A false BLOCK costs an audit. A false WARN
costs a sentence the analyst ignores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


BLOCK = "block"
WARN = "warn"


@dataclass(frozen=True)
class Rule:
    """One field's format.

    ``pattern`` is deliberately a plain regular expression string rather
    than a compiled object: it is handed to JavaScript by codegen, and the
    two engines agree on this subset.
    """

    pattern: str
    level: str
    hint: str
    #: Shown under the field before anything is typed.
    example: str = ""
    #: Upper-case and strip before testing. True for every identifier —
    #: MCA, the GST portal and the income-tax portal all print them in
    #: capitals, and analysts paste them in whatever case they found them.
    normalise: bool = True


# --- the identifiers ---------------------------------------------------
#
# CIN   U93090MH2011PTC215361   21 chars: listing letter, 5-digit NIC,
#                               2-letter state, 4-digit year, 3-letter
#                               ownership class, 6-digit registration no.
# LLPIN AAA-1234                3 letters, hyphen, 4 digits.
# FCIN  F01234                  F or FLLPIN followed by digits.
#
# All three go in ONE rule, because they share one field. Validating that
# field as "CIN only" is precisely the bug that stopped LLPs being
# auditable — the provider accepts all three on the same endpoint.

CIN_PATTERN = r"^[LUu]\d{5}[A-Za-z]{2}\d{4}[A-Za-z]{3}\d{6}$"
LLPIN_PATTERN = r"^[A-Za-z]{3}-?\d{4}$"
FCIN_PATTERN = r"^(F|FLLPIN)\d{4,6}$"

MCA_IDENTIFIER = rf"(?:{CIN_PATTERN[1:-1]}|{LLPIN_PATTERN[1:-1]}|{FCIN_PATTERN[1:-1]})"

RULES: dict[str, Rule] = {
    "cin": Rule(
        pattern=rf"^{MCA_IDENTIFIER}$",
        level=BLOCK,
        hint="A 21-character CIN, an LLPIN like AAA-1234, or an FCIN like F01234.",
        example="U93090MH2011PTC215361",
    ),
    "gstin": Rule(
        # Shape only. The checksum is a separate step — see gstin_checksum_ok.
        pattern=r"^\d{2}[A-Za-z]{5}\d{4}[A-Za-z]{1}[A-Za-z\d]{1}[Zz]{1}[A-Za-z\d]{1}$",
        level=BLOCK,
        hint="15 characters: 2-digit state code, 10-character PAN, entity "
             "digit, Z, then the check character.",
        example="22AAAAA0000A1Z5",
    ),
    "pan": Rule(
        pattern=r"^[A-Za-z]{5}\d{4}[A-Za-z]$",
        level=BLOCK,
        hint="10 characters, five letters then four digits then a letter.",
        example="AAAAA0000A",
    ),
    "din": Rule(
        pattern=r"^\d{8}$",
        level=BLOCK,
        hint="Exactly 8 digits.",
        example="09054126",
    ),

    # --- everything below warns only -----------------------------------
    "cnr": Rule(
        pattern=r"^[A-Za-z]{4}\d{2}[A-Za-z0-9]{6}\d{4}$",
        level=WARN,
        hint="A CNR is normally 16 characters, e.g. MHAU010012342024.",
        example="MHAU010012342024",
    ),
    "domainName": Rule(
        # No scheme, no path, no trailing dot. A pasted URL is the common
        # mistake and the one worth catching.
        pattern=r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$",
        level=WARN,
        hint="Just the domain — no https://, no path.",
        example="example.com",
        normalise=False,
    ),
    "fy": Rule(
        pattern=r"^\d{4}-\d{2}$",
        level=WARN,
        hint="Financial year as 2023-24.",
        example="2023-24",
        normalise=False,
    ),
}

#: Fields that are plain positive integers. Collected rather than written
#: out, because the list grows with the catalog and the rule never varies.
NUMERIC_FIELDS = ("limit", "offset", "page", "page_size", "rows")

for _key in NUMERIC_FIELDS:
    RULES[_key] = Rule(
        pattern=r"^\d+$",
        level=WARN,
        hint="A whole number.",
        normalise=False,
    )


# --- GSTIN checksum ----------------------------------------------------

_GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum_ok(value: str) -> bool:
    """Verify a GSTIN's 15th character.

    Worth doing because it catches the error a length check cannot: a
    single mistyped digit in an otherwise well-formed GSTIN. That is the
    most common way this field is wrong, and without the checksum it costs
    a call to discover.

    Each of the first 14 characters is weighted alternately 1 and 2, the
    products are reduced by base-36 digit sum, and the check character is
    whatever brings the total to a multiple of 36.

    Returns True when the shape is not a GSTIN at all — shape is the other
    rule's job, and reporting "bad checksum" for a 4-character string
    would send the analyst looking for the wrong mistake.
    """
    value = (value or "").strip().upper()
    if len(value) != 15:
        return True
    if any(ch not in _GSTIN_ALPHABET for ch in value):
        return True

    total = 0
    for index, char in enumerate(value[:14]):
        digit = _GSTIN_ALPHABET.index(char)
        product = digit * (2 if index % 2 else 1)
        total += product // 36 + product % 36
    expected = _GSTIN_ALPHABET[(36 - total % 36) % 36]
    return expected == value[14]


# --- MCA identifier type -----------------------------------------------

def detect_id_type(value: str | None) -> str:
    """Which MCA identifier this is: ``cin``, ``llpin`` or ``fcin``.

    Falls back to ``cin`` for an empty box or a shape we do not recognise,
    so the form always shows a real answer rather than "Auto-detect".

    This is what makes dropping the auto-detect option safe. Pinning the
    field to ``cin`` by hand is what broke LLPs before: the provider then
    applies CIN validation to an LLPIN and answers 400. Deriving it from
    what was actually typed gives the same tidy screen without that.
    """
    text = (value or "").strip().upper().replace(" ", "")
    if re.match(LLPIN_PATTERN, text, re.IGNORECASE):
        return "llpin"
    if re.match(FCIN_PATTERN, text, re.IGNORECASE):
        return "fcin"
    return "cin"


# --- the one entry point -----------------------------------------------

@dataclass(frozen=True)
class Problem:
    key: str
    level: str
    message: str


def check_value(key: str, value: str | None) -> Problem | None:
    """Validate one field. ``None`` means nothing to report.

    An EMPTY value is never a problem here. Whether a field is required is
    the catalog's business, and reporting "wrong format" for a box nobody
    filled in points the analyst at the wrong thing.
    """
    rule = RULES.get(key)
    if rule is None:
        return None
    raw = (value or "").strip()
    if not raw:
        return None

    candidate = raw.upper() if rule.normalise else raw
    if not re.match(rule.pattern, candidate):
        return Problem(key, rule.level, rule.hint)

    if key == "gstin" and not gstin_checksum_ok(candidate):
        return Problem(
            key, BLOCK,
            "The check character does not match the rest of the GSTIN — "
            "usually one mistyped digit. Compare it against the source "
            "document.",
        )
    return None


def check_all(values: dict[str, str | None]) -> list[Problem]:
    """Every problem across a set of inputs, blocking ones first.

    All of them, not the first — an analyst who has mistyped two fields
    should fix two fields in one pass, not discover the second after
    correcting the first.
    """
    found = [p for p in (check_value(k, v) for k, v in values.items()) if p]
    return sorted(found, key=lambda p: 0 if p.level == BLOCK else 1)


def blocking(values: dict[str, str | None]) -> list[Problem]:
    """Only the problems that must stop a run."""
    return [p for p in check_all(values) if p.level == BLOCK]
