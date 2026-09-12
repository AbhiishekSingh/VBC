"""The facts layer — the renderable tier between a result line and the payload.

A check has always had two tiers: a one-line ``value``/``detail`` string, and
``raw_response``, the exact provider bytes. Nothing sat between them, so a
screen could offer a sentence or twenty kilobytes of JSON and nothing else.

``facts`` is that middle tier. It is DERIVED and DISPOSABLE — every value in
it traces to a field in the payload, and it can be thrown away and rebuilt
from ``raw_response`` at any time. That is the point: when a parse defect is
found (four have been so far), the fix is re-running the parser over stored
payloads, not re-paying the provider.

Two rules this module exists to enforce:

1. **Facts never invent.** Nothing here reads a payload. The builders take
   values a parser already extracted and put them in a shape a screen can
   render. If a parser could not find a field, ``ParseGuard`` has already
   raised and the check is UNAVAILABLE — a fact blob must never paper over
   that.
2. **Formatting happens HERE, once.** ``₹7.69 Cr``, ``02 Feb 2015`` and
   ``Yes`` are produced in Python and travel as strings. The frontend
   applies alignment and tone and nothing else. Two implementations of
   Indian number formatting, one in each language, is exactly the drift
   ``parity.test.ts`` exists to catch for the catalog.

PII: nothing written into a fact blob may carry a PAN, an unmasked contact
detail, or a base64 blob. ``raw_response`` holds those under its own access
controls; ``facts`` is the tier a client-facing screen reads, so it is the
tier that must be safe to read.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Literal

#: Bumped whenever a parser's output changes meaning. Stored beside the
#: blob so a re-parse can be told apart from the original.
PARSER_VERSION = "1"

Shape = Literal["detail", "summary", "table", "document", "reference", "none"]

DETAIL: Shape = "detail"
SUMMARY: Shape = "summary"
TABLE: Shape = "table"
DOCUMENT: Shape = "document"
REFERENCE: Shape = "reference"
NONE: Shape = "none"

Tone = Literal["neutral", "good", "warn", "bad"]
Level = Literal["info", "warn", "bad"]
Format = Literal["text", "date", "money", "count", "url", "id", "bool"]

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# =====================================================================
# Formatters
# =====================================================================

def human_date(value: Any) -> str | None:
    """``2015-02-02`` → ``02 Feb 2015``. Anything unparseable passes through.

    Providers send five different date formats between them and the parsers
    normalise to ISO. This is the last step: ISO is unambiguous but nobody
    reads a report in it.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (date, datetime)):
        d = value.date() if isinstance(value, datetime) else value
        return f"{d.day:02d} {_MONTHS[d.month - 1]} {d.year}"
    text = str(value).strip()
    try:
        d = date.fromisoformat(text[:10])
    except ValueError:
        return text
    return f"{d.day:02d} {_MONTHS[d.month - 1]} {d.year}"


def crore(rupees: Any) -> str | None:
    """Rupees → ``₹7.69 Cr``. For MCA capital and charge amounts.

    NOT for ``cost_paisa`` — that is paisa and goes through ``paisa()``.
    Mixing the two is a factor-of-100 error in a money figure on a report,
    so they are deliberately two functions with unmistakable names.
    """
    if rupees in (None, ""):
        return None
    try:
        n = float(rupees)
    except (TypeError, ValueError):
        return str(rupees)
    if abs(n) >= 10_000_000:
        return f"₹{n / 10_000_000:,.2f} Cr"
    if abs(n) >= 100_000:
        return f"₹{n / 100_000:,.2f} L"
    return f"₹{n:,.0f}"


def paisa(value: Any) -> str | None:
    """Integer paisa → ``₹1,234.56``. Money is never a float in this system."""
    if value in (None, ""):
        return None
    try:
        return f"₹{int(value) / 100:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def yes_no(value: Any) -> str | None:
    """A real tri-state. ``None`` stays ``None`` — 'the provider said nothing'
    is a different fact from 'no', and collapsing them is how an unexamined
    field starts reading as a clean one."""
    if value is None:
        return None
    return "Yes" if value else "No"


def plural(n: int, singular: str, many: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (many or singular + 's')}"


# =====================================================================
# Builders
# =====================================================================

