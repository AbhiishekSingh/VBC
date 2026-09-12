"""FileSure (MCA) adapter.

Base: https://api.filesure.in    Header: x-api-key

Every gotcha catalogued in the API reference is handled here, in one place,
so no caller has to remember them:

  * Success wraps in ``data``, errors in ``error``. ``/update/status`` has
    NO ``meta`` object — never assume one exists.
  * Key casing is inconsistent WITHIN a single response: ``directorData``
    is PascalCase (DIN, PAN, FirstName), everything else camelCase, and
    extractions alone are snake_case.
  * Booleans are STRINGS. ``"DirectorDisqualified": "false"`` is truthy in
    Python. Always via ``as_bool``.
  * ``dateOfSatisfaction: null`` means the charge is OPEN — the headline
    audit fact, and the one most likely to be read backwards.
  * Filings ``data`` is a BARE ARRAY, unlike every other endpoint, with
    pagination in ``meta`` — and the sample returns limit 20 when 50 was
    asked for, so read ``meta.limit`` back.
  * Financials are XBRL ``{qname, value, unit}`` triples, not named fields,
    and reaching them is a THREE-step drill-down, not one call.
  * ``unlock`` is GET and POST on one path. GET is free. Always GET first —
    skipping it risks a duplicate ₹330 charge.
  * ``/update`` is async, charges ₹150 at trigger, and must be polled.
  * ``filings/refresh`` can charge ₹5 and return ``fromCache: true``,
    meaning no fresh MCA pull happened.
  * Director update routes are STUBS returning ``{stub: true}`` with 200 OK.
  * A test key returns SANDBOX_ONLY for real DINs and ``sandbox: true`` on
    unlocks — a green sandbox run is not evidence the live path works.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.providers.base import (
    HttpProvider,
    NotConfigured,
    ProviderResponse,
    SandboxLimitation,
    Spend,
    ParseGuard,
    as_bool,
    as_int,
    dig,
    is_blank,
    parse_date,
)

logger = logging.getLogger(__name__)

# UNIT PRICES, in paisa (₹1 = 100). Source: the account's own pricing
# table, effective 24 Aug 2026. Re-check against /v1/account/usage (free);
# the table has no end date.
#
#   ₹0.05  extractions (list/years/data), filings.download, directors.contact
#   ₹5     companies.{resolve,master,filings.list,filings.refresh}
#          directors.{resolve,profile}
#   ₹50    directors.unlock
#   ₹150   companies.update          (charged at trigger, async)
#   ₹330   companies.unlock          (once per company per year)
#
# The three extraction steps together cost ₹0.15 while one master read
# costs ₹5. Cost work belongs on the ₹5 reads, not the extractions.

CHEAP_PAISA = 5           # ₹0.05  extractions (all 3), filing download, director contact
READ_PAISA = 500          # ₹5     master, resolve (company + director), filings list, director profile
FILINGS_REFRESH_PAISA = 500     # ₹5     own ~6h cooldown
DIRECTOR_UNLOCK_PAISA = 5_000   # ₹50
COMPANY_UPDATE_PAISA = 15_000   # ₹150   async, charged at trigger
COMPANY_UNLOCK_PAISA = 33_000   # ₹330   once per company per year

#: Back-compat alias; not a distinct tier.
DOWNLOAD_PAISA = CHEAP_PAISA

#: directors.update costs ₹150 and returns {"stub": true} with HTTP 200.
#: Never called. Recorded only so the number is written down.
DIRECTOR_UPDATE_STUB_PAISA = 15_000


@dataclass
class UnlockStatus:
    unlocked: bool
    unlocked_at: str | None
    expires_at: str | None
    unlock_price_paisa: int | None
    sandbox: bool = False
    #: Bulk document ZIPs exposed by the unlock job — a cheaper alternative
    #: to per-filing downloads when many documents are needed.
    zip_urls: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.zip_urls is None:
            self.zip_urls = []


class FileSureProvider(HttpProvider):
    name = "filesure"

    def __init__(self, settings: Settings | None = None, client=None, spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()

    # -----------------------------------------------------------------

    def _require_key(self) -> None:
        if not self.settings.filesure_configured:
            raise NotConfigured(
                "FileSure has no API key configured. Set VBC_FILESURE_API_KEY. "
                "Until then MCA checks report not_configured rather than failing."
            )

    def _call(
        self, method: str, path: str, *, paisa: int = 0, binary: bool = False, **kwargs
    ) -> ProviderResponse:
        self._require_key()
        if paisa:
            self.guard_paid(path, paisa)

        response = self.request(
            method,
            f"{self.settings.filesure_base_url}{path}",
            headers={"x-api-key": self.settings.filesure_api_key},
            binary=binary,
            **kwargs,
        )

        # FileSure reports what it actually charged, and the wallet balance
        # after — cheaper and more accurate than assuming the rate card.
        charged = dig(response.payload, "meta", "priceChargedPaisa", default=None)
        wallet = dig(response.payload, "meta", "walletBalanceAfterPaisa", default=None)
        actual = int(charged) if isinstance(charged, (int, float)) else paisa
        response.paisa_charged = actual
        response.wallet_after = wallet
        if actual or wallet is not None:
            self.spend.record(path, paisa=actual, wallet_after=wallet)
        return response

    @staticmethod
    def _data(response: ProviderResponse) -> Any:
        """Unwrap the ``data`` envelope. Errors wrap in ``error`` instead."""
        payload = response.payload
        if isinstance(payload, dict):
            if "error" in payload and "data" not in payload:
                error = payload["error"]
                message = (
                    f"{error.get('code')}: {error.get('message')}"
                    if isinstance(error, dict)
                    else str(error)
                )
                raise SandboxLimitation(message) if "SANDBOX" in message.upper() else \
                    RuntimeError(f"FileSure error — {message}")
            return payload.get("data", payload)
        return payload

    # =================================================================
    # Companies
    # =================================================================

    def resolve_company(
        self, query: str, *, state: str = "", city: str = "", limit: int = 10
    ) -> list[dict]:
        """Name → CIN. Ranked by ``matchScore``.

        Most candidate fields come back NULL — this returns identity and a
        score, nothing more, so master data still has to be fetched. When
        more than one candidate scores high the AMBIGUITY IS THE FINDING:
        the caller surfaces it rather than auto-picking, because picking the
        wrong company silently audits the wrong business.
        """
        params: dict[str, Any] = {"q": query, "limit": limit}
        if state:
            params["state"] = state
        if city:
            params["city"] = city
        response = self._call("GET", "/v1/companies/resolve", paisa=READ_PAISA, params=params)
        return self._data(response).get("candidates", []) or []

    def company_master(self, cin: str) -> dict:
        """Master data: status, capital, address, directors, charges — one call."""
        response = self._call(
            "GET", f"/v1/companies/{cin}", paisa=READ_PAISA, params={"idType": "cin"}
        )
        return self._data(response)

    def filings(
        self, cin: str, *, form_id: str = "", year: int | None = None,
        limit: int = 50, page: int = 1,
    ) -> tuple[list[dict], dict]:
        """Filing history. Returns (rows, pagination).

        ``data`` is a BARE ARRAY here — unlike every other endpoint — and
        pagination lives in ``meta``. The server may cap ``limit`` below what
        was asked, so the caller gets ``meta`` back to read the real value
        rather than assuming its own request was honoured.
        """
        params: dict[str, Any] = {"limit": limit, "page": page}
        if form_id and form_id != "All forms":
            params["formId"] = form_id
        if year:
            params["year"] = year
        response = self._call(
            "GET", f"/v1/companies/{cin}/filings", paisa=READ_PAISA, params=params
        )
        payload = response.payload
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        rows = rows if isinstance(rows, list) else []

        # Form IDs come back spelled "ADT - 1", not "ADT-1", so an empty
        # filtered result is ambiguous: never filed, or spelling mismatch?
        # Those differ by a compliance finding, so refetch unfiltered
        # (₹5) and filter locally rather than reporting the ambiguity.
        if form_id and form_id != "All forms":
            wanted = normalise_form_id(form_id)
            if not rows:
                logger.info(
                    "%s: formId=%r returned no rows; refetching unfiltered to "
                    "distinguish 'never filed' from a spelling mismatch",
                    cin, form_id,
                )
                retry = self._call(
                    "GET", f"/v1/companies/{cin}/filings", paisa=READ_PAISA,
                    params={"limit": limit, "page": page},
                )
                payload = retry.payload
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                rows = rows if isinstance(rows, list) else []
                meta = payload.get("meta", meta) if isinstance(payload, dict) else meta
            rows = [
                r for r in rows
                if isinstance(r, dict)
                and normalise_form_id(r.get("formId") or r.get("formType")) == wanted
            ]
        return rows, meta

    def download_filing(self, cin: str, filing_id: str) -> bytes:
        """Raw document bytes. Not JSON. Company must be unlocked."""
        response = self._call(
            "GET",
            f"/v1/companies/{cin}/filings/{filing_id}/download",
            paisa=CHEAP_PAISA,
            binary=True,
        )
        return response.content or b""

    def refresh_filings(self, cin: str) -> dict:
        """₹5 filings-only refresh, with its own ~6h cooldown.

        ``fromCache: true`` means you were billed and served the cache — no
        fresh MCA pull happened. The caller must check ``cooldownUntil``
        before calling rather than discovering this after paying.
        """
        response = self._call(
            "POST", f"/v1/companies/{cin}/filings/refresh", paisa=FILINGS_REFRESH_PAISA
        )
        return self._data(response)

    # --- extractions: a THREE-step drill-down ------------------------

    def extraction_form_types(self, cin: str) -> list[str]:
        """Step 1. Absence of AOC-4 means no financials exist at all.

        That is a coverage gap to report, not an error to raise. Note the
        ``?formType=`` query parameter has NO effect — the drill-down is by
        path segment only.
        """
        response = self._call("GET", f"/v1/companies/{cin}/extractions", paisa=CHEAP_PAISA)
        return self._data(response).get("availableFormTypes", []) or []

    def extraction_years(self, cin: str, form_type: str) -> list[int]:
        """Step 2. Years come back DESCENDING, and gaps are a real signal.

        A missing year is a compliance finding — diff against the
        incorporation year rather than taking the max.
        """
        response = self._call(
            "GET", f"/v1/companies/{cin}/extractions/{form_type}", paisa=CHEAP_PAISA
        )
        return self._data(response).get("availableYears", []) or []

    def extraction(
        self, cin: str, form_type: str, year: int, *, scope: str = "standalone"
    ) -> dict:
        """Step 3. XBRL triples. Company must be unlocked.

        ``scope`` materially changes the numbers, so it travels with the
        result and is stated in the report.
        """
        response = self._call(
            "GET",
            f"/v1/companies/{cin}/extractions/{form_type}/{year}",
            paisa=CHEAP_PAISA,
            params={"scope": scope},
        )
        return self._data(response)

    def latest_financials(
        self, cin: str, *, form_type: str = "AOC-4", year: int | None = None,
        scope: str = "standalone",
    ) -> dict | None:
        """Walk all three extraction steps and return the newest filing.

        Returns None when the form type is not available at all — which is a
        gap to report, not a failure.
        """
        available = self.extraction_form_types(cin)
        if form_type not in available:
            logger.info("%s: %s not among available form types %s", cin, form_type, available)
            return None

        years = self.extraction_years(cin, form_type)
        if not years:
            return None

        target = year if year in years else max(years)
        data = self.extraction(cin, form_type, target, scope=scope)
        data["_requested_year"] = year
        data["_resolved_year"] = target
        data["_available_years"] = years
        data["_year_gaps"] = self.year_gaps(years)
        return data

    @staticmethod
    def year_gaps(years: list[int]) -> list[int]:
        """Missing years between the earliest and latest filed.

        A gap is a compliance signal, not an error — a company that filed in
        2022 and 2024 but not 2023 has a story worth asking about.
        """
        if len(years) < 2:
            return []
        ordered = sorted(years)
        return [y for y in range(ordered[0], ordered[-1] + 1) if y not in set(ordered)]

    # --- unlock: GET is free, POST costs ₹220 ------------------------

    def unlock_status(self, cin: str) -> UnlockStatus:
        """FREE status check. ALWAYS call this before POSTing an unlock."""
        response = self._call("GET", f"/v1/companies/{cin}/unlock")
        data = self._data(response)

        zips: list[str] = []
        stages = dig(data, "job", "processingStages", default={}) or {}
        for stage in stages.values() if isinstance(stages, dict) else []:
            if isinstance(stage, dict):
                for zf in stage.get("zipFiles", []) or []:
                    if isinstance(zf, dict) and zf.get("blob_url"):
                        zips.append(zf["blob_url"])

        return UnlockStatus(
            unlocked=as_bool(data.get("unlocked")),
            unlocked_at=data.get("unlockedAt"),
            expires_at=data.get("expiresAt"),
            unlock_price_paisa=data.get("unlockPrice"),
            sandbox=as_bool(data.get("sandbox")),
            zip_urls=zips,
        )

    def unlock_company(self, cin: str) -> UnlockStatus:
        """₹330, once per company per year. Never call without the GET first.

        A ``sandbox: true`` response has null timestamps and no job — the
        call succeeded but nothing was really unlocked. Treated as a sandbox
        limitation rather than a success, so test runs cannot be mistaken
        for proof the live path works.
        """
        response = self._call(
            "POST", f"/v1/companies/{cin}/unlock", paisa=COMPANY_UNLOCK_PAISA
        )
        data = self._data(response)
        status = UnlockStatus(
            unlocked=as_bool(data.get("unlocked")),
            unlocked_at=data.get("unlockedAt"),
            expires_at=data.get("expiresAt"),
            unlock_price_paisa=data.get("unlockPrice"),
            sandbox=as_bool(data.get("sandbox")),
        )
        if status.sandbox:
            logger.warning(
                "%s: unlock returned sandbox:true — no real unlock occurred", cin
            )
        return status

    def ensure_unlocked(self, cin: str) -> tuple[UnlockStatus, bool]:
        """GET first; only POST when genuinely needed. Returns (status, paid).

        The cap is compared against the price the API QUOTES (unlockPrice
        in the free status response), not against COMPANY_UNLOCK_PAISA.
        A local constant can go stale — this one did, at 22000 against a
        real 33000, so a ₹250 cap waved a ₹330 charge through.
        """
        status = self.unlock_status(cin)
        if status.unlocked and status.expires_at:
            return status, False

        quoted = status.unlock_price_paisa
        price = int(quoted) if isinstance(quoted, (int, float)) and quoted > 0 else COMPANY_UNLOCK_PAISA
        source = "quoted by the API" if price == quoted else "from the local price table"

        if price > self.settings.company_unlock_paisa_cap:
            raise RuntimeError(
                f"Company unlock costs {price} paisa ({source}), above the "
                f"configured cap of {self.settings.company_unlock_paisa_cap}. "
                f"Raise VBC_COMPANY_UNLOCK_PAISA_CAP deliberately if this is "
                f"expected — the cap exists so a price rise cannot be paid "
                f"silently."
            )
        if price != COMPANY_UNLOCK_PAISA:
            logger.warning(
                "%s: unlock quoted at %d paisa but the local price table says "
                "%d — the rate card has changed; update the constants.",
                cin, price, COMPANY_UNLOCK_PAISA,
            )
        return self.unlock_company(cin), True

    # --- async company update ---------------------------------------

    def trigger_update(self, cin: str) -> dict:
        """₹150, charged at trigger. Returns immediately with status pending.

        The data is NOT fresh when this returns. Poll before reading master
        data, or you read the stale values you just paid to replace.
        """
        response = self._call(
            "POST", f"/v1/companies/{cin}/update", paisa=COMPANY_UPDATE_PAISA
        )
        return self._data(response)

    def update_status(self, cin: str) -> dict:
        """Free to poll. NOTE: this response has no ``meta`` object."""
        response = self._call("GET", f"/v1/companies/{cin}/update/status")
        return self._data(response)

    # =================================================================
    # Directors
    # =================================================================

    def resolve_director(self, query: str, *, limit: int = 10) -> list[dict]:
        """Name → DIN.

        ``totalDirectorshipCount`` is a free red-flag metric: an unusually
        high count is the classic mass-director / dummy-director pattern.
        """
        response = self._call(
            "GET", "/v1/directors/resolve", paisa=READ_PAISA,
            params={"q": query, "limit": limit},
        )
        return self._data(response).get("candidates", []) or []

    def director_profile(self, din: str) -> dict:
        """Full directorship history. ``cessationDate: null`` = still serving.

        Dates here are ISO while company master uses DD/MM/YYYY. Also
        returns gender, nationality and qualification — decide deliberately
        whether those belong in a client-facing report.
        """
        response = self._call("GET", f"/v1/directors/{din}", paisa=READ_PAISA)
        return self._data(response)

    def director_contact(self, din: str) -> dict:
        """Mobile is returned MASKED. Requires a ₹50 director unlock.

        Said ₹10 here until 12 Sep 2026. DIRECTOR_UNLOCK_PAISA and the
        pricing table both say 5_000 paisa, and test_pricing pins it — so
        the number in this docstring was the only wrong one."""
        response = self._call("GET", f"/v1/directors/{din}/contact", paisa=CHEAP_PAISA)
        return self._data(response)

    def director_unlock_status(self, din: str) -> dict:
        response = self._call("GET", f"/v1/directors/{din}/unlock")
        return self._data(response)

    def ensure_director_unlocked(self, din: str) -> tuple[dict, bool]:
        status = self.director_unlock_status(din)
        if as_bool(status.get("unlocked")):
            return status, False
        response = self._call(
            "POST", f"/v1/directors/{din}/unlock", paisa=DIRECTOR_UNLOCK_PAISA
        )
        return self._data(response), True

    # NOTE: director update endpoints are deliberately NOT wrapped. Both
    # return {"stub": true} with HTTP 200, so any wrapper would report a
    # successful no-op. Refresh director data via the company update.

    # =================================================================
    # Account
    # =================================================================

    def account_usage(self) -> dict:
        """Wallet balance and 30-day spend by endpoint. Free.

        The only place real unit prices can be derived — divide spendPaisa
        by calls per endpoint.
        """
        response = self._call("GET", "/v1/account/usage")
        return self._data(response)


# =====================================================================
# Normalisers — payload to finding
# =====================================================================


def normalise_form_id(value: Any) -> str:
    """"ADT - 1", "ADT-1", "adt 1" all compare equal.

    The MCA form ID is spelled differently by different endpoints and the
    difference is pure whitespace and punctuation, never meaning.
    """
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def normalise_master(data: dict) -> dict:
    """Flatten master data into the facts the scoring engine needs."""
    company = dig(data, "masterData", "companyData", default={}) or {}
    # commonData is a second, cleaner projection of the same company in the
    # same response: ISO dates, real booleans, and the status. Preferred.
    common = dig(data, "masterData", "commonData", default={}) or {}

    addresses = company.get("MCAMDSCompanyAddress", []) or []
    registered = next(
        (a for a in addresses if a.get("addressType") == "Registered Address"),
        addresses[0] if addresses else {},
    )
    result = {
        "cin": data.get("cin") or company.get("CIN"),
        "company": data.get("company") or common.get("company_name"),
        # No "companyStatus" in companyData — it is commonData.status.
        "status": common.get("status") or company.get("companyStatus"),
        "class_of_company": company.get("classOfCompany") or common.get("class_of_company"),
        "company_type": company.get("companyType") or common.get("company_type"),
        "listed": company.get("whetherListedOrNot"),
        # ISO from commonData when present; the slashed form is MM/DD/YYYY.
        "incorporated_on": (
            parse_date(common.get("date_of_incorporation"))
            or parse_date(company.get("dateOfIncorporation"))
        ),
        # paidUpCapital, capital U. Both capitals are STRINGS.
        "authorised_capital": as_int(
            company.get("authorisedCapital") or common.get("authorised_capital")
        ),
        "paidup_capital": as_int(
            company.get("paidUpCapital")
            or company.get("paidupCapital")
            or common.get("paid_up_capital")
        ),
        "last_agm_on": parse_date(common.get("agm_date") or company.get("dateOfLastAGM")),
        "balance_sheet_on": parse_date(
            common.get("balance_sheet_date") or company.get("balanceSheetDate")
        ),
        "active_compliance": company.get("activeCompliance"),
        "registered_address": registered.get("streetAddress") or common.get("address_line1"),
        "registered_city": registered.get("city") or common.get("city"),
        "registered_state": registered.get("state") or common.get("state"),
        # mainDivisionDescription lives in companyData, NOT commonData.
        # commonData carries the finer-grained NIC description instead.
        "nic_division": (
            company.get("mainDivisionDescription")
            or common.get("nic_primary_description")
        ),
        "director_count": common.get("number_of_directors"),
        "small_company": as_bool(common.get("small_company_flag") or company.get("smallCompanyFlag")),
        # A non-empty history means the company was renamed or re-registered
        # — a finding in itself, not noise.
        "cin_history": data.get("cinHistory", []) or [],
        "name_history": data.get("nameHistory", []) or [],
    }

    # Drive SCAN S1, SCAN S2 and risk rule r1.
    guard = ParseGuard("filesure.master")
    guard.expect("status", raw=company or common, parsed=result["status"],
                 hint="commonData.status (NOT companyData.companyStatus) · risk rule r1")
    guard.expect("class_of_company", raw=company or common, parsed=result["class_of_company"],
                 hint="companyData.classOfCompany or commonData.class_of_company · SCAN S1")
    guard.expect_any("incorporated_on",
                     raw=company.get("dateOfIncorporation") or common.get("date_of_incorporation"),
                     parsed=[result["incorporated_on"]],
                     hint="commonData.date_of_incorporation (ISO) or "
                          "companyData.dateOfIncorporation (MM/DD/YYYY) · SCAN S2 vintage")
    guard.raise_if_gaps(payload=data)
    return result


def normalise_directors(data: dict) -> list[dict]:
    """directorData is PascalCase and its booleans are strings."""
    rows = dig(data, "masterData", "directorData", default=[]) or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        first = (row.get("FirstName") or "").strip()
        middle = (row.get("MiddleName") or "").strip()
        last = (row.get("LastName") or "").strip()
        name = " ".join(p for p in (first, middle, last) if p and p != ".")
        din = (row.get("DIN") or "").strip()

        # Placeholder rows: DIN "", names ".", appointment 01/01/1900,
        # rows whose "DIN" is a PAN, and the company itself as an "FO User".
        # A live payload had 15 rows for a board of 6. Dropped, not counted.
        if not name or not din or len(din) != 8 or not din.isdigit():
            continue

        roles = row.get("MCAUserRole", []) or []
        roles = [r for r in roles if isinstance(r, dict)]

        # cessationDate and isDisqualified live INSIDE MCAUserRole, one
        # entry per directorship — not on the director row. The row carries
        # only the older "DirectorDisqualified".
        # Company master nests these in MCAUserRole; the director profile
        # endpoint puts them on the row. Both shapes are live.
        cessations = [r.get("cessationDate") for r in roles]
        if "cessationDate" in row:
            cessations.append(row.get("cessationDate"))
        still_serving = (not cessations) or any(is_blank(c) for c in cessations)
        ceased = next((parse_date(c) for c in cessations if not is_blank(c)), None)

        out.append(
            {
                "din": din,
                "pan": row.get("PAN"),
                "name": name,
                "designations": sorted({
                    str(r.get("designation")) for r in roles if r.get("designation")
                }),
                "other_companies": sorted({
                    str(r.get("companyName")) for r in roles
                    if r.get("companyName") and r.get("cin") != data.get("cin")
                }),
                "appointed_on": parse_date(row.get("dateOfAppointment")),
                # Two encodings in the wild: the documented
                # "DirectorDisqualified": "true"/"false" and the real
                # "isDisqualified": "Y"/"N". Both are strings, so both must
                # go through as_bool — "false" is truthy in Python.
                # Disqualified on ANY directorship disqualifies the person.
                # Checked across every role, then the row-level flag.
                "disqualified": (
                    any(as_bool(r.get("isDisqualified")) for r in roles)
                    or as_bool(row.get("isDisqualified"))
                    or as_bool(row.get("DirectorDisqualified"))
                ),
                "ceased_on": ceased,
                "still_serving": still_serving,
                "roles": roles,
            }
        )


    guard = ParseGuard("filesure.directors")
    # Compared against rows that LOOK like real people, so a payload of
    # nothing but MCA placeholder rows is reported as "no directors on
    # file" rather than as a parse failure.
    real_rows = [
        r for r in rows
        if isinstance(r, dict)
        and (r.get("FirstName") or r.get("LastName") or "").strip() not in ("", ".")
    ]
    guard.expect("din", raw=real_rows, parsed=[d["din"] for d in out if d["din"]],
                 hint="masterData.directorData[].DIN (8 digits)")
    guard.expect("name", raw=real_rows, parsed=[d["name"] for d in out if d["name"]],
                 hint="masterData.directorData[].FirstName / .MiddleName / .LastName")
    # Two field names so far. Neither present = not reading the flag.
    guard.expect_any(
        "disqualification flag",
        raw=rows,
        parsed=[
            any(
                r.get("DirectorDisqualified") is not None
                or r.get("isDisqualified") is not None
                or any(
                    role.get("isDisqualified") is not None
                    for role in (r.get("MCAUserRole") or [])
                    if isinstance(role, dict)
                )
                for r in rows if isinstance(r, dict)
            )
            or None
        ],
        hint="DirectorDisqualified or isDisqualified on the row (director "
             "profile shape), or isDisqualified inside MCAUserRole[] "
             "(company master shape)",
    )
    guard.raise_if_gaps(payload=data)
    return out


def normalise_charges(data: dict) -> dict:
    """dateOfSatisfaction is null for an OPEN charge — the headline fact."""
    rows = dig(data, "masterData", "indexChargesData", default=[]) or []
    open_charges, closed_charges = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        satisfied_on = parse_date(row.get("dateOfSatisfaction"))
        status = str(row.get("chargeStatus") or "").strip().lower()
        charge = {
            "charge_id": row.get("chargeId"),
            "srn": row.get("SRN"),
            # "chargeAmount" does not exist. The field is "amount", and it
            # is a STRING.
            "amount": as_int(row.get("amount") or row.get("chargeAmount")),
            "holder": row.get("chName") or row.get("chargeHolderName"),
            "created_on": parse_date(row.get("dateOfCreation")),
            "modified_on": parse_date(row.get("dateOfModification")),
            "satisfied_on": satisfied_on,
            "status": row.get("chargeStatus"),
        }

        # An OPEN charge carries dateOfSatisfaction "" — an empty string,
        # not null. Classifying on `is None` filed every open charge as
        # satisfied: on the company that revealed this, nine live charges
        # worth ~₹730 Cr would have read as cleared. chargeStatus states it
        # outright, so that wins and the date is only a fallback.
        if status == "open":
            is_open = True
        elif status == "closed":
            is_open = False
        else:
            is_open = satisfied_on is None
        (open_charges if is_open else closed_charges).append(charge)
    result = {
        "open": open_charges,
        "closed": closed_charges,
        # as_int above means this adds rather than concatenating.
        "open_total": sum(c["amount"] or 0 for c in open_charges),
        "closed_total": sum(c["amount"] or 0 for c in closed_charges),
    }

    # No charges is a clean result and passes (raw block is empty too).
    # Rows present but unparsed amounts is the failure worth catching.
    guard = ParseGuard("filesure.charges")
    all_charges = open_charges + closed_charges
    guard.expect("charge_id", raw=rows,
                 parsed=[c["charge_id"] for c in all_charges if c["charge_id"]],
                 hint="masterData.indexChargesData[].chargeId")
    guard.expect("amount", raw=rows,
                 parsed=[c["amount"] for c in all_charges if c["amount"] is not None],
                 hint="masterData.indexChargesData[].amount (a STRING)")
    guard.raise_if_gaps(payload=data)
    return result


#: XBRL PREFIXES SEEN IN THE WILD.
#:
#: The reference document showed ``in-ca:``. A real AOC-4 extraction returns
#: ``ind-as:`` (taxonomy_id "ind-as-2017") — Ind AS filers, which is most of
#: the corporate universe. Reading only "in-ca:" gave revenue=None and
#: net_worth=None on a company that had filed perfectly good financials:
#: SCAN N3 could never rate, and risk rule r3 could never fire.
#:
#: So every lookup here is by LOCAL NAME, prefix stripped. Both taxonomies
#: use the same local names for the figures we need.
XBRL_PREFIXES = ("ind-as:", "in-ca:", "in-bse:")


def local_name(qname: str) -> str:
    """Strip the taxonomy prefix: "ind-as:Equity" -> "Equity"."""
    text = str(qname or "")
    return text.split(":", 1)[1] if ":" in text else text


#: LOCAL NAME → human label. Never assume a name is present.
XBRL_LABELS: dict[str, str] = {
    "RevenueFromOperations": "Revenue from operations",
    "OtherIncome": "Other income",
    "ProfitBeforeTax": "Profit before tax",
    "ProfitLossForPeriod": "Profit for the period",
    "Equity": "Equity / net worth",
    "NetWorthOfCompany": "Net worth (as reported)",
    "Assets": "Total assets",
    "Liabilities": "Total liabilities",
    "CashFlowsFromUsedInOperatingActivities": "Operating cash flow",
    "CashFlowsFromUsedInInvestingActivities": "Investing cash flow",
    "CashFlowsFromUsedInFinancingActivities": "Financing cash flow",
}

#: Net worth, in order of preference. A real payload carries BOTH
#: ``ind-as:Equity`` and ``in-ca:NetWorthOfCompany`` with the same value;
#: Equity is the computed statutory figure, so it wins.
NET_WORTH_NAMES = ("Equity", "NetWorthOfCompany")
REVENUE_NAMES = ("RevenueFromOperations",)


def normalise_financials(data: dict) -> dict:
    """XBRL triples into named figures. Values are raw rupees.

    This endpoint alone uses snake_case. A qname that is not present is
    simply absent from the result — never defaulted to zero, which would
    turn missing data into a reported figure of nil.
    """
    figures: dict[str, dict] = {}
    #: local name -> the figure, so lookups do not depend on the taxonomy.
    by_name: dict[str, dict] = {}
    for section in ("balance_sheet", "profit_and_loss", "cash_flow"):
        for triple in data.get(section, []) or []:
            if not isinstance(triple, dict):
                continue
            qname = triple.get("qname")
            if not qname:
                continue
            name = local_name(qname)
            figure = {
                "label": XBRL_LABELS.get(name, name),
                "value": triple.get("value"),
                "unit": triple.get("unit", "INR"),
                "section": section,
                # The qname is kept verbatim so a report can cite exactly
                # which taxonomy element the number came from.
                "qname": qname,
            }
            figures[qname] = figure
            # First prefix wins; both taxonomies carry the same value when
            # a figure appears twice, and XBRL_PREFIXES states the order.
            by_name.setdefault(name, figure)

    def _first(names: tuple[str, ...]):
        for name in names:
            value = dig(by_name, name, "value")
            if value is not None:
                return value
        return None

    revenue = _first(REVENUE_NAMES)
    equity = _first(NET_WORTH_NAMES)

    # Triples came back and were paid for. Neither figure parsing means an
    # unknown taxonomy, not a company that reported nothing.
    guard = ParseGuard("filesure.financials")
    guard.expect_any(
        "revenue / net worth",
        raw=figures,
        parsed=[revenue, equity],
        hint=f"looked for {REVENUE_NAMES + NET_WORTH_NAMES} under any prefix; "
             f"saw {sorted(by_name)[:8]}",
    )
    guard.raise_if_gaps(payload=data)
    return {
        # scope is stated because standalone vs consolidated changes the
        # numbers materially.
        "scope": data.get("filing_scope"),
        "period_start": data.get("period_start"),
        "period_end": data.get("period_end"),
        "taxonomy": data.get("taxonomy_id"),
        # metadata.source carries "filingDate" (ISO) in a real response, not
        # the documented "dateOfFiling". Both are read so this works either
        # way; parse_ddmmyyyy passes ISO through untouched.
        "filed_on": parse_date(
            dig(data, "metadata", "source", "filingDate")
            or dig(data, "metadata", "source", "dateOfFiling")
        ),
        "year": data.get("_resolved_year") or dig(data, "metadata", "source", "year"),
        "available_years": data.get("_available_years", []),
        "year_gaps": data.get("_year_gaps", []),
        "figures": figures,
        "revenue": revenue,
        "net_worth": equity,
        "positive_net_worth": (equity is not None and equity > 0),
    }
