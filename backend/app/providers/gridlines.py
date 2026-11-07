"""Gridlines — person-level checks on the vendor's own contact number.

WHAT THESE ARE, AND WHY THEY ARE DIFFERENT FROM EVERY OTHER ADAPTER
-------------------------------------------------------------------
Every other provider in this package reads a REGISTRY: MCA, GSTN, the
courts, the DNS. The record is about a company, it is public, and nobody's
permission is needed to read it.

These five are not that. They take a mobile number and return a NAMED
INDIVIDUAL's PAN, date of birth, residential address, digital footprint
and EPFO employment history. Even a company's own number resolves to
whoever holds the SIM — the proprietor, a director, the office manager.
So a finding from this adapter is personal data about a person, and the
report says so rather than presenting it as a company record.

CONSENT IS CARRIED, NOT ASSERTED
--------------------------------
Gridlines takes a ``consent`` field on every request. The obvious thing
to do — and what the Mobile Intelligence Suite does in all twenty-five of
its calls — is to hardcode ``"Y"``.

This adapter will not do that, and the refusal is structural rather than
stylistic: the literal appears nowhere in executable code here, and
``test_no_hardcoded_consent`` parses this module's AST to keep it that
way. ``consent`` arrives as an argument from the runner, which gets it
from an analyst's recorded attestation — a named human, a timestamp, an
audit row.

Mechanically that is almost the same request. The difference shows up
only once, when somebody asks on what basis a person's PAN was pulled,
and the answer is a name rather than a constant in a source file.

THE RESPONSE SHAPE IS NOT KNOWN YET
-----------------------------------
The Mobile Intelligence Suite calls these endpoints but never parses
them — its UI walks whatever JSON arrives and renders it generically, so
it records no response field anywhere. Documentation has been wrong about
this project's providers three times (``createdDateNormalized`` against
``createdDateISO8601`` on WhoisXML; ``SEARCHGSTIN`` against ``TP`` on
FinAGG; ``subject.name`` against ``subject.company_name`` on eCourts), so
nothing here guesses at a field name and calls it known.

Instead the adapter stores the payload whole and extracts only what it
can find across several plausible spellings. ``facts`` is a projection of
``raw_response`` and ``scripts/backfill_facts`` rebuilds it from stored
payloads for nothing, so the first real response can be parsed properly
and every historical row corrected without re-paying for a single call.

Where a payload clearly HAS content and this adapter extracted none,
``ParseGuard`` raises and the check reports ``unavailable`` with the
payload attached. It never reports a person as having no record because
we could not read the answer.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.providers.base import (
    HttpProvider,
    NotConfigured,
    ParseGuard,
    Spend,
)

logger = logging.getLogger(__name__)


#: Endpoints, verbatim from the Mobile Intelligence Suite's
#: `third_party.py`, which calls all of these in production.
PREFILL = "/profile-api/mobile/prefill"
FOOTPRINT = "/profile-api/mobile/digital-footprint"
ADDRESS = "/profile-api/mobile/address-lookup"
EPFO_UAN = "/epfo-api/fetch-uan"
EMPLOYMENT = "/epfo-api/employment-history/fetch-by-uan"


def dig(payload: Any, *keys: str, default: Any = None) -> Any:
    """Walk a nested payload, returning ``default`` at the first miss."""
    node = payload
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


def first_of(source: Any, *keys: str, default: Any = None) -> Any:
    """The first key present and non-empty, across several spellings.

    Written this way because the response shape is genuinely unknown —
    see the module docstring. A provider that calls it ``pan_number``
    and one that calls it ``pan`` are the same fact, and guessing one
    produces a silent None rather than an error.
    """
    if not isinstance(source, dict):
        return default
    for key in keys:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def deep_find(source: Any, *keys: str, default: Any = None) -> Any:
    """``first_of``, but at ANY DEPTH in the payload.

    THE LESSON FROM THE ONE RESPONSE WE HAVE SEEN.

    The digital-footprint parser failed not because its field names were
    all wrong, but because it looked for them in the wrong PLACE: the
    platform list sits four levels down, under
    ``digital_profile_data[].primary_data.account_details``. A top-level
    ``first_of`` could never have found it however many spellings it
    tried.

    The other four endpoints have still not been seen. Their envelope is
    now known — ``descend`` handles it — but where inside the payload
    each leaf sits is not. So they search the whole tree rather than one
    level of it.

    BREADTH-FIRST, deliberately: the shallowest match wins. On the
    footprint response ``digital_age`` appears at two depths and the
    shallower copy is the populated one. Depth-first would have returned
    the errored copy.

    This is a widened net, not a licence to invent. ``ParseGuard`` is
    unchanged: a payload that clearly carries content and still yields
    nothing raises, and the check reports ``unavailable`` with the bytes
    attached rather than telling anybody a person has no record.
    """
    queue: list[Any] = [source]
    while queue:
        nxt: list[Any] = []
        for node in queue:
            if isinstance(node, dict):
                for key in keys:
                    value = node.get(key)
                    if value not in (None, "", [], {}):
                        return value
                nxt.extend(node.values())
            elif isinstance(node, list):
                nxt.extend(node)
        queue = nxt
    return default


def deep_rows(source: Any, *keys: str) -> list:
    """Every list found under any of ``keys``, at any depth, concatenated.

    For the repeating sections — addresses, employment history — where
    the provider may return one list, several, or one nested inside a
    block. A single ``deep_find`` would take the first and silently drop
    the rest, and a dropped employer is exactly the kind of gap this
    product is not allowed to create.
    """
    out: list = []
    stack: list[Any] = [source]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys:
                    if isinstance(value, list):
                        out.extend(v for v in value if v not in (None, "", {}))
                    elif value not in (None, "", {}):
                        out.append(value)
                else:
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return out


def unwrap(payload: Any) -> dict:
    """The data object inside whatever envelope Gridlines uses.

    Tried in order, falling back to the payload itself. Unknown envelopes
    are the normal case on a first integration; an unknown one that is
    NOT unwrapped still reaches ParseGuard with its content intact, which
    is the failure mode we want.
    """
    for key in ("data", "result", "response"):
        inner = payload.get(key) if isinstance(payload, dict) else None
        # `isinstance` WITHOUT a truthiness test, deliberately. An EMPTY
        # envelope — `{"data": {}}` — is the provider saying "no record",
        # which is a real answer. Requiring a non-empty dict here fell
        # through to the wrapper, and ParseGuard then saw the key "data"
        # as unparsed content and reported a parse gap for a response
        # that was perfectly well understood.
        if isinstance(inner, dict):
            return inner
    return payload if isinstance(payload, dict) else {}


# =====================================================================
# THE ENVELOPE, NOW THAT WE HAVE SEEN ONE
# =====================================================================
#
# A real digital-footprint response, 7 Nov 2026, with the person's
# details removed:
#
#   {"request_id": …, "transaction_id": …, "status": 200,
#    "data": {"code": "1030",
#             "message": "Fetched digital footprint data.",
#             "digital_profile_data": [
#                 {"data_type": "phone_data", "primary_data": {…},
#                  "intelligence_data": {…}},
#                 {"data_type": "intelligence_data", "scores": [...]},
#                 {"data_type": "status_code"},
#                 {"data_type": "status"}]},
#    "timestamp": …, "path": "/profile-api/mobile/digital-footprint"}
#
# Two things this settles, and they were both guessed wrong before:
#
#  1. `unwrap` reaches `data` correctly, but `data` is NOT the payload —
#     it is a status envelope of its own, carrying `code`, `message`, and
#     ONE key ending in `_data` that holds everything. The parser was
#     searching the status envelope for field names that live two levels
#     further in, found nothing, and ParseGuard correctly refused to
#     report "no online presence" for a number that had eight profiles.
#
#  2. The payload is a LIST OF BLOCKS discriminated by `data_type`, not
#     a flat object. Position is not stable — `status_code` and `status`
#     blocks are interleaved with the real ones — so blocks are read by
#     their `data_type`, never by index.


def descend(data: dict) -> tuple[dict, str, str]:
    """Past Gridlines' status envelope to the payload itself.

    Returns ``(payload, code, message)``. ``code`` and ``message`` are
    the provider's own, kept because a response that carries them and no
    payload is the provider saying "nothing found" — a real answer — and
    must not be mistaken for a parse gap.

    The ``_data`` suffix is the convention across this API
    (``digital_profile_data`` here), so this is matched rather than
    named: naming it would mean one more field name per endpoint that
    nobody has verified, which is the mistake this module exists to stop
    making.
    """
    if not isinstance(data, dict):
        return {}, "", ""
    code = str(data.get("code") or "")
    message = str(data.get("message") or "")
    for key, value in data.items():
        if key.endswith("_data") and isinstance(value, (dict, list)):
            # Returned AS-IS, list or dict, and deliberately not wrapped.
            # ParseGuard is handed this as the raw content, and an empty
            # list has to stay an empty list: wrapped in a dict it looks
            # like content, and "the source found nothing" starts
            # reporting as a defect in our parser.
            return value, code, message
    return data, code, message


def blocks_by_type(payload: Any) -> dict:
    """The ``data_type``-keyed blocks, when the payload is a list.

    A flat payload comes back as a single unnamed block, so a caller can
    treat both shapes the same way — four of these five endpoints have
    not been seen yet and may not use the block convention at all.
    """
    if not isinstance(payload, list):
        return {"": payload if isinstance(payload, dict) else {}}
    out: dict[str, dict] = {}
    for row in payload:
        if isinstance(row, dict):
            out.setdefault(str(row.get("data_type") or ""), row)
    return out


def present_state(account: dict) -> bool | None:
    """Whether this number has an account on one platform.

    THREE STATES, NOT TWO. Gridlines returns ``{"platform": "AMAZON",
    "user_exist": true}``, ``{"platform": "SNAPDEAL", "user_exist":
    false}`` AND ``{"platform": "SKYPE", "error": true}``. The third is
    "we could not check", and collapsing it into "no account" is this
    product's cardinal sin at the level of a single row.
    """
    if account.get("error"):
        return None
    value = account.get("user_exist")
    return bool(value) if value is not None else None


class GridlinesProvider(HttpProvider):
    """The five person-level checks VBC calls."""

    name = "gridlines"

    def __init__(self, settings: Settings | None = None, client=None,
                 spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()

    # -----------------------------------------------------------------

    def _require_key(self) -> None:
        if not self.settings.gridlines_configured:
            raise NotConfigured(
                "Gridlines has no API key configured. Set "
                "VBC_GRIDLINES_API_KEY. Until then these checks report "
                "not_configured — which is NOT the same as a person having "
                "no record."
            )

    def _headers(self) -> dict:
        # Both headers are required. X-Auth-Type names the scheme; sending
        # only the key returns 401.
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.settings.gridlines_api_key,
            "X-Auth-Type": "API-Key",
        }

    def _url(self, path: str) -> str:
        return f"{self.settings.gridlines_base_url.rstrip('/')}{path}"

    def _call(self, path: str, body: dict, *, paisa: int, label: str) -> dict:
        """One POST, guarded and metered.

        NOTE the guard is inert while the price is 0 — `guard_paid` returns
        immediately at `paisa <= 0`. That is recorded in config.py as a
        live hazard rather than a default.
        """
        self._require_key()
        self.guard_paid(label, paisa)
        response = self.request(
            "POST", self._url(path), headers=self._headers(), json=body
        )
        self.spend.record(label, paisa=paisa)
        return response.payload or {}

    # -----------------------------------------------------------------
    # The five checks
    # -----------------------------------------------------------------

    def mobile_prefill(self, mobile: str, *, consent: str,
                       first_name: str = "", last_name: str = "") -> dict:
        """Identity behind a mobile number — name, PAN, DOB, address.

        `consent` is an argument, never a constant. See the module
        docstring.
        """
        body: dict[str, Any] = {"mobile_number": mobile, "consent": consent}
        # TOP-LEVEL, not nested under "name".
        #
        # This adapter sent `{"name": {"first_name": …, "last_name": …}}`,
        # which was invented here. The Mobile Intelligence Suite — the
        # integration that is live and working against this same key and
        # this same endpoint — sends them flat, and it is the only
        # evidence anyone has about what this endpoint accepts. Copied
        # from `third_party.py:api_mobile_prefill`, verbatim.
        if first_name:
            body["first_name"] = first_name
        if last_name:
            body["last_name"] = last_name
        payload = self._call(PREFILL, body,
                             paisa=self.settings.gridlines_prefill_paisa,
                             label="gridlines.prefill")
        data = unwrap(payload)
        inner, code, message = descend(data)

        # DEEP, not top-level. The one response anybody has seen from
        # this provider nests its real content four levels down; there
        # is no reason to expect this endpoint to be flatter.
        # WRITTEN AGAINST THE REAL RESPONSE, 7 Nov 2026:
        #
        #   data.personal_data
        #       personal_information  full_name, gender, age,
        #                             date_of_birth, income
        #       alternate_phone[]     {serial_number, value}
        #       email[]               {serial_number, value}
        #       address[]             {detailed_address, state, pincode,
        #                              date_of_reporting}
        #       document_data.pan[]   {serial_number, value}
        #
        # The repeatable fields are SERIAL-WRAPPED — see `serial_values`.
        # Reading them with a plain key lookup returned the whole list
        # where a string belonged, and the PAN mask then ran over a
        # stringified dict.
        parsed = {
            "name": deep_find(inner, "full_name", "name", "fullName",
                              "bank_verified_name"),
            "pan": first_serial(deep_find(inner, "pan", "pan_number",
                                          "panNumber")),
            "all_pans": serial_values(deep_find(inner, "pan", "pan_number")),
            "dob": deep_find(inner, "date_of_birth", "dob", "dateOfBirth"),
            "age": deep_find(inner, "age"),
            "gender": deep_find(inner, "gender"),
            "email": first_serial(deep_find(inner, "email", "email_id")),
            "all_emails": serial_values(deep_find(inner, "email", "email_id")),
            # Kept as the provider's own rows — `detailed_address`,
            # `state`, `pincode` and `date_of_reporting` — because WHEN
            # an address was last reported is the useful part and a
            # flattened string loses it.
            "addresses": [a for a in (deep_find(inner, "address", "addresses",
                                                "address_details") or [])
                          if isinstance(a, dict)] or
                         ([deep_find(inner, "full_address")]
                          if deep_find(inner, "full_address") else []),
            "alt_phones": serial_values(deep_find(
                inner, "alternate_phone", "phones", "alternate_numbers")),
            # PARSED, DELIBERATELY NOT RENDERED. See the note in
            # `factsets.person_identity`: an individual's income band
            # says nothing about a vendor company and does not belong in
            # a client-facing report. It stays in `raw_response` under
            # its own access controls, reachable if the methodology ever
            # calls for it.
            "income": deep_find(inner, "income", "income_range"),
            "code": code,
            "message": message,
        }

        guard = ParseGuard("gridlines.prefill")
        guard.expect("identity", raw=inner,
                     parsed=_any(_without_status(parsed)),
                     hint="the payload carried content but no recognised "
                          "identity field was extracted at any depth — "
                          "compare against `descend` and `deep_find`")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": shape_keys(inner)}

    def digital_footprint(self, mobile: str, *, consent: str,
                          email: str = "", name: str = "") -> dict:
        """Where this number appears online.

        WRITTEN AGAINST A REAL RESPONSE, unlike the first version. See
        the envelope note above `descend` for what that response looks
        like and what the first version got wrong.

        What this endpoint actually returns, for a vendor file:

          - one row per PLATFORM, in three states — has an account, does
            not, or could not be checked;
          - a bank-verified name for the number, which is the single
            most useful field here: it says who the SIM is registered
            to, independently of what the vendor told us;
          - a digital age, which is how long this number has had any
            footprint at all. A number first seen last year behind a
            company claiming a decade of trading is worth a human look;
          - category presence scores and an onboarding phone-risk score.

        Nothing here is scored or judged. These five checks feed no SCAN
        parameter, deliberately, and this one returns a provider's own
        risk number — passing that into our scoring would be importing
        somebody else's model under our catalog version.
        """
        body: dict[str, Any] = {"phone": mobile, "consent": consent}
        if email:
            body["email"] = email
        if name:
            body["name"] = name
        payload = self._call(FOOTPRINT, body,
                             paisa=self.settings.gridlines_footprint_paisa,
                             label="gridlines.footprint")
        data = unwrap(payload)
        inner, code, message = descend(data)
        blocks = blocks_by_type(inner)

        phone_block = blocks.get("phone_data") or {}
        primary = phone_block.get("primary_data") or {}
        intel = phone_block.get("intelligence_data") or {}
        scores_block = blocks.get("intelligence_data") or {}

        accounts = [a for a in (primary.get("account_details") or [])
                    if isinstance(a, dict) and a.get("platform")]
        platforms = [
            {"platform": str(a["platform"]), "present": present_state(a)}
            for a in accounts
        ]

        scores = {
            str(s.get("score_type")): (s.get("score_data") or {})
            for s in (scores_block.get("scores") or [])
            if isinstance(s, dict) and s.get("score_type")
        }
        # `{}` is a score that was NOT computed — `phone_email_linking_score`
        # came back empty on the first real response. Rendering that as 0
        # would be a number we invented.
        risk = (scores.get("onboarding_phone_risk_score") or {}).get("score_value")

        parsed = {
            "platforms": platforms,
            "profile_count": primary.get("social_profile_count"),
            # Prefer the populated block: `digital_age` appears twice and
            # the second copy came back `{"error": true}`.
            "digital_age": _age(intel.get("digital_age"))
                           or _age(scores_block.get("digital_age")),
            "verified_name": intel.get("bank_verified_name"),
            "associated_names": [
                n for n in (intel.get("associated_names") or [])
                if isinstance(n, dict) and n.get("name")
            ],
            "scores": scores,
            "risk_score": risk,
            "fintech_count": scores_block.get("fintech_count"),
            # Kept so the screen can show what the provider SAID when it
            # returned no payload — "nothing found" is an answer, and a
            # blank panel is not the way to report it.
            "code": code,
            "message": message,
            # Still read across spellings, because four of these five
            # endpoints have not been seen yet and may not nest the same
            # way. Costs nothing when the block above already matched.
            "email": first_of(primary, "email", "email_id"),
        }

        guard = ParseGuard("gridlines.footprint")
        # RAW IS THE PAYLOAD BLOCK, NOT THE STATUS ENVELOPE.
        #
        # `code` and `message` are present on every response including
        # the empty ones, so guarding against `data` would call a
        # legitimate "no record found" a parse gap — reporting a defect
        # in us where the provider gave a clear answer.
        #
        # And for the SAME reason they are excluded from "did we parse
        # anything": they are always set, so counting them would make
        # `_any` permanently truthy and the guard could never fire
        # again. A test caught that within a minute of this rewrite.
        guard.expect("footprint", raw=inner,
                     parsed=_any({k: v for k, v in parsed.items()
                                  if k not in ("code", "message")}),
                     hint="account_details / scores — the payload carried "
                          "blocks but none of them parsed; compare against "
                          "`descend` and `blocks_by_type`")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": sorted(blocks)}

    def address_lookup(self, mobile: str, *, consent: str) -> dict:
        """Addresses on record against this number."""
        payload = self._call(ADDRESS,
                             {"mobile_number": mobile, "consent": consent},
                             paisa=self.settings.gridlines_address_paisa,
                             label="gridlines.address")
        data = unwrap(payload)
        inner, code, message = descend(data)

        # `deep_rows`, not `deep_find`: the provider may return several
        # address lists in several blocks, and taking the first would
        # silently drop the rest.
        parsed = {
            "addresses": deep_rows(inner, "addresses", "address_list",
                                   "address", "address_details"),
            "name": deep_find(inner, "name", "full_name",
                              "bank_verified_name"),
            "code": code,
            "message": message,
        }
        guard = ParseGuard("gridlines.address")
        guard.expect("address", raw=inner,
                     parsed=_any(_without_status(parsed)),
                     hint="no recognised address field at any depth; "
                          "compare against `descend` and `deep_rows`")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": shape_keys(inner)}

    def epfo_member(self, mobile: str, *, consent: str,
                    pan: str | None = None) -> dict:
        """The UAN behind a mobile number.

        `pan` is optional in the Mobile Intelligence Suite's body, so it is
        optional here. Whether the response actually carries a UAN that
        `employment_history` can consume is INFERRED from the endpoint name
        and not yet proven — the first real response settles it, and until
        then `employment_history` simply requires the UAN as an input.
        """
        body: dict[str, Any] = {"mobile_number": mobile, "consent": consent}
        # `pan`, NOT `pan_number`.
        #
        # `pan_number` was invented here. The live integration sends
        # `pan` (`third_party.py:api_epfo_member`), and because the
        # vendor record usually HAS a PAN this field was present on
        # almost every real call — so the wrong spelling was not an edge
        # case, it was the normal request.
        #
        # Note the employment-history call below really does send
        # `uan_number`. The two are inconsistent at the provider, and
        # normalising them to match each other would break one of them.
        if pan:
            body["pan"] = pan.strip().upper()
        payload = self._call(EPFO_UAN, body,
                             paisa=self.settings.gridlines_epfo_member_paisa,
                             label="gridlines.epfo_member")
        data = unwrap(payload)
        inner, code, message = descend(data)

        parsed = {
            # By name first, then by SHAPE — see `find_uan`. The named
            # lookup is kept because it is cheaper and unambiguous when
            # it hits; the shape search is what stops a seventh guessed
            # spelling from costing another round trip.
            "uan": (deep_find(inner, "uan", "uan_number", "uanNumber")
                    or find_uan(inner)),
            "name": deep_find(inner, "name", "full_name", "member_name",
                              "bank_verified_name"),
            # NOT `status`: the envelope has a `status` of its own —
            # `"status": 200` sits at the top of every response — and a
            # deep search for it would report the HTTP code as the
            # member's EPFO status.
            "status": deep_find(inner, "uan_status", "member_status"),
            "code": code,
            "message": message,
        }
        guard = ParseGuard("gridlines.epfo_member")
        guard.expect("UAN", raw=inner, parsed=parsed["uan"],
                     hint="uan / uan_number — the field the employment "
                          "history check chains from")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": shape_keys(inner)}

    def employment_history(self, uan: str, *, consent: str) -> dict:
        """Employment history for a UAN."""
        payload = self._call(EMPLOYMENT,
                             {"uan_number": uan, "consent": consent},
                             paisa=self.settings.gridlines_employment_paisa,
                             label="gridlines.employment")
        data = unwrap(payload)
        inner, code, message = descend(data)

        # By NAME first, then by SHAPE. The named lookup is cheaper and
        # unambiguous when it hits; `find_employments` is what stops a
        # fourth guessed spelling from costing another round trip.
        rows = [r for r in deep_rows(inner, "employment_history", "history",
                                     "employments", "records",
                                     "employment_details")
                if isinstance(r, dict)]
        if not rows:
            rows = find_employments(inner)

        parsed = {
            "employments": rows,
            "name": deep_find(inner, "name", "full_name", "member_name",
                              "bank_verified_name"),
            "uan": (deep_find(inner, "uan", "uan_number")
                    or find_uan(inner) or uan),
            "code": code,
            "message": message,
        }
        guard = ParseGuard("gridlines.employment")
        guard.expect("employment history", raw=inner,
                     parsed=parsed["employments"],
                     hint="employment_history / history — the list of "
                          "employers and dates, at any depth")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": shape_keys(inner)}


def shape_keys(payload: Any) -> list[str]:
    """What the payload actually contained, for mapping it later.

    This is the field that makes a wrong parser cheap to fix: when a
    check comes back unreadable, `_raw_keys` is what says where to look
    next, and `scripts/backfill_facts` then rebuilds every affected row
    from storage for nothing.

    So it reports the payload's OWN keys — block names for a list,
    ordinary keys for a dict — and never the `[""]` that a
    `blocks_by_type` of a flat payload would produce, which says
    nothing to anybody.
    """
    if isinstance(payload, list):
        return sorted(blocks_by_type(payload))
    return sorted(payload) if isinstance(payload, dict) else []


def find_uan(payload: Any) -> str | None:
    """A UAN anywhere in the payload, found by SHAPE not by name.

    The EPFO membership call returned 200 and this adapter could not
    read the number out of it — the sixth field name in a row that was
    guessed rather than observed. Guessing a seventh is the same
    mistake with a different spelling.

    So: any key whose name contains "uan", whose value is exactly twelve
    digits. A UAN is a twelve-digit number and nothing else in an EPFO
    response is, so the pair of conditions identifies it without anyone
    having to know whether the provider calls it `uan`, `uan_number`,
    `member_uan`, `uanNo` or `UAN`.

    Breadth-first, so the shallowest match wins. Returns None rather
    than a near-miss: a value under a uan-ish key that is NOT twelve
    digits is something else, and feeding it to the employment-history
    call would buy an answer about nobody.
    """
    queue: list[Any] = [payload]
    while queue:
        nxt: list[Any] = []
        for node in queue:
            if isinstance(node, dict):
                for key, value in node.items():
                    if "uan" in str(key).lower():
                        digits = "".join(
                            c for c in str(value) if c.isdigit())
                        if len(digits) == 12 and str(value).strip() == digits:
                            return digits
                nxt.extend(node.values())
            elif isinstance(node, list):
                nxt.extend(node)
        queue = nxt
    return None


#: A key naming the employer. `establishment_name` is what the live
#: response used; the rest are the spellings seen elsewhere in EPFO
#: data and cost nothing to accept.
_EMPLOYER_KEYS = ("establishment_name", "employer_name", "establishment",
                  "employer", "company_name")

#: A key naming when the person joined.
_JOINED_KEYS = ("date_of_joining", "doj", "joining_date", "from_date")


def looks_like_employment(row: Any) -> bool:
    """Is this dict one employment record?

    An employment row names an EMPLOYER or says when somebody JOINED.
    Nothing else in an EPFO payload does both, and a record with
    neither is not one however it is labelled.
    """
    if not isinstance(row, dict):
        return False
    return (any(k in row for k in _EMPLOYER_KEYS)
            or any(k in row for k in _JOINED_KEYS))


def find_employments(payload: Any) -> list[dict]:
    """Every employment record in the payload, found by SHAPE.

    THE THIRD FIELD NAME THIS ADAPTER GUESSED WRONG, and the last one
    it will guess. The live response to `/epfo-api/employment-history/
    fetch-by-uan` carried `date_of_joining`, `establishment_name`,
    `guardian_name`, `member_id`, `name` and `service_period` — no
    `employment_history`, no `history`, no `employments`, no `records`.

    So the rows are identified by what they CONTAIN rather than by what
    the key around them is called. Both shapes are handled without
    knowing which the provider used: a list of records, and a single
    record returned bare.

    Order is preserved — an employment history read out of order is
    worse than none — and duplicates are dropped, because the same
    record reached through two keys is still one job.
    """
    out: list[dict] = []
    seen: list[dict] = []
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            if looks_like_employment(node):
                if node not in seen:
                    seen.append(node)
                    out.append(node)
                continue
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def serial_values(value: Any) -> list:
    """``[{"serial_number": "1", "value": "X"}]`` → ``["X"]``.

    THE WRAPPER THIS PROVIDER PUTS ROUND ITS REPEATABLE FIELDS. The
    live prefill response wraps `pan`, `email` and `alternate_phone`
    this way — a person can have more than one of each, and the serial
    number is which.

    Found on 7 Nov 2026, and it was doing real damage: a key-based
    lookup returned the whole LIST where a string was expected, so the
    PAN mask ran over `[{'serial_number': '1', 'value': 'OAYPS…'}]` and
    the screen showed masked rubbish instead of a PAN.

    Ordered by serial number when one is given, because "which phone
    number is the primary" is the question this field answers.
    """
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return [value] if value not in (None, "", [], {}) else []

    def order(row: Any) -> int:
        try:
            return int(str((row or {}).get("serial_number")))
        except (TypeError, ValueError, AttributeError):
            return 9999

    rows = sorted(value, key=order) if all(
        isinstance(r, dict) for r in value) else list(value)
    out = []
    for row in rows:
        inner = row.get("value") if isinstance(row, dict) else row
        if inner not in (None, "", [], {}):
            out.append(inner)
    return out


def first_serial(value: Any) -> Any:
    """The first value out of a serial-wrapped field, or None."""
    found = serial_values(value)
    return found[0] if found else None


def _without_status(parsed: dict) -> dict:
    """The parsed fields minus the envelope's own `code` and `message`.

    They are set on EVERY response, empty ones included, so counting
    them as "something was parsed" would make `_any` permanently truthy
    and ParseGuard could never fire again. Found by a test one minute
    after the first version of this was written.
    """
    return {k: v for k, v in parsed.items() if k not in ("code", "message")}


def _age(value: Any) -> str | None:
    """``{"age": "1+", "year": 2025}`` → ``"1+ years (first seen 2025)"``.

    ``{"error": true}`` returns None rather than an empty string: the
    second copy of this field came back exactly that way, and a blank
    where a number should be reads as "no footprint" rather than "not
    established".
    """
    if not isinstance(value, dict) or value.get("error"):
        return None
    age, year = value.get("age"), value.get("year")
    if age and year:
        return f"{age} years (first seen {year})"
    return str(age) if age else (f"first seen {year}" if year else None)


def _any(parsed: dict) -> Any:
    """Truthy when ANY field was extracted.

    ParseGuard asks "raw had content, parsed did not". With an unknown
    response shape, extracting even one recognised field is enough to say
    the adapter is reading the right payload; extracting none, from a
    payload that clearly has content, is exactly the gap worth raising.
    """
    return [v for v in parsed.values() if v not in (None, "", [], {})]
