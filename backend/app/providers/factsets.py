"""Per-check fact builders.

One function per check. Each takes what the runner already has — the
provider payload and whatever the existing normaliser extracted — and returns
the fact envelope defined in ``app.domain.facts``.

These are PURE: no network, no session, no settings. That is what makes a
re-parse over stored payloads possible, and what lets every one of them be
tested against a captured response with no credits spent.

Nothing here decides a check's status. The runner already did that, from the
normalised values, before calling any of this. A fact builder that could
change an outcome would be a second scoring engine with no catalog version
behind it.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from app.domain import facts as F
# Pure helper. FileSure sends slashed dates as MM/DD/YYYY, and this is
# the one place that knows it.
from app.providers.base import parse_date

# Suffixes that carry no identity. "RELIANCE INDUSTRIES LIMITED" and
# "Reliance Industries Ltd" are the same company; a comparison that says
# otherwise produces a false mismatch flag on every second vendor.
_NOISE = re.compile(
    r"\b(PRIVATE|PVT|PUBLIC|LIMITED|LTD|LLP|COMPANY|CO|CORPORATION|CORP|"
    r"INCORPORATED|INC|AND|THE)\b"
)

#: Below this, two names are treated as different entities.
NAME_MATCH_FLOOR = 0.86

#: Between ``NAME_MATCH_FLOOR`` and this, a search term is close enough to
#: the vendor's name to be a typo rather than a variant. Exact-match
#: registries return nothing for a misspelling, and nothing is the most
#: dangerous possible answer here.
NAME_TYPO_CEILING = 0.995

#: A web presence not captured in this long is evidence about the archive,
#: not about the vendor's site being live.
STALE_CAPTURE_YEARS = 3


def _key(name: Any) -> str:
    """A name reduced to what identifies it."""
    text = _NOISE.sub(" ", str(name or "").upper())
    return re.sub(r"[^A-Z0-9]+", "", text)


def name_similarity(a: Any, b: Any) -> float:
    """0..1. Both blank returns 0 — 'nothing to compare' is not a match."""
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


def host_covers(cert_name: Any, domain: Any) -> bool:
    """Does a certificate name cover this domain?

    Deliberately NOT ``name_similarity``. That function strips corporate
    noise words, and several of them — CORP, CO, INC — are perfectly normal
    subdomain labels. Run over hostnames it reduces ``corp.ril.com`` to
    ``ril.com`` and reports a certificate for a different host as a match,
    which is exactly the case this flag exists to catch.
    """
    cert = str(cert_name or "").strip().lower().rstrip(".")
    host = str(domain or "").strip().lower().rstrip(".")
    if not cert or not host:
        return False
    if cert.startswith("*."):
        # A wildcard covers one label, not a whole subtree: *.ril.com
        # matches www.ril.com and ril.com, never a.b.ril.com.
        base = cert[2:]
        return host == base or (host.endswith("." + base)
                                and "." not in host[: -len(base) - 1])
    return cert == host


def entity_mismatch(returned: Any, expected: Any, *, source: str) -> list[dict]:
    """The flag that catches a provider answering about a different company.

    A GSTIN typed one digit wrong resolves cleanly and returns a real,
    active, perfectly healthy registration — belonging to somebody else. The
    call succeeded, the status is PASS, and the report is about the wrong
    entity. Nothing else in the pipeline looks for this.
    """
    if not returned or not expected:
        return []
    score = name_similarity(returned, expected)
    if score >= NAME_MATCH_FLOOR:
        return []
    return [F.flag(
        "bad",
        "Does not match the vendor on file",
        f"{source} returned “{returned}”, but this vendor is recorded as "
        f"“{expected}”. The identifier may belong to a different entity — "
        f"confirm it before any of this counts.",
    )]


def _yn(value: Any) -> str | None:
    """MCA's ``"Y"`` / ``"N"`` → ``Yes`` / ``No``.

    Separate from ``F.yes_no``, which takes a real boolean. MCA sends these
    as single-character STRINGS, and every non-empty string is truthy — so
    passing them through ``yes_no`` would render "N" as "Yes", which is the
    worst possible failure for a field like this. Anything unrecognised is
    passed through untouched rather than guessed at.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return F.yes_no(value)
    text = str(value).strip()
    return {"y": "Yes", "n": "No", "yes": "Yes", "no": "No",
            "true": "Yes", "false": "No"}.get(text.lower(), text)


#: A payload smaller than this said little, so extracting little from it is
#: not suspicious. Roughly the size of a terse "nothing found" response.
THIN_PAYLOAD_FLOOR_BYTES = 1_500

#: Below this share of populated fields, against a substantial payload, the
#: parser is probably reading keys that are no longer there.
THIN_FIELD_RATIO = 0.34

#: Fewer fields than this and the ratio is noise — two of five nulls is not
#: evidence of anything.
THIN_MIN_FIELDS = 5

#: A column empty on EVERY row is the sharpest signal there is that a field
#: name has moved, and it does not survive an average. Four rows of DINs
#: beside three dead columns and two live ones scores 0.40 — comfortably
#: above the ratio floor, and wrong. So whole-blank columns are counted on
#: their own, and it takes a strict majority of the table's columns: two of
#: four is an ordinary pair of optional fields (a charge with no
#: satisfaction date has two), three of five is a parser that has lost its
#: place.
THIN_BLANK_COLUMN_MIN = 2

#: …and never on a single row, where "blank in every row" means "blank
#: once", which is just a quiet record.
THIN_BLANK_COLUMN_MIN_ROWS = 2


def thin_result(payload: Any, facts: dict | None) -> dict | None:
    """Did the provider say a lot while the parser heard almost nothing?

    `ParseGuard` protects about fifteen fields across eight endpoints, each
    one declared by hand. The facts layer reads several times that many. So
    a provider renaming a field nobody thought to guard produces a check
    that still passes, a guard that never fires, and a row quietly reading
    "not returned" — the same silent failure the guards exist to stop, one
    level further out.

    This is the general form of that question, and it needs no list of
    field names to maintain. Two rules, because one was not enough:

    * **Yield** — a 40 KB response that fills two fields out of fourteen,
      or two table cells in six, is not a quiet company. Averaged, and so
      gated on payload size.
    * **Whole-blank columns** — half the table's columns silent on every
      single row. `dresolve` passed the yield rule comfortably (two live
      columns out of five averages 0.40, above the 0.34 floor) while the
      director's company names, the reason anyone opens that check, were
      missing entirely. An average lets one healthy column carry three
      dead ones, so this rule is counted separately and is not averaged.

    Deliberately conservative. It raises a flag for a person, never a
    status, and it stays silent on short field lists, on single rows, and
    — for the yield rule — on small payloads, because a flag that cries
    wolf gets switched off inside a week and is then protecting nothing.
    """
    if not facts or facts.get("shape") in (None, "none", "reference"):
        return None

    try:
        size = len(json.dumps(payload, default=str))
    except (TypeError, ValueError):
        return None

    def _empty(value: Any) -> bool:
        return value in (None, "", "—")

    # --- whole-blank columns -------------------------------------------
    #
    # Tested BEFORE the size floor, and deliberately. The floor exists
    # because extracting little from a terse response is not suspicious —
    # that is an argument about YIELD, and it does not apply here. Rows
    # present with half the columns dead says the payload held records
    # whatever its size, and the real `dresolve` reproduction is 934 bytes:
    # four candidates, three columns of dashes, and the floor would have
    # swallowed it for the second time.
    table = facts.get("table") or {}
    rows, columns = table.get("rows") or [], table.get("columns") or []
    blank_cols = [c for c in columns
                  if all(_empty(r.get(c["key"])) for r in rows)] if rows else []
    blank = [c["label"] for c in blank_cols]

    # --- the sharp version: a blank column the payload could have filled ---
    #
    # Two field-rename defects got past the majority rule below, because two
    # dead columns out of five is not a majority. Counting was the wrong
    # question. The right one is narrower and almost never wrong:
    #
    #   this column is empty on every row — does the payload contain a field
    #   with almost this name, carrying data we did not read?
    #
    # `causelist` rendered a Parties column of dashes while every record
    # carried `party`. That is unambiguous. Contrast a charge with no
    # satisfaction date: the payload HAS `satisfactionDate`, and it is null,
    # which is the source telling us the charge was never satisfied. One is
    # a parser reading the wrong name; the other is a fact. Only the first
    # fires here.
    if rows and columns:
        missed = _renamed_fields(payload, blank_cols)
        if missed:
            return F.flag(
                "warn", "A field was read under the wrong name",
                _join([f"“{label}” is empty on all {len(rows)} rows while the "
                       f"source sends “{key}”" for label, key in missed])
                + ". The data is in the stored response and the parser is "
                  "looking for it under a name the source does not use. "
                  "Treat those columns as unread, not as absent.",
            )

    if (len(columns) >= 3
            and len(rows) >= THIN_BLANK_COLUMN_MIN_ROWS
            and len(blank) >= THIN_BLANK_COLUMN_MIN
            and len(blank) * 2 > len(columns)):
        return F.flag(
            "warn", "Whole columns came back empty",
            f"{_join(blank)} are empty in all {len(rows)} rows. A column "
            f"blank on every single row is the shape of a field name that "
            f"has moved, not a fact the source does not hold — the rows "
            f"below are real, but treat those columns as unread, not as "
            f"absent, until someone has compared them against the stored "
            f"response.",
        )

    if size < THIN_PAYLOAD_FLOOR_BYTES:
        return None

    # --- fields ------------------------------------------------------
    fields = facts.get("fields") or []
    if len(fields) >= THIN_MIN_FIELDS:
        filled = sum(1 for f in fields if not _empty(f.get("value")))
        if filled / len(fields) < THIN_FIELD_RATIO:
            return F.flag(
                "warn", "Most fields came back empty",
                f"The source returned {size:,} bytes but only {filled} of "
                f"{len(fields)} fields could be read from it. That is the "
                f"shape of a renamed or moved field rather than a quiet "
                f"record — treat the blanks below as unverified, not as "
                f"absent, until someone has compared this against the stored "
                f"response.",
            )

    # --- table cells --------------------------------------------------
    #
    # Rows used to be taken as proof the parser knew its way around the
    # payload. They are not — see the blank-column rule above, which is the
    # sharper form of this same question. This one catches the diffuse
    # version: no single column entirely dead, but the table mostly holes.
    if len(columns) >= 3 and rows:
        cells = len(rows) * len(columns)
        filled = sum(1 for r in rows for c in columns if not _empty(r.get(c["key"])))

        if filled / cells < THIN_FIELD_RATIO:
            return F.flag(
                "warn", "Most table cells came back empty",
                f"The source returned {size:,} bytes and {len(rows)} rows, but "
                f"only {filled} of {cells} cells could be read"
                + (f" — {_join(blank)} " +
                   ("is" if len(blank) == 1 else "are") + " empty in every row"
                   if blank else "")
                + ". That is the shape of a renamed or moved field rather "
                  "than a quiet record.",
            )

    return None


