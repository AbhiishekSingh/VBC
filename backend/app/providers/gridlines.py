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

        parsed = {
            "name": first_of(data, "name", "full_name", "fullName"),
            "pan": first_of(data, "pan", "pan_number", "panNumber"),
            "dob": first_of(data, "dob", "date_of_birth", "dateOfBirth"),
            "gender": first_of(data, "gender"),
            "email": first_of(data, "email", "email_id"),
            "address": first_of(data, "address", "full_address", "addresses"),
            "alt_phones": first_of(data, "alternate_phone", "phones",
                                   "alternate_numbers", default=[]),
        }

        guard = ParseGuard("gridlines.prefill")
        guard.expect("identity", raw=data, parsed=_any(parsed),
                     hint="the payload carried content but no recognised "
                          "identity field was extracted — the response shape "
                          "differs from what this adapter looks for")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": sorted(data) if data else []}

    def digital_footprint(self, mobile: str, *, consent: str,
                          email: str = "", name: str = "") -> dict:
        """Where this number appears online."""
        body: dict[str, Any] = {"phone": mobile, "consent": consent}
        if email:
            body["email"] = email
        if name:
            body["name"] = name
        payload = self._call(FOOTPRINT, body,
                             paisa=self.settings.gridlines_footprint_paisa,
                             label="gridlines.footprint")
        data = unwrap(payload)

        parsed = {
            "platforms": first_of(data, "platforms", "accounts", "services",
                                  "digital_footprint", default=[]),
            "email": first_of(data, "email", "email_id"),
            "name": first_of(data, "name", "full_name"),
        }
        guard = ParseGuard("gridlines.footprint")
        guard.expect("footprint", raw=data, parsed=_any(parsed),
                     hint="no recognised footprint field; see module docstring")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": sorted(data) if data else []}

    def address_lookup(self, mobile: str, *, consent: str) -> dict:
        """Addresses on record against this number."""
        payload = self._call(ADDRESS,
                             {"mobile_number": mobile, "consent": consent},
                             paisa=self.settings.gridlines_address_paisa,
                             label="gridlines.address")
        data = unwrap(payload)

        parsed = {
            "addresses": first_of(data, "addresses", "address_list",
                                  "address", default=[]),
            "name": first_of(data, "name", "full_name"),
        }
        guard = ParseGuard("gridlines.address")
        guard.expect("address", raw=data, parsed=_any(parsed),
                     hint="no recognised address field; see module docstring")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": sorted(data) if data else []}

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

        parsed = {
            "uan": first_of(data, "uan", "uan_number", "uanNumber"),
            "name": first_of(data, "name", "full_name", "member_name"),
            "status": first_of(data, "status", "uan_status"),
        }
        guard = ParseGuard("gridlines.epfo_member")
        guard.expect("UAN", raw=data, parsed=parsed["uan"],
                     hint="uan / uan_number — the field the employment "
                          "history check chains from")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": sorted(data) if data else []}

    def employment_history(self, uan: str, *, consent: str) -> dict:
        """Employment history for a UAN."""
        payload = self._call(EMPLOYMENT,
                             {"uan_number": uan, "consent": consent},
                             paisa=self.settings.gridlines_employment_paisa,
                             label="gridlines.employment")
        data = unwrap(payload)

        rows = first_of(data, "employment_history", "history", "employments",
                        "records", default=[])
        if isinstance(rows, dict):
            rows = [rows]

        parsed = {
            "employments": rows if isinstance(rows, list) else [],
            "name": first_of(data, "name", "full_name", "member_name"),
            "uan": first_of(data, "uan", "uan_number", default=uan),
        }
        guard = ParseGuard("gridlines.employment")
        guard.expect("employment history", raw=data,
                     parsed=parsed["employments"],
                     hint="employment_history / history — the list of "
                          "employers and dates")
        guard.raise_if_gaps(payload)
        return {**parsed, "_raw_keys": sorted(data) if data else []}


def _any(parsed: dict) -> Any:
    """Truthy when ANY field was extracted.

    ParseGuard asks "raw had content, parsed did not". With an unknown
    response shape, extracting even one recognised field is enough to say
    the adapter is reading the right payload; extracting none, from a
    payload that clearly has content, is exactly the gap worth raising.
    """
    return [v for v in parsed.values() if v not in (None, "", [], {})]