def field(
    label: str, value: Any, *,
    format: Format = "text", tone: Tone | None = None, note: str | None = None,
) -> dict:
    """One labelled value.

    ``value`` of ``None`` is preserved rather than dropped: the screen renders
    it as "not returned", which is information. A field that silently
    disappears when the provider omits it makes a partial response look
    complete.
    """
    out: dict[str, Any] = {
        "label": label,
        "value": None if value in (None, "") else str(value),
        "format": format,
    }
    if tone:
        out["tone"] = tone
    if note:
        out["note"] = note
    return out


def stat(label: str, value: Any, *, tone: Tone = "neutral") -> dict:
    """One headline number, for the tile row at the top of a result."""
    return {"label": label, "value": "—" if value in (None, "") else str(value), "tone": tone}


def column(key: str, label: str, *, align: str = "left", format: Format = "text") -> dict:
    return {"key": key, "label": label, "align": align, "format": format}


def table(
    columns: list[dict], rows: list[dict], *,
    total: int | None = None, empty_note: str | None = None,
) -> dict:
    """Repeating rows.

    ``total`` is the provider's count, which may exceed ``len(rows)`` — 3209
    filings arrive 50 at a time. The screen says "50 of 3209" rather than
    implying it is showing everything.

    ``empty_note`` says what an empty table means AT THIS CHECK. "No charges
    registered" and "the search returned nothing" are different findings and
    a shared "No rows" would erase the difference.
    """
    shown = len(rows)
    n = shown if total is None else int(total)
    return {
        "columns": columns,
        "rows": rows,
        "totalRows": n,
        "truncated": n > shown,
        **({"emptyNote": empty_note} if empty_note else {}),
    }


def document(
    title: str, kind: str, *,
    size_bytes: int | None = None, href: str | None = None, excerpt: str | None = None,
) -> dict:
    """A file or a long text.

    ``href`` is served from our storage. A base64 blob NEVER goes inline into
    a fact blob — an order PDF is ~50 KB of base64 each and would land in the
    browser as unreadable text inside an already-large response.
    """
    out: dict[str, Any] = {"title": title, "kind": kind}
    if size_bytes is not None:
        out["sizeBytes"] = int(size_bytes)
    if href:
        out["href"] = href
    if excerpt:
        out["excerpt"] = excerpt[:400]
    return out


def flag(level: Level, label: str, detail: str) -> dict:
    """Something true of the RESPONSE, not of the vendor.

    A mismatch, a staleness, an internal contradiction. Flags never change
    ``status`` — a parser does not get to decide that a vendor is adverse
    because a certificate expired. They surface the problem next to the
    result so a person decides, which is the whole difference between an
    audit tool and a scoreboard.
    """
    return {"level": level, "label": label, "detail": detail}


def build(
    shape: Shape, *,
    stats: Iterable[dict] | None = None,
    fields: Iterable[dict] | None = None,
    rows: dict | None = None,
    documents: Iterable[dict] | None = None,
    flags: Iterable[dict] | None = None,
    derived_from: str | None = None,
    note: str | None = None,
) -> dict:
    """Assemble the envelope. Empty sections are omitted, not sent as ``[]``.

    ``derived_from`` names another check when this one made no call of its
    own — the directors list is read out of the company master payload. The
    screen then says where the evidence is instead of showing a "no payload
    stored" placeholder, which would be true of this row and misleading
    about the finding.
    """
    out: dict[str, Any] = {"shape": shape, "parserVersion": PARSER_VERSION}
    if stats:
        out["stats"] = list(stats)
    if fields:
        out["fields"] = list(fields)
    if rows:
        out["table"] = rows
    if documents:
        out["documents"] = list(documents)
    if flags:
        out["flags"] = list(flags)
    if derived_from:
        out["derivedFrom"] = derived_from
    if note:
        out["note"] = note
    return out


def reference(summary: str, fields: Iterable[dict] | None = None) -> dict:
    """Operational metadata — a capability list, an enum catalog, a job receipt.

    Ten of the 47 checks are plumbing. They are real calls with real
    responses, but they say nothing about the vendor, and rendering them
    among the findings puts a list of sortable field names in front of a
    client with no explanation of why it is in their report. This shape
    tells the screen to file them under Operational instead.
    """
    return build(REFERENCE, fields=fields, note=summary)


def none(reason: str | None = None) -> dict:
    """No facts were parsed. The screen falls back to the status line alone."""
    return build(NONE, note=reason)