def _join(labels: list[str]) -> str:
    """``a``, ``a and b``, ``a, b and c`` — this text is read by auditors."""
    if len(labels) <= 1:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


#: How much of two field names must agree before they are "the same field
#: under another name". Four characters: enough that `party`/`parties` and
#: `item`/`itemNumber` match, short enough to stay readable, long enough
#: that `date`/`dateModified` is the only kind of collision it invites —
#: and a collision here costs a flag a person reads, not a status.
_RENAME_PREFIX = 4

#: The walk over an unknown payload is bounded. A response is nested JSON of
#: unknown depth, and a guard that can spend real time on a 500 KB document
#: is a guard someone will switch off.
_RENAME_MAX_RECORDS = 60
_RENAME_MAX_DEPTH = 6


def _normalise_key(key: str) -> str:
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def _records(value: Any, depth: int = 0) -> list[dict]:
    """Every dict inside the payload that looks like a record."""
    if depth > _RENAME_MAX_DEPTH:
        return []
    found: list[dict] = []
    if isinstance(value, dict):
        found.append(value)
        for inner in value.values():
            found.extend(_records(inner, depth + 1))
    elif isinstance(value, list):
        for inner in value[:_RENAME_MAX_RECORDS]:
            found.extend(_records(inner, depth + 1))
    return found[:_RENAME_MAX_RECORDS]


def _renamed_fields(payload: Any, blank_columns: list[dict]) -> list[tuple[str, str]]:
    """Blank columns the payload could have filled, and the field it sends.

    Returns ``(column label, the key the source actually uses)``. Empty when
    nothing matches — which is the common case and must stay cheap.

    The value test is what keeps this honest. A key that exists and is null
    everywhere is the source saying "there is none of this", and that is a
    fact about the vendor, not a defect in us.
    """
    if not blank_columns:
        return []

    records = _records(payload)
    if not records:
        return []

    #: field name -> does any record carry a real value for it
    populated: dict[str, str] = {}
    for record in records:
        for key, value in record.items():
            if value in (None, "", [], {}):
                continue
            populated.setdefault(_normalise_key(key), str(key))

    out: list[tuple[str, str]] = []
    for column in blank_columns:
        want = _normalise_key(column.get("key", ""))
        if len(want) < _RENAME_PREFIX:
            continue
        for norm, original in populated.items():
            if norm == want:
                continue  # same name, so the parser is not the problem
            if (norm.startswith(want[:_RENAME_PREFIX])
                    or want.startswith(norm[:_RENAME_PREFIX])):
                out.append((column.get("label") or original, original))
                break
    return out


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _iso(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# =====================================================================
# MCA · FileSure
# =====================================================================

def master(parsed: dict, *, subject: str | None = None) -> dict:
    """Company master — the spine of the whole dossier."""
    status = str(parsed.get("status") or "")
    flags = entity_mismatch(parsed.get("company"), subject, source="MCA")
    if parsed.get("name_history"):
        flags.append(F.flag(
            "warn", "Company has been renamed",
            f"{F.plural(len(parsed['name_history']), 'previous name')} on record. "
            f"Searches run against the current name will not find history "
            f"filed under the old one.",
        ))
    if parsed.get("cin_history"):
        flags.append(F.flag(
            "info", "CIN has changed",
            "The company was re-registered at some point; earlier filings sit "
            "under the previous CIN.",
        ))

    return F.build(
        F.DETAIL,
        fields=[
            F.field("Status", status, tone="good" if status.lower() == "active" else "warn"),
            F.field("CIN", parsed.get("cin"), format="id"),
            F.field("Registered name", parsed.get("company")),
            F.field("Class", parsed.get("class_of_company")),
            F.field("Company type", parsed.get("company_type")),
            F.field("Listed", _yn(parsed.get("listed")),
                    note="Whether the company's shares are listed on a "
                         "recognised stock exchange."),
            F.field("Incorporated", F.human_date(parsed.get("incorporated_on")), format="date"),
            F.field("Paid-up capital", F.crore(parsed.get("paidup_capital")), format="money"),
            F.field("Authorised capital", F.crore(parsed.get("authorised_capital")),
                    format="money"),
            F.field("Last AGM", F.human_date(parsed.get("last_agm_on")), format="date"),
            F.field("Balance sheet date", F.human_date(parsed.get("balance_sheet_on")),
                    format="date"),
            F.field("Directors on record", parsed.get("director_count"), format="count"),
            F.field("Principal activity", parsed.get("nic_division")),
            F.field("Registered address", ", ".join(p for p in (
                parsed.get("registered_address"),
                parsed.get("registered_city"),
                parsed.get("registered_state"),
            ) if p)),
        ],
        flags=flags,
    )


def resolve_candidates(candidates: list[dict], *, subject: str | None = None) -> dict:
    """Name → CIN. Which company the rest of the dossier is about.

    Everything downstream inherits whichever CIN is picked here, so this is
    the one place where being wrong is silently and completely wrong. The
    candidates are shown with their scores rather than collapsed to the
    winner.
    """
    strong = [c for c in candidates if (c.get("matchScore") or 0) >= 0.9]
    flags = []
    if len(strong) > 1:
        flags.append(F.flag(
            "warn", f"{len(strong)} companies match this name closely",
            "The ambiguity is surfaced rather than resolved automatically — "
            "auditing the wrong company is worse than auditing none.",
        ))
    elif candidates and subject:
        flags.extend(entity_mismatch(
            candidates[0].get("company"), subject, source="MCA name search",
        ))

    return F.build(
        F.TABLE,
        rows=F.table(
            [
                F.column("company", "Company"),
                F.column("cin", "CIN", format="id"),
                F.column("score", "Match", align="right"),
                F.column("state", "State"),
                F.column("status", "Status"),
            ],
            [
                {
                    "company": c.get("company"),
                    "cin": c.get("cin"),
                    "score": c.get("matchScore"),
                    "state": c.get("state"),
                    "status": c.get("status"),
                }
                for c in candidates
            ],
            empty_note="No MCA registration traced under this name — "
                       "consistent with a proprietorship or partnership firm, "
                       "which are not registered with MCA at all.",
        ),
        flags=flags,
    )


def directors(rows: list[dict]) -> dict:
    """The directors table.

    PAN is in the normalised rows and is deliberately NOT carried through.
    This blob is what a client-facing screen reads; the PAN stays in
    ``raw_response`` behind its own grants.
    """
    disqualified = [d for d in rows if d.get("disqualified")]
    flags = []
    if disqualified:
        flags.append(F.flag(
            "bad", F.plural(len(disqualified), "disqualified director"),
            ", ".join(d.get("name") or d.get("din") or "?" for d in disqualified)
            + ". A disqualification under s.164 bars the person from a board "
              "seat and is not cured by the company's own standing.",
        ))

    return F.build(
        F.TABLE,
        derived_from="master",
        stats=[
            F.stat("On the board", len(rows)),
            F.stat("Disqualified", len(disqualified),
                   tone="bad" if disqualified else "good"),
            F.stat("Still serving", sum(1 for d in rows if d.get("still_serving"))),
        ],
        rows=F.table(
            [
                F.column("din", "DIN", format="id"),
                F.column("name", "Name"),
                F.column("designation", "Designation"),
                F.column("appointed", "Appointed", format="date"),
                F.column("ceased", "Ceased", format="date"),
                F.column("disqualified", "Disqualified"),
                F.column("others", "Other boards", align="right", format="count"),
            ],
            [
                {
                    "din": d.get("din"),
                    "name": d.get("name"),
                    "designation": ", ".join(d.get("designations") or []) or None,
                    "appointed": F.human_date(d.get("appointed_on")),
                    "ceased": F.human_date(d.get("ceased_on")),
                    "disqualified": F.yes_no(d.get("disqualified")),
                    "others": len(d.get("other_companies") or []),
                }
                for d in rows
            ],
            empty_note="MCA lists no directors against this company — unusual "
                       "for an active registration and worth confirming.",
        ),
        flags=flags,
    )


def director_profiles(profiles: list[dict]) -> dict:
    """Directorships held elsewhere, across every profile fetched.

    ``dirs`` and ``dprof`` describe the same concept through different
    envelopes — ``roles``/``companyName``/``cin`` against
    ``companyData``/``nameOfTheCompany``/``cin_LLPIN``. Reconciling that is
    this function's job; the screen must never see both spellings.
    """
    rows: list[dict] = []
    flags: list[dict] = []

    for profile in profiles:
        person = (profile.get("name") or profile.get("directorName")
                  or profile.get("din") or "—")
        companies = profile.get("companyData") or profile.get("roles") or []
        row_disq = any(
            str(c.get("isDisqualified") or "").upper() == "Y" for c in companies
        )
        # A top-level flag with nothing under it to support it is a
        # contradiction in the source, not a finding. It gets surfaced as
        # neither clean nor adverse — a person decides.
        if profile.get("disqualified") and not row_disq:
            flags.append(F.flag(
                "warn", f"Contradictory disqualification flag — {person}",
                "The profile header reports this director as disqualified, but "
                "no individual directorship carries the flag. The source "
                "disagrees with itself; confirm against the MCA record before "
                "either reading is used.",
            ))
        for c in companies:
            rows.append({
                "person": person,
                "company": c.get("nameOfTheCompany") or c.get("companyName"),
                "cin": c.get("cin_LLPIN") or c.get("cin"),
                "role": c.get("designation"),
                "from": F.human_date(c.get("appointmentDate") or c.get("dateOfAppointment")),
                "to": F.human_date(c.get("cessationDate")),
            })

    active = sum(1 for r in rows if not r["to"])
    return F.build(
        F.TABLE,
        stats=[
            F.stat("Profiles retrieved", len(profiles)),
            F.stat("Directorships", len(rows)),
            F.stat("Currently active", active),
        ],
        rows=F.table(
            [
                F.column("person", "Director"),
                F.column("company", "Company"),
                F.column("cin", "CIN", format="id"),
                F.column("role", "Role"),
                F.column("from", "From", format="date"),
                F.column("to", "To", format="date"),
            ],
            rows,
            empty_note="No other directorships on record for these individuals.",
        ),
        flags=flags,
    )


def company_names(candidate: dict) -> list[str]:
    """The company names on a director-resolve candidate, whatever shape
    they arrive in.

    `companies` comes back either as plain strings or as objects carrying a
    name and a CIN, depending on the account. Joining the list blind raised
    ``TypeError: expected str instance, dict found`` — and a parser that
    crashes is worse than the blank column it was written to fix, because
    the call has already been paid for and the whole check dies with it.

    Module-level rather than a closure because the runner's summary line
    reads the same list for the same reason, and two copies of a coercion
    is how one of them ends up not fixed.
    """
    out: list[str] = []
    for entry in candidate.get("companies") or []:
        if isinstance(entry, dict):
            entry = (entry.get("name") or entry.get("companyName")
                     or entry.get("cin") or "")
        text = str(entry or "").strip()
        if text:
            out.append(text)
    return out


def director_candidates(
    candidates: list[dict], *, query: str = "", alarm: int = 20,
) -> dict:
    """Name → DIN. Which of the same-named people is actually meant.

    The field names here were wrong and the table rendered as a column of
    DINs beside four columns of dashes — `name`, `fatherName`, `dateOfBirth`
    are not what this endpoint returns. It sends `fullName`, `status`,
    `companies` and `dinAllocationDate`.

    `companies` was the costly omission. A search for "Mukesh Dhirubhai
    Ambani" returns four DINs: three **Lapsed** with no companies, and one
    **Approved** sitting on RELIANCE INDUSTRIES LIMITED, JIO PLATFORMS and
    eight others. The answer is obvious the moment those two columns are on
    screen and impossible without them — and picking the wrong DIN here
    poisons every director check downstream.

    `matchScore` is deliberately NOT shown. This endpoint returns it as
    1736172819525404700 — identical for every candidate, and no more a
    ranking than a row number is.
    """
    def _count(c: dict) -> int:
        return int(c.get("totalDirectorshipCount") or 0)

    def _name(c: dict) -> str:
        return str(c.get("fullName") or c.get("name") or c.get("din") or "?")

    def _active(c: dict) -> bool:
        return str(c.get("status") or "").strip().lower() == "approved"

    _companies = company_names

    flags = []

    # The disambiguation, stated rather than left to the reader. An
    # Approved DIN holding directorships and a Lapsed one holding none are
    # not equally likely to be the person being audited.
    live = [c for c in candidates if _active(c) and _count(c)]
    if len(candidates) > 1 and len(live) == 1:
        winner = live[0]
        flags.append(F.flag(
            "info", f"One candidate is active: DIN {winner.get('din')}",
            f"{_name(winner)} — status {winner.get('status')}, "
            f"{F.plural(_count(winner), 'directorship')}"
            + (f", including {_companies(winner)[0]}" if _companies(winner) else "")
            + f". The other {len(candidates) - 1} are lapsed and hold none. "
              f"Still confirm before the DIN is used downstream — MCA does "
              f"not disambiguate names, and this is an inference from status, "
              f"not an identification.",
        ))
    elif len(candidates) > 1:
        flags.append(F.flag(
            "warn", f"{len(candidates)} people match this name",
            "Director names are not unique and MCA does not disambiguate "
            "them. Nothing in the response separates these candidates, so a "
            "person must pick before the DIN is used anywhere downstream.",
        ))

    loaded = [c for c in candidates if _count(c) >= alarm]
    if loaded:
        flags.append(F.flag(
            "warn", "Unusually high directorship count",
            ", ".join(f"{_name(c)} sits on {_count(c)} boards" for c in loaded)
            + f". At {alarm}+ this is the mass-director pattern — often a "
              f"nominee lending a signature rather than a person exercising "
              f"judgement. Not adverse on its own.",
        ))

    return F.build(
        F.TABLE,
        stats=[
            F.stat("Candidates", len(candidates)),
            F.stat("Active DINs", sum(1 for c in candidates if _active(c)),
                   tone="good" if len(live) == 1 else "warn"),
        ] if candidates else None,
        fields=[F.field("Searched for", query, format="id")] if query else None,
        rows=F.table(
            [
                F.column("din", "DIN", format="id"),
                F.column("name", "Name"),
                F.column("status", "DIN status"),
                F.column("boards", "Boards", align="right", format="count"),
                F.column("companies", "Companies"),
                F.column("allocated", "DIN allocated", format="date"),
            ],
            [
                {
                    "din": c.get("din") or c.get("DIN"),
                    "name": c.get("fullName") or c.get("name"),
                    "status": c.get("status"),
                    "boards": _count(c),
                    # The whole point of this row. Truncated because a
                    # conglomerate director can hold dozens and the count
                    # beside it already says how many there are.
                    "companies": (
                        ", ".join(_companies(c)[:4])
                        + (f" … and {len(_companies(c)) - 4} more"
                           if len(_companies(c)) > 4 else "")
                    ) or None,
                    "allocated": F.human_date(parse_date(c.get("dinAllocationDate"))),
                }
                for c in candidates
            ],
            empty_note="No director on the MCA register matches this name. A "
                       "person can hold no DIN and still be an officer, so "
                       "this is a gap rather than a clearance.",
        ),
        flags=flags,
    )


def _mask_email(value: Any) -> str | None:
    """``amit.sharma@acme.in`` → ``a***@acme.in``.

    MCA returns the mobile already masked; the email it returns whole. This
    blob is the tier a client-facing screen reads, and a working personal
    address is the single most re-usable piece of data in the dossier. The
    unredacted value stays in ``raw_response`` behind its own grants, which
    is the split the DPDP note asks for.
    """
    text = str(value or "").strip()
    if "@" not in text:
        return text or None
    local, _, host = text.partition("@")
    return f"{local[:1]}***@{host}" if local else f"***@{host}"


def director_contacts(contacts: list[dict]) -> dict:
    """Contact details as filed with MCA.

    Deliberately redacted HERE rather than at retention time: a parser that
    never writes the identifier cannot leak it, and the column a screen
    reads then needs no special grant at all.
    """
    reachable = sum(1 for c in contacts if c.get("email") or c.get("mobile"))
    return F.build(
        F.TABLE,
        stats=[
            F.stat("Directors looked up", len(contacts)),
            F.stat("Contactable", reachable,
                   tone="good" if reachable else "warn"),
        ],
        rows=F.table(
            [
                F.column("din", "DIN", format="id"),
                F.column("email", "Email"),
                F.column("mobile", "Mobile"),
            ],
            [
                {
                    "din": c.get("din"),
                    "email": _mask_email(c.get("email")),
                    # Already masked by the source. Passed through as-is
                    # rather than re-masked, so what is shown is what MCA
                    # holds.
                    "mobile": c.get("mobile") or c.get("mobileNumber"),
                }
                for c in contacts
            ],
            empty_note="MCA holds no contact details for these directors — "
                       "common where filings were made through a practitioner.",
        ),
        note="Addresses are shown part-masked. The values exactly as MCA "
             "returned them are in the stored response, which is held under "
             "narrower access than this summary.",
    )


def refresh_pending(check_id: str, stage: str) -> dict:
    """The unlock landed; the documents behind it have not.

    Rendered as a flag rather than a bare status line because the reader
    needs to know this row will look different in half an hour. Without it,
    "Documents not ready" reads like a permanent property of the vendor.
    """
    return F.build(
        F.NONE,
        flags=[F.flag(
            "info", "Waiting on the provider's document refresh",
            f"Unlocking a company queues a download and extraction that takes "
            f"10–30 minutes (current stage: {stage}). Until it finishes the "
            f"source returns nothing here, so this check is recorded as "
            f"unexamined rather than as an absence. Re-run it shortly — the "
            f"unlock fee is not charged again.",
        )],
        note=f"{check_id} depends on documents the unlock is still preparing.",
    )


def filing_document(
    filing_id: str, size_bytes: int, digest: str, *,
    href: str | None = None, note: str = "",
) -> dict:
    """A filing PDF, with a link to it when it was successfully stored.

    When it was not, the gap is stated rather than implied: a row reading
    "document retrieved" with nothing to open looks like an attachment that
    failed to load, when the truth is that the file was never kept.
    """
    return F.build(
        F.DOCUMENT,
        fields=[
            F.field("Filing ID", filing_id, format="id"),
            F.field("Size", f"{size_bytes:,} bytes", format="count"),
            F.field("SHA-256", digest, format="id",
                    note="The digest is the storage key AND the integrity "
                         "check — a stored file cannot be altered without "
                         "changing its own name."),
        ],
        documents=[F.document(f"Filing {filing_id}", "pdf",
                              size_bytes=size_bytes, href=href)],
        flags=None if href else [F.flag(
            "warn", "Document is identified, not retained",
            (note or "The file itself was not stored.") + " The digest above "
            "proves which document was fetched; it is not a substitute for "
            "the document.",
        )],
    )


def refresh_receipt(data: dict, *, what: str, cached: bool) -> dict:
    """A paid refresh. A receipt, not a finding about the vendor."""
    flags = []
    if cached:
        flags.append(F.flag(
            "warn", "Billed, but nothing was refreshed",
            "The source charged for this call and answered from its own "
            "cache — no fresh pull from MCA happened. The data on file is no "
            "newer than it was before.",
        ))
    return F.build(
        F.REFERENCE,
        fields=[
            F.field("Result", "Served from cache" if cached else "Queued",
                    tone="warn" if cached else "good"),
            F.field("Status", data.get("status")),
            F.field("Cooldown until",
                    F.human_date(data.get("cooldownUntil") or data.get("cooldown_until")),
                    format="date",
                    note="Calling again before this bills again and returns "
                         "the same data."),
        ],
        flags=flags,
        note=f"{what} — an operation on our copy of the record, not a "
             f"finding about the vendor.",
    )


def company_update(
    triggered: dict, state: dict, *, polls: int = 0, done: bool = False,
) -> dict:
    """The ₹150 asynchronous company update."""
    flags = []
    if not done:
        flags.append(F.flag(
            "warn", "Charged and still running",
            "The poll budget ran out, not the job — it continues on the "
            "source's side. Re-run the company master check later rather "
            "than paying for a second update.",
        ))
    return F.build(
        F.REFERENCE,
        fields=[
            F.field("Status", state.get("status"),
                    tone="good" if done else "warn"),
            F.field("Job", triggered.get("jobId") or triggered.get("id"), format="id"),
            F.field("Polls", polls, format="count"),
            F.field("Message", state.get("message") or triggered.get("message")),
            F.field("Cooldown until",
                    F.human_date(triggered.get("cooldownUntil")), format="date"),
        ],
        flags=flags,
        note="A refresh of our copy of the MCA record. Re-run the company "
             "master check to read what changed.",
    )


def charges(parsed: dict) -> dict:
    """Secured lending. The provider pre-splits open and closed; use its split."""
    open_rows = parsed.get("open") or []
    closed_rows = parsed.get("closed") or []
    return F.build(
        F.SUMMARY,
        stats=[
            F.stat("Open charges", len(open_rows),
                   tone="warn" if open_rows else "good"),
            F.stat("Secured amount", F.crore(parsed.get("open_total")) or "₹0",
                   tone="warn" if open_rows else "neutral"),
            F.stat("Satisfied", len(closed_rows)),
            F.stat("Satisfied amount", F.crore(parsed.get("closed_total")) or "₹0"),
        ],
        rows=F.table(
            [
                F.column("holder", "Charge holder"),
                F.column("amount", "Amount", align="right", format="money"),
                F.column("created", "Created", format="date"),
                F.column("satisfied", "Satisfied", format="date"),
                F.column("status", "Status"),
            ],
            [
                {
                    "holder": c.get("holder"),
                    "amount": F.crore(c.get("amount")),
                    "created": F.human_date(c.get("created_on")),
                    "satisfied": F.human_date(c.get("satisfied_on")),
                    "status": c.get("status"),
                }
                for c in [*open_rows, *closed_rows]
            ],
            empty_note="No charges registered against this company — no "
                       "secured borrowing on the MCA record.",
        ),
        derived_from="master",
    )


def filings(rows: list[dict], meta: dict) -> dict:
    """Filing history. Fifty rows out of a few thousand is normal here."""
    return F.build(
        F.TABLE,
        stats=[
            F.stat("Filings on record", meta.get("total") or len(rows)),
            F.stat("Shown", len(rows)),
        ],
        rows=F.table(
            [
                F.column("form", "Form", format="id"),
                F.column("description", "Description"),
                F.column("filed", "Filed on", format="date"),
                F.column("year", "FY", align="right"),
            ],
            [
                {
                    "form": r.get("formId") or r.get("formType"),
                    "description": r.get("formDescription") or r.get("description"),
                    "filed": F.human_date(r.get("dateOfFiling")),
                    "year": r.get("year") or r.get("financialYear"),
                }
                for r in rows
            ],
            total=meta.get("total"),
            empty_note="No filings match this filter. The form ID is spelled "
                       "inconsistently by MCA, so an empty result here has "
                       "already been re-checked unfiltered.",
        ),
    )


def financials(parsed: dict) -> dict:
    """Filed accounts, from the XBRL extraction."""
    gaps = parsed.get("year_gaps") or []
    flags = []
    if gaps:
        flags.append(F.flag(
            "warn", "Gaps in the filing record",
            f"No accounts filed for {', '.join(str(g) for g in gaps)}. "
            f"A missing year is a compliance fact, not an absence of data.",
        ))
    if parsed.get("net_worth") is not None and parsed["net_worth"] <= 0:
        flags.append(F.flag(
            "bad", "Negative or nil net worth",
            f"Net worth {F.crore(parsed['net_worth'])} at the close of the "
            f"filed period.",
        ))

    figures = parsed.get("figures") or []
    return F.build(
        F.DETAIL,
        fields=[
            F.field("Scope", parsed.get("scope")),
            F.field("Period", " – ".join(p for p in (
                F.human_date(parsed.get("period_start")),
                F.human_date(parsed.get("period_end")),
            ) if p), format="date"),
            F.field("Filed on", F.human_date(parsed.get("filed_on")), format="date"),
            F.field("Revenue", F.crore(parsed.get("revenue")), format="money"),
            F.field("Net worth", F.crore(parsed.get("net_worth")), format="money",
                    tone="good" if parsed.get("positive_net_worth") else "bad"),
            F.field("Taxonomy", parsed.get("taxonomy"),
                    note="The XBRL prefix differs between filings; a change "
                         "here is the usual cause of a blank figure."),
        ],
        rows=F.table(
            [
                F.column("label", "Line item"),
                F.column("value", "Value", align="right", format="money"),
                F.column("section", "Section"),
            ],
            [
                {
                    "label": f.get("label"),
                    "value": F.crore(f.get("value")),
                    "section": f.get("section"),
                }
                for f in figures
            ],
            empty_note="The filing carried no extractable figures.",
        ) if figures else None,
        flags=flags,
    )


# =====================================================================
# Domain · WhoisXML
# =====================================================================

def whois(data: dict) -> dict:
    """Ownership history. The provider already summarises; don't recompute."""
    records = data.get("records") or []
    age = data.get("age_years")
    return F.build(
        F.DETAIL,
        stats=[
            F.stat("Domain age", f"{age} yrs" if age is not None else "—",
                   tone="good" if (age or 0) >= 2 else "warn"),
            F.stat("Registrar changes", data.get("registrar_changes")),
            F.stat("History records", data.get("records_count") or len(records)),
        ],
        fields=[
            F.field("Registered", F.human_date(data.get("created")), format="date"),
            F.field("Expires", F.human_date(data.get("expires")), format="date"),
            F.field("Registrar", data.get("registrar")),
            F.field("Registrant", data.get("registrant") or "privacy-protected"),
            F.field("Registrant email", data.get("registrant_email")),
        ],
        rows=F.table(
            [
                F.column("seen", "Recorded", format="date"),
                F.column("registrar", "Registrar"),
                F.column("registrant", "Registrant"),
            ],
            [
                {
                    "seen": F.human_date(r.get("auditUpdatedDate") or r.get("updated")),
                    "registrar": r.get("registrarName") or r.get("registrar"),
                    "registrant": (r.get("registrant") or {}).get("organization")
                    if isinstance(r.get("registrant"), dict) else r.get("registrant"),
                }
                for r in records
            ],
            empty_note="No ownership history returned for this domain.",
        ) if records else None,
    )


def reputation(data: dict) -> dict:
    score = data.get("score")
    warnings = data.get("warnings") or []
    return F.build(
        F.DETAIL,
        stats=[F.stat("Trust score", score,
                      tone="good" if (score or 0) >= 80 else "warn")],
        fields=[
            F.field("Tests run", data.get("test_count"), format="count"),
            F.field("Warnings", len(warnings), format="count",
                    tone="warn" if warnings else "good"),
        ],
        rows=F.table(
            [F.column("warning", "Warning")],
            [{"warning": w.get("warning")} for w in warnings],
            empty_note="No warnings raised against this domain.",
        ),
    )


def ssl(data: dict, *, domain: str | None = None) -> dict:
    """Certificate. Two flags here that nothing else in the pipeline catches."""
    flags: list[dict] = []
    valid_to = _iso(data.get("valid_to"))
    if valid_to:
        remaining = (valid_to - _today()).days
        if remaining < 0:
            flags.append(F.flag(
                "bad", "Certificate has expired",
                f"Expired {F.human_date(valid_to)}, {abs(remaining)} days ago. "
                f"Visitors to the site see a browser security warning.",
            ))
        elif remaining <= 30:
            flags.append(F.flag(
                "warn", "Certificate expires shortly",
                f"Valid only until {F.human_date(valid_to)} — {remaining} days.",
            ))
    else:
        remaining = None

    common = data.get("common_name")
    names = data.get("dns_names") or []
    if domain and common:
        covered = any(host_covers(n, domain) for n in [common, *names])
        if not covered:
            flags.append(F.flag(
                "warn", "Certificate is for a different host",
                f"Issued to “{common}”, but the domain on file is "
                f"“{domain}”. The certificate belongs to a related host, so "
                f"it says nothing about the site being assessed.",
            ))

    return F.build(
        F.DETAIL,
        fields=[
            F.field("Served", F.yes_no(data.get("present")),
                    tone="good" if data.get("present") else "bad"),
            F.field("Common name", common, format="id"),
            F.field("Issuer", data.get("issuer")),
            F.field("Trusted CA", F.yes_no(data.get("trusted_ca")),
                    tone="good" if data.get("trusted_ca") else "bad"),
            F.field("Valid from", F.human_date(data.get("valid_from")), format="date"),
            F.field("Valid to", F.human_date(data.get("valid_to")), format="date",
                    tone="bad" if (remaining is not None and remaining < 0) else None),
            F.field("Days remaining", remaining, format="count",
                    tone="bad" if (remaining is not None and remaining < 0) else None),
            F.field("Validation", data.get("validation_type")),
            F.field("Key", " ".join(str(p) for p in (
                data.get("key_algorithm"), data.get("key_size")) if p)),
            F.field("Wildcard", F.yes_no(data.get("wildcard"))),
            F.field("Also covers", ", ".join(names[:8]) if names else None),
        ],
        flags=flags,
    )


def reverse_whois(data: dict) -> dict:
    domains = data.get("domains") or []
    return F.build(
        F.TABLE,
        stats=[F.stat("Domains, same owner", data.get("count"))],
        fields=[F.field("Searched on", data.get("term"), format="id")],
        rows=F.table(
            [F.column("domain", "Domain", format="url")],
            [{"domain": d if isinstance(d, str) else d.get("domainName")} for d in domains],
            total=data.get("count"),
            empty_note="No other domains registered to this owner. Not a "
                       "finding either way — most registrants are private.",
        ),
    )


def screenshot(size_bytes: int, url: str | None = None) -> dict:
    return F.build(
        F.DOCUMENT,
        documents=[F.document(url or "Website screenshot", "image", size_bytes=size_bytes)],
        note="Captured at the time of the run. The image is stored, not "
             "inlined into this response.",
    )


# =====================================================================
# Web presence · archive.org
# =====================================================================

def availability(data: dict) -> dict:
    return F.build(
        F.DETAIL,
        fields=[
            F.field("Archived", F.yes_no(data.get("archived")),
                    tone="good" if data.get("archived") else "bad"),
            F.field("First seen", F.human_date(data.get("first_seen")), format="date"),
            F.field("Last seen", F.human_date(data.get("last_seen")), format="date"),
            F.field("Snapshot", data.get("snapshot_url"), format="url"),
        ],
    )


def timeline(data: dict) -> dict:
    """Capture history. 301/302 are redirects, not outages — the adapter
    already knows that; this only presents what it decided."""
    outages = data.get("outages") or []
    last = _iso(data.get("last_capture"))
    flags: list[dict] = []
    if last and (_today() - last).days > STALE_CAPTURE_YEARS * 365:
        flags.append(F.flag(
            "warn", "Archive record is stale",
            f"The most recent capture is {F.human_date(last)}. The archive has "
            f"not visited recently, which is a fact about the archive — it is "
            f"not evidence that the site is down.",
        ))

    breakdown = data.get("status_breakdown") or {}
    return F.build(
        F.SUMMARY,
        stats=[
            F.stat("Captures", data.get("captures")),
            F.stat("Successful", data.get("ok_captures"),
                   tone="good" if data.get("ok_captures") else "warn"),
            F.stat("Redirects", data.get("redirects")),
            F.stat("Outages", len(outages), tone="warn" if outages else "good"),
        ],
        fields=[
            F.field("First capture", F.human_date(data.get("first_capture")), format="date"),
            F.field("First successful", F.human_date(data.get("first_ok_capture")),
                    format="date"),
            F.field("Last capture", F.human_date(data.get("last_capture")), format="date"),
            F.field("Continuous", F.yes_no(data.get("continuous")),
                    tone="good" if data.get("continuous") else "warn"),
        ],
        rows=F.table(
            [
                F.column("status", "HTTP status"),
                F.column("from", "From", format="date"),
                F.column("to", "To", format="date"),
            ],
            [
                {
                    "status": o.get("status"),
                    "from": F.human_date(o.get("from")),
                    "to": F.human_date(o.get("to")),
                }
                for o in outages
            ],
            empty_note="No gaps in the capture history.",
        ) if outages else (
            F.table(
                [F.column("code", "HTTP status"),
                 F.column("count", "Captures", align="right", format="count")],
                [{"code": k, "count": v} for k, v in sorted(breakdown.items())],
            ) if breakdown else None
        ),
        flags=flags,
    )


def mentions(data: dict) -> dict:
    """Loose archive hits. Fuzzy by construction — say so, loudly."""
    docs = data.get("docs") or []
    flags = []
    if data.get("note"):
        flags.append(F.flag(
            "info", "Matching is approximate",
            str(data["note"]) + " Rows here are candidates for a person to "
            "read, not findings.",
        ))
    return F.build(
        F.TABLE,
        stats=[F.stat("Loose hits", data.get("found"))],
        fields=[F.field("Searched for", data.get("q"), format="id")],
        rows=F.table(
            [
                F.column("title", "Title"),
                F.column("creator", "Source"),
                F.column("date", "Date", format="date"),
                F.column("identifier", "Identifier", format="id"),
            ],
            [
                {
                    "title": d.get("title"),
                    "creator": d.get("creator") or d.get("mediatype"),
                    "date": F.human_date(d.get("publicdate") or d.get("date")),
                    "identifier": d.get("identifier"),
                }
                for d in docs
            ],
            total=data.get("found"),
            empty_note="Nothing in the archive mentions this name.",
        ),
        flags=flags,
    )


# =====================================================================
# GST · FinAGG
# =====================================================================

def gst(data: dict, *, subject: str | None = None) -> dict:
    """Registration and status. Where a mistyped GSTIN gets caught."""
    status = str(data.get("status") or "")
    tone = "good" if data.get("is_active") else "bad"
    flags = entity_mismatch(
        data.get("legal_name") or data.get("trade_name"), subject, source="GSTN",
    )
    places = data.get("additional_places") or []

    return F.build(
        F.DETAIL,
        fields=[
            F.field("GSTIN", data.get("gstin"), format="id"),
            F.field("Status", status, tone=tone),
            F.field("Legal name", data.get("legal_name")),
            F.field("Trade name", data.get("trade_name")),
            F.field("Constitution", data.get("constitution")),
            F.field("Taxpayer type", data.get("taxpayer_type")),
            F.field("Composition scheme", F.yes_no(data.get("is_composition"))),
            F.field("Registered on", F.human_date(data.get("registered_on")), format="date"),
            F.field("Cancelled on", F.human_date(data.get("cancelled_on")), format="date",
                    tone="bad" if data.get("cancelled_on") else None),
            F.field("Nature of business", ", ".join(data.get("nature_of_business") or [])
                    if isinstance(data.get("nature_of_business"), list)
                    else data.get("nature_of_business")),
            F.field("Premises", data.get("premises_kind")),
            F.field("Principal address", data.get("address")),
            F.field("State jurisdiction", data.get("state_jurisdiction")),
            F.field("Centre jurisdiction", data.get("centre_jurisdiction")),
            F.field("e-Invoicing", data.get("einvoice_status")),
            F.field("Record last updated", F.human_date(data.get("record_last_updated")),
                    format="date"),
        ],
        rows=F.table(
            [F.column("address", "Additional place of business")],
            [{"address": p if isinstance(p, str) else p.get("address")} for p in places],
            total=data.get("additional_place_count"),
            empty_note="One place of business only.",
        ) if places else None,
        flags=flags,
    )


def gst_returns(data: dict) -> dict:
    rows = data.get("filings") or []
    months = data.get("months_since_last_filing")
    flags = []
    if data.get("fell_back_to_prior_fy"):
        flags.append(F.flag(
            "info", f"Read from FY {data.get('financial_year')}",
            "The current financial year has no filings due yet, so the count "
            "below is last year's — not this year's.",
        ))
    return F.build(
        F.SUMMARY,
        stats=[
            F.stat("Returns filed", data.get("filing_count"),
                   tone="good" if data.get("filing_count") else "bad"),
            F.stat("Months since last", months,
                   tone="bad" if (months or 0) > 3 else
                        "warn" if (months or 0) > 1 else "good"),
            F.stat("Financial year", data.get("financial_year")),
        ],
        fields=[
            F.field("Latest period", data.get("latest_period")),
            F.field("Latest filed on", F.human_date(data.get("latest_filed_on")),
                    format="date"),
            F.field("Return types", ", ".join(data.get("return_types") or [])),
        ],
        rows=F.table(
            [
                F.column("period", "Period"),
                F.column("type", "Return"),
                F.column("filed", "Filed on", format="date"),
                F.column("status", "Status"),
                F.column("arn", "ARN", format="id"),
            ],
            [
                {
                    "period": r.get("period"),
                    "type": r.get("return_type"),
                    "filed": F.human_date(r.get("filed_on")),
                    "status": r.get("status"),
                    "arn": r.get("arn"),
                }
                for r in rows
            ],
            empty_note="No returns filed in the year examined.",
        ),
        flags=flags,
    )


# =====================================================================
# Litigation · eCourts
# =====================================================================

def _hollow(row: dict) -> bool:
    """A result with a CNR and nothing else.

    The search index returns a stub when it matched on the CNR alone. Twenty
    stubs render as twenty cases found, which is the single most misleading
    thing this product could put in front of a client.
    """
    populated = [
        row.get("case_type") not in (None, "", "UNKNOWN"),
        bool(row.get("petitioners")),
        bool(row.get("respondents")),
        bool(row.get("filing_date")),
    ]
    return not any(populated)


def case_search(data: dict, *, subject: str | None = None) -> dict:
    rows = data.get("results") or []
    flags: list[dict] = []

    query = " ".join(str(q) for q in (data.get("query") or []))
    if subject and query:
        score = name_similarity(query, subject)
        # Two different problems, and the NEAR miss is the worse one. A
        # query nothing like the vendor's name is usually deliberate — a
        # trading name, a subsidiary. A query one or two characters off is a
        # typo, and court records match on exact party names, so it searched
        # for a company that does not exist and found nothing. "No cases"
        # then reaches the report as good news.
        if score < NAME_MATCH_FLOOR:
            flags.append(F.flag(
                "warn", "Search term differs from the vendor's legal name",
                f"Searched “{query}”, vendor on file is “{subject}”. Court "
                f"records match on exact party names — a difference this "
                f"large means the search may have missed the vendor entirely, "
                f"or found somebody else.",
            ))
        elif score < NAME_TYPO_CEILING:
            flags.append(F.flag(
                "bad", "Search term looks like a misspelling",
                f"Searched “{query}”, vendor on file is “{subject}”. These are "
                f"nearly the same string, which usually means a typo rather "
                f"than a deliberate variant. An exact-match registry returns "
                f"nothing for a misspelled party, and nothing must not be read "
                f"as no litigation — re-run against the exact legal name.",
            ))

    hollow = [r for r in rows if _hollow(r)]
    if hollow and len(hollow) == len(rows) and rows:
        flags.append(F.flag(
            "warn", f"All {len(rows)} results are empty records",
            "Every row carries a CNR and no case type, no parties and no "
            "filing date. These are index stubs, not matters — they must not "
            "be read as cases found against this vendor until each is looked "
            "up individually.",
        ))
    elif hollow:
        flags.append(F.flag(
            "info", f"{len(hollow)} of {len(rows)} results are empty records",
            "Those rows carry a CNR only. Look each up before counting it.",
        ))

    if data.get("unverified_filters"):
        flags.append(F.flag(
            "warn", "Query used unconfirmed filters",
            f"{', '.join(data['unverified_filters'])} are not in this "
            f"account's capability catalog, so the server may have ignored them.",
        ))

    return F.build(
        F.TABLE,
        stats=[
            F.stat("Cases matched", data.get("count"),
                   tone="warn" if data.get("count") else "good"),
            F.stat("Complete records", len(rows) - len(hollow)),
            F.stat("Index stubs", len(hollow), tone="warn" if hollow else "neutral"),
        ],
        fields=[F.field("Searched for", query, format="id")],
        rows=F.table(
            [
                F.column("cnr", "CNR", format="id"),
                F.column("case_type", "Type"),
                F.column("court", "Court"),
                F.column("filed", "Filed", format="date"),
                F.column("petitioners", "Petitioners"),
                F.column("respondents", "Respondents"),
            ],
            [
                {
                    "cnr": r.get("cnr"),
                    "case_type": None if str(r.get("case_type") or "").upper() == "UNKNOWN"
                    else r.get("case_type"),
                    "court": r.get("court_name") or r.get("court"),
                    "filed": F.human_date(r.get("filing_date")),
                    "petitioners": ", ".join(r.get("petitioners") or []) or None,
                    "respondents": ", ".join(r.get("respondents") or []) or None,
                }
                for r in rows
            ],
            total=data.get("total") or data.get("count"),
            empty_note="No court records name this party. Note this is a "
                       "search of the connected registries only.",
        ),
        flags=flags,
    )


def case_detail(data: dict) -> dict:
    """One matter.

    The payload carries every field twice — flattened at the top level and
    again inside ``court_case_data`` under camelCase names. Only the
    flattened set is read; the duplicate never reaches a screen.
    """
    parties = " v ".join(p for p in (
        ", ".join(data.get("petitioners") or []) or None,
        ", ".join(data.get("respondents") or []) or None,
    ) if p)

    flags = []
    if data.get("is_pending"):
        flags.append(F.flag(
            "warn", "Matter is live",
            "A pending case is a current exposure, not history.",
        ))

    return F.build(
        F.DETAIL,
        stats=[
            F.stat("Status", data.get("case_status"),
                   tone="warn" if data.get("is_pending") else "neutral"),
            F.stat("Hearings", data.get("hearing_count")),
            F.stat("Orders", data.get("order_count")),
            F.stat("Judgments", data.get("judgment_count")),
        ],
        fields=[
            F.field("CNR", data.get("cnr"), format="id"),
            F.field("Case number", data.get("case_number"), format="id"),
            F.field("Parties", parties),
            F.field("Type", data.get("case_type_sub") or data.get("case_type_label")
                    or data.get("case_type")),
            F.field("Category", data.get("case_category")),
            F.field("Acts and sections", data.get("acts_and_sections")),
            F.field("Court", data.get("court_name") or data.get("court_label")),
            F.field("District", data.get("district")),
            F.field("State", data.get("state")),
            F.field("Filed", F.human_date(data.get("filing_date")), format="date"),
            F.field("Registered", F.human_date(data.get("registration_date")), format="date"),
            F.field("First hearing", F.human_date(data.get("first_hearing_date")),
                    format="date"),
            F.field("Next hearing", F.human_date(data.get("next_hearing_date")),
                    format="date"),
            F.field("Decided", F.human_date(data.get("decision_date")), format="date"),
            F.field("Disposal", data.get("disposal_type_raw") or data.get("disposal_type"),
                    note="“Disposed” alone says nothing — a withdrawal and a "
                         "conviction are both disposals."),
            F.field("Duration", data.get("case_duration_days"), format="count"),
            F.field("FIR on record", F.yes_no(data.get("has_fir"))),
            F.field("Police station", data.get("police_station")),
            F.field("Source last modified", F.human_date(data.get("data_last_modified")),
                    format="date"),
        ],
        flags=flags,
    )


def hearings(data: dict) -> dict:
    rows = data.get("results") or data.get("items") or []
    listed = data.get("listed_count")
    return F.build(
        F.SUMMARY,
        stats=[
            F.stat("Checked", data.get("checked")),
            F.stat("Listed for hearing", listed, tone="warn" if listed else "good"),
        ],
        rows=F.table(
            [
                F.column("cnr", "CNR", format="id"),
                F.column("date", "Next date", format="date"),
                F.column("purpose", "Purpose"),
                F.column("court", "Court"),
            ],
            [
                {
                    "cnr": r.get("cnr"),
                    "date": F.human_date(r.get("hearing_date") or r.get("date")),
                    "purpose": r.get("purpose"),
                    "court": r.get("court_name") or r.get("court"),
                }
                for r in rows if isinstance(r, dict)
            ],
            empty_note="None of the matched cases are currently listed.",
        ),
    )


def _stem(filename: str) -> str:
    """``order-1.pdf`` → ``order-1``. The extension is already the badge."""
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def orders(cnr: str, fetched: list[dict], *, generated: bool = False) -> dict:
    """Order text and PDFs.

    Every order arrives as a ~50 KB base64 blob plus its markdown. Neither
    goes into the fact blob: the PDF is stored and linked, and only the first
    lines of the text travel as an excerpt.
    """
    docs = []
    for order in fetched:
        text = order.get("markdown") or order.get("content") or ""
        name = str(order.get("filename") or order.get("order") or "Order")

        if order.get("pdf_base64") or order.get("href"):
            docs.append(F.document(
                name, "pdf",
                size_bytes=(len(order["pdf_base64"]) * 3 // 4)
                if order.get("pdf_base64") else order.get("bytes"),
                # Set once the PDF has been decoded out of its base64 and
                # written to the store. Without it the row named a document
                # nobody could open.
                href=order.get("href"),
            ))

        # The readable half, and the one most people actually want. The PDF
        # is a signed scan of a court order; this is the same order as text
        # a person can read without downloading anything. It gets its own
        # entry rather than riding along as an excerpt because an excerpt is
        # capped at 400 characters and a court order is not 400 characters —
        # truncating it to a paragraph with a trailing ellipsis and calling
        # that "the order" is how a finding ends up looking answered when it
        # has only been sampled.
        if text:
            # "as filed" and "read off a scan by OCR" are NOT the same
            # claim, and the difference has to survive all the way to the
            # screen. A misread digit in an amount or a misread name in a
            # party puts something in an audit report that no court wrote.
            machine_read = order.get("text_source") == "ocr"
            docs.append(F.document(
                f"{_stem(name)} — "
                + ("text read from the scan (OCR)" if machine_read
                   else "readable text"),
                "text",
                size_bytes=len(text),
                excerpt=text,
                href=order.get("text_href"),
            ))
        elif order.get("pdf_base64") or order.get("href"):
            docs.append(F.document(
                f"{_stem(name)} — no text available", "text",
                excerpt=str(order.get("ocr_note") or
                            "This order came back as a scanned PDF the "
                            "provider could not convert to text. Open the "
                            "PDF above to read it."),
            ))
    return F.build(
        F.DOCUMENT,
        fields=[F.field("CNR", cnr, format="id")],
        documents=docs,
        note=("Analysis is produced by the PROVIDER's model, not by VBC. It is "
              "a sourced finding, not registry fact." if generated else
              "Order text as filed. PDFs are stored and linked, never inlined."),
        flags=_order_flags(fetched),
    )


def _order_flags(fetched: list[dict]) -> list[dict] | None:
    """What is true of these order documents, as opposed to of the case."""
    flags = []

    scanned = [o for o in fetched if o.get("text_source") == "ocr"]
    if scanned:
        languages = sorted({str(o.get("ocr_language")) for o in scanned
                            if o.get("ocr_language")})
        flags.append(F.flag(
            "warn",
            f"{F.plural(len(scanned), 'order')} read by OCR, not as filed",
            f"{_join([_stem(str(o.get('filename') or 'order')) for o in scanned])} "
            f"came back as scanned images, so the text shown is a MACHINE'S "
            f"READING of the page"
            + (f" (detected {', '.join(languages)})" if languages else "")
            + ". OCR misreads digits and names. The PDF is the document; "
              "quote the PDF, not this, and check any figure or party name "
              "against it before it goes in a report.",
        ))

    cut = [o for o in scanned if o.get("ocr_truncated")]
    if cut:
        flags.append(F.flag(
            "warn", "Only the first pages were read",
            f"{_join([_stem(str(o.get('filename') or 'order')) for o in cut])} "
            f"ran to the page limit, so the text below stops partway through "
            f"the order. The full document is in the PDF.",
        ))

    if any(o.get("store_note") for o in fetched):
        flags.append(F.flag(
            "warn", "Some orders were not retained",
            "; ".join(sorted({str(o["store_note"]) for o in fetched
                              if o.get("store_note")}))))

    return flags or None


def causelist(data: dict, *, subject: str | None = None) -> dict:
    """Who is listed in court this week, and for what.

    The field names here were wrong and two columns rendered as dashes on
    every row. This endpoint sends `listingNo`, not `item_number`, and
    `party` — singular — not `parties`. Losing them cost the two things
    this check exists to show: WHICH case, and WHO is on each side of it.

    `court` is the registry code (`MHSO07`). `courtLabel` is the court a
    person would recognise ("Civil Court Junior Division, Pandhurpur,
    Solapur"). The label leads; the code is not worth a column of its own.
    """
    rows = [r for r in (data.get("results") or data.get("items") or [])
            if isinstance(r, dict)]

    def _party(r: dict) -> str | None:
        """The provider pre-joins this as "A Vs. B". Where it hasn't, the
        two sides are still there as lists and can be joined here."""
        if r.get("party"):
            return str(r["party"])
        left = ", ".join(str(p) for p in (r.get("petitioners") or []) if p)
        right = ", ".join(str(p) for p in (r.get("respondents") or []) if p)
        if left and right:
            return f"{left} Vs. {right}"
        return left or right or r.get("parties") or r.get("litigant")

    def _case(r: dict) -> str | None:
        numbers = r.get("caseNumber") or r.get("case_number")
        if isinstance(numbers, list):
            return ", ".join(str(n) for n in numbers if n) or None
        return str(numbers) if numbers else r.get("internalCaseNo") or None

    flags = [F.flag(
        "info", "Name matching is fuzzy",
        "This list includes any party whose name CONTAINS the search term. "
        "For a group name that returns unrelated companies. An analyst must "
        "confirm which rows are this vendor before any of it counts.",
    )] if data.get("count") else []

    # Worth stating separately. A motor-accident claim against an insurer is
    # ordinary trading; a criminal listing is not, and an auditor should not
    # have to read thirteen rows to find out one of them is.
    criminal = [r for r in rows
                if str(r.get("listType") or "").strip().upper() == "CRIMINAL"]
    if criminal:
        flags.append(F.flag(
            "warn", f"{F.plural(len(criminal), 'criminal listing')}",
            ", ".join(f"{_case(r) or r.get('cnr')} at "
                      f"{r.get('courtLabel') or r.get('court')}"
                      for r in criminal[:4])
            + ". Listed as CRIMINAL by the court, which says nothing about "
              "who is accused — the vendor may be the complainant. Read the "
              "parties before this counts either way.",
        ))

    if data.get("truncated"):
        flags.append(F.flag(
            "warn", "Results were capped",
            f"Showing the first {data.get('limit')} — there are more.",
        ))

    return F.build(
        F.TABLE,
        stats=[
            F.stat("Listings", f"{data.get('count')}"
                   f"{'+' if data.get('truncated') else ''}",
                   tone="warn" if data.get("count") else "good"),
            F.stat("Criminal", len(criminal),
                   tone="bad" if criminal else "good"),
        ] if rows else None,
        rows=F.table(
            [
                F.column("date", "Listed on", format="date"),
                F.column("court", "Court"),
                F.column("case", "Case no"),
                F.column("parties", "Parties"),
                F.column("listed", "Listed for"),
                F.column("item", "Item", align="right", format="count"),
                F.column("cnr", "CNR", format="id"),
            ],
            [
                {
                    "date": F.human_date(r.get("date") or r.get("causelist_date")),
                    "court": r.get("courtLabel") or r.get("court_name")
                    or r.get("court"),
                    "case": _case(r),
                    "parties": _party(r),
                    # Null on a third of the live rows — the court simply has
                    # not said yet. A dash there is the truth, not a gap.
                    "listed": r.get("listingFor") or r.get("purpose"),
                    "item": r.get("listingNo") or r.get("item_number")
                    or r.get("serial"),
                    "cnr": r.get("cnr"),
                }
                for r in rows
            ],
            total=data.get("count"),
            empty_note="Nothing scheduled under this name.",
        ),
        flags=flags,
    )


def legal_check(data: dict) -> dict:
    """The scored LegalCheck product, as opposed to a raw registry search."""
    confident = bool(data.get("confident"))
    flags = [] if confident else [F.flag(
        "warn", "Identity confidence below the scoring threshold",
        f"Matched at {data.get('identity_confidence')}% confidence. Matches "
        f"may belong to a similarly-named party, so this is NOT scored — a "
        f"person confirms the subject before it counts.",
    )]
    return F.build(
        F.DETAIL,
        stats=[
            F.stat("Risk band", data.get("risk_band") or "UNKNOWN",
                   tone="bad" if data.get("risk_band") in ("HIGH", "MEDIUM") else "good"),
            F.stat("Matters matched", data.get("match_count")),
            F.stat("Identity confidence", f"{data.get('identity_confidence')}%",
                   tone="good" if confident else "warn"),
        ],
        fields=[
            F.field("Scored", F.yes_no(confident),
                    tone="good" if confident else "warn"),
            F.field("Model", data.get("model")),
            F.field("Score floor applied", data.get("min_score_applied")),
        ],
        flags=flags,
    )


# =====================================================================
# Internal
# =====================================================================

def inhouse(data: dict, *, kind: str) -> dict:
    """Duplicate, related-party and conflict checks.

    The count compared against is the finding when nothing matched. "No
    duplicate" means nothing without it; "no duplicate across 0 vendors" is
    a coverage gap wearing a pass.
    """
    matches = data.get("matches") or []
    compared = data.get("compared_against") or 0
    flags = []
    if not compared:
        flags.append(F.flag(
            "warn", "Nothing was compared",
            "No records were available to compare against, so this is a "
            "coverage gap rather than a clean result.",
        ))
    return F.build(
        F.TABLE,
        stats=[
            F.stat("Compared against", compared,
                   tone="warn" if not compared else "neutral"),
            F.stat("Matches", len(matches),
                   tone="bad" if matches else "good"),
        ],
        rows=F.table(
            [
                F.column("vendor", "Record", format="id"),
                F.column("rule", "Matched on"),
                F.column("confidence", "Confidence"),
                F.column("detail", "Detail"),
            ],
            [
                {
                    "vendor": m.get("vendorId") or m.get("employee"),
                    "rule": m.get("rule"),
                    "confidence": m.get("confidence"),
                    "detail": m.get("detail"),
                }
                for m in matches
            ],
            empty_note=f"No {kind} found across {compared} records compared.",
        ),
        flags=flags,
    )


# =====================================================================
# Account & reference
# =====================================================================

def usage(data: dict) -> dict:
    wallet = data.get("wallet") or {}
    return F.build(
        F.DETAIL,
        stats=[F.stat("Wallet balance", F.paisa(wallet.get("balancePaisa")))],
        fields=[
            F.field("Spent this period", F.paisa(wallet.get("spentPaisa")), format="money"),
            F.field("Credits remaining", wallet.get("credits"), format="count"),
            F.field("Calls this period", data.get("callCount"), format="count"),
        ],
    )


def unlock_status(status: Any) -> dict:
    data = status if isinstance(status, dict) else getattr(status, "__dict__", {})
    return F.reference(
        "Whether this company is unlocked for paid reads on the provider account.",
        fields=[
            F.field("Unlocked", F.yes_no(data.get("unlocked"))),
            F.field("Expires", F.human_date(data.get("expires_at")), format="date"),
        ],
    )


def job_receipt(data: dict, *, what: str) -> dict:
    """A refresh was queued. A receipt, not a finding about the vendor."""
    return F.reference(
        f"{what} was queued with the source. Re-run the dependent check "
        f"afterwards to see refreshed data.",
        fields=[
            F.field("Status", data.get("status")),
            F.field("Message", data.get("message")),
            F.field("Estimated time", data.get("estimated_time")),
        ],
    )


def catalog(summary: str, items: list[str]) -> dict:
    """Capability lists, enum codes, court structures, available dates."""
    return F.reference(
        summary,
        fields=[F.field("Values", ", ".join(str(i) for i in items[:40])
                        + (f" … and {len(items) - 40} more" if len(items) > 40 else ""))],
    )