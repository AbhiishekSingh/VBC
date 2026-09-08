"""FinAGG GSP adapter — GST, via the two consent-free Common APIs.

WHY ONLY TWO ENDPOINTS
----------------------
FinAGG exposes thirteen endpoints across three sections. Eleven of them —
every Taxpayer API and both File Download calls — sit behind
``POST /taxpayerapi/{v}/authenticate``, which authenticates AS THE TAXPAYER
using an OTP sent to their registered mobile number.

That is unusable here, and not for a technical reason. VBC assesses a third
party who has not consented to the audit and will not be forwarding anyone
an OTP. An integration that depends on the subject's cooperation is not due
diligence. So the OTP-gated endpoints are deliberately NOT implemented —
not stubbed, not commented out, absent — and this module carries no auth
token, no ``app_key`` encryption and no session state.

What remains is enough:

  ``GET /commonapi/{v}/search``    → C1, C3, C4, C5
  ``GET /commonapi/{v}/returns``   → C2

Two calls, no consent, the whole Compliance pillar.

FIELD NAMES
-----------
FinAGG's published documentation promises only "legal name, trade name, and
registration status" and does not enumerate the response. The field names
below are the standard GSTN contract that GSPs wrap (``sts``, ``dty``,
``ctb``, ``pradr``), and every one of them is read through a tolerant
lookup that also accepts a wrapped envelope.

If FinAGG's shape differs, ParseGuard turns that into ``unavailable`` with
the payload attached, rather than a clean-looking empty result. That is the
same inversion the rest of this package uses: an adapter that reads nothing
out of a non-empty payload is assumed to be out of date, not to have found
nothing.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone

from app.config import Settings
from app.providers.base import (
    HttpProvider,
    NotConfigured,
    ParseGuard,
    Spend,
    dig,
    is_blank,
)

logger = logging.getLogger(__name__)

#: Actions on the two Common endpoints. Documented for search; the returns
#: action follows the GSTN contract and is the first thing to check if the
#: call comes back 400.
ACTION_SEARCH = "SEARCHGSTIN"
ACTION_RETURNS = "RETTRACK"

#: A GSTIN is 15 characters: 2 state code, 10 PAN, 1 entity, 1 Z, 1 check.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

#: GSTN registration status values, lowercased for comparison.
STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_CANCELLED = "cancelled"

#: ``pradr.addr.ntr`` — nature of business at the principal place. Its
#: presence is the only commercial-vs-residential signal GSTN offers, and
#: it is a weak one. When it is absent or unrecognised, C5 is left UNSET
#: for an analyst rather than guessed at.
COMMERCIAL_MARKERS = (
    "office", "factory", "manufactur", "warehouse", "depot", "godown",
    "retail", "wholesale", "shop", "showroom", "supplier", "service",
    "export", "import", "works", "leasing", "recipient",
)


class FinaggProvider(HttpProvider):
    """The two GST endpoints that need no taxpayer consent."""

    name = "finagg"

    def __init__(self, settings: Settings | None = None, client=None,
                 spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()

    # -----------------------------------------------------------------

    def _require_key(self) -> None:
        if not self.settings.finagg_configured:
            raise NotConfigured(
                "FinAGG GSP has no API key configured. Set VBC_FINAGG_API_KEY. "
                "Until then GST checks report not_configured — which is not the "
                "same as a vendor having no GST registration."
            )

    def _url(self, path: str) -> str:
        return (
            f"{self.settings.finagg_base_url.rstrip('/')}"
            f"/{self.settings.finagg_version}/commonapi"
            f"/{self.settings.finagg_gsp_version}/{path}"
        )

    def _headers(self) -> dict:
        return {"x-api-key": self.settings.finagg_api_key}

    # -----------------------------------------------------------------
    # C1, C3, C4, C5
    # -----------------------------------------------------------------

    def search_gstin(self, gstin: str) -> dict:
        """Registration status, taxpayer type, constitution, address.

        One call, four Compliance parameters. Needs no consent because
        GSTN publishes this data — it is the same record the public GST
        portal search returns.
        """
        self._require_key()
        gstin = (gstin or "").strip().upper()
        if not GSTIN_RE.match(gstin):
            raise ValueError(
                f"'{gstin}' is not a valid GSTIN. Expected 15 characters: "
                f"2-digit state code, PAN, entity number, Z, check digit."
            )

        response = self.request(
            "GET",
            self._url("search"),
            headers=self._headers(),
            params={"action": ACTION_SEARCH, "gstin": gstin},
        )
        self.spend.record("finagg.search", paisa=self.settings.finagg_search_paisa)

        payload = response.payload or {}
        data = _unwrap(payload)

        status_raw = _first(data, "sts", "status", "gstinStatus")
        taxpayer_type = _first(data, "dty", "taxpayerType", "dealerType")
        address_block = _first(data, "pradr", "principalAddress") or {}

        guard = ParseGuard("finagg.search")
        guard.expect(
            "registration status", raw=data, parsed=status_raw,
            hint="sts · feeds C1 and C4, and both GST risk rules",
        )
        guard.expect_any(
            "legal name", raw=data,
            parsed=[_first(data, "lgnm", "legalName"),
                    _first(data, "tradeNam", "tradeName")],
            hint="lgnm / tradeNam · identity match against the vendor record",
        )
        guard.raise_if_gaps(payload=payload)

        status = str(status_raw or "").strip().lower()
        address = _flatten_address(address_block)

        return {
            "gstin": gstin,
            "status": status_raw,
            "is_active": status == STATUS_ACTIVE,
            "is_suspended": status == STATUS_SUSPENDED,
            "is_cancelled": status == STATUS_CANCELLED,
            "taxpayer_type": taxpayer_type,
            "is_composition": "compos" in str(taxpayer_type or "").lower(),
            "legal_name": _first(data, "lgnm", "legalName"),
            "trade_name": _first(data, "tradeNam", "tradeName"),
            "constitution": _first(data, "ctb", "constitutionOfBusiness"),
            "registered_on": _iso(_first(data, "rgdt", "registrationDate")),
            "cancelled_on": _iso(_first(data, "cxdt", "cancellationDate")),
            "nature_of_business": _nature(address_block),
            "premises_kind": _premises_kind(address_block),
            "address": address,
            "state_jurisdiction": _first(data, "stj", "stateJurisdiction"),
            "centre_jurisdiction": _first(data, "ctj", "centreJurisdiction"),
        }

    # -----------------------------------------------------------------
    # C2
    # -----------------------------------------------------------------

    def returns_metadata(self, gstin: str, *, fy: str | None = None) -> dict:
        """Which returns were filed, for which periods, and when.

        This is the public filing-status track — no consent, no OTP. It
        carries filing dates but no invoice data, which is exactly the
        depth C2 needs and no more.
        """
        self._require_key()
        gstin = (gstin or "").strip().upper()
        if not GSTIN_RE.match(gstin):
            raise ValueError(f"'{gstin}' is not a valid GSTIN.")
        fy = fy or _current_fy()

        response = self.request(
            "GET",
            self._url("returns"),
            headers=self._headers(),
            params={"action": ACTION_RETURNS, "gstin": gstin, "fy": fy},
        )
        self.spend.record("finagg.returns", paisa=self.settings.finagg_returns_paisa)

        payload = response.payload or {}
        data = _unwrap(payload)
        rows = _return_rows(data)

        guard = ParseGuard("finagg.returns")
        guard.expect(
            "filed returns", raw=data, parsed=rows,
            hint="EFiledlist / returns · feeds C2 filing status",
        )
        guard.raise_if_gaps(payload=payload)

        filings = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            period = _first(row, "ret_prd", "retPrd", "taxp", "period")
            filings.append({
                "return_type": _first(row, "rtntype", "returnType", "ret_type"),
                "period": period,
                "filed_on": _iso(_first(row, "dof", "dateOfFiling", "filedDate")),
                "arn": _first(row, "arn"),
                "status": _first(row, "status", "sts"),
                "mode": _first(row, "mof", "modeOfFiling"),
            })

        filings.sort(key=lambda f: _period_key(f["period"]), reverse=True)
        latest = filings[0] if filings else None
        months_since = _months_since(latest["period"]) if latest else None

        return {
            "gstin": gstin,
            "financial_year": fy,
            "filings": filings,
            "filing_count": len(filings),
            "latest_period": latest["period"] if latest else None,
            "latest_filed_on": latest["filed_on"] if latest else None,
            "months_since_last_filing": months_since,
            "return_types": sorted({
                f["return_type"] for f in filings if f["return_type"]
            }),
        }


# ---------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------


def _unwrap(payload):
    """Return the taxpayer object, whatever envelope it arrived in.

    GSPs wrap the GSTN body inconsistently — sometimes bare, sometimes
    under ``data``, sometimes double-wrapped. Trying each is cheaper than
    depending on documentation that does not describe the response at all.
    """
    if not isinstance(payload, dict):
        return {}
    for key in ("data", "result", "response", "taxpayerDetails"):
        inner = payload.get(key)
        if isinstance(inner, dict) and inner:
            # One more level: {"data": {"data": {...}}} happens.
            for nested in ("data", "result"):
                deeper = inner.get(nested)
                if isinstance(deeper, dict) and deeper:
                    return deeper
            return inner
    return payload


def _first(source, *keys, default=None):
    """First key present and non-blank. Case variations are common."""
    if not isinstance(source, dict):
        return default
    for key in keys:
        if key in source and not is_blank(source[key]):
            return source[key]
        # GSPs vary the casing of the same GSTN field.
        for actual, value in source.items():
            if actual.lower() == key.lower() and not is_blank(value):
                return value
    return default


def _nature(address_block) -> list[str]:
    """``pradr.addr.ntr`` — nature of business at the principal place."""
    if not isinstance(address_block, dict):
        return []
    raw = _first(address_block, "ntr", "natureOfBusiness")
    if raw is None:
        raw = dig(address_block, "addr", "ntr")
    if is_blank(raw):
        return []
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if not is_blank(v)]
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _premises_kind(address_block) -> str | None:
    """Commercial, or unknown. Never 'residential' by inference.

    GSTN has no residential flag. The nature-of-business field is the only
    signal, and its ABSENCE means nothing was recorded — not that the
    premises are a home. So this returns ``"commercial"`` or ``None``, and
    C5 is left for an analyst in every other case. Guessing here would put
    an inferred fact in the sourced-findings half of the report, which is
    the one line this product does not cross.
    """
    natures = _nature(address_block)
    if not natures:
        return None
    joined = " ".join(natures).lower()
    if any(marker in joined for marker in COMMERCIAL_MARKERS):
        return "commercial"
    return None


def _flatten_address(address_block) -> str | None:
    """GSTN nests the address under ``pradr.addr`` with abbreviated keys."""
    if not isinstance(address_block, dict):
        return None
    addr = address_block.get("addr")
    if not isinstance(addr, dict):
        addr = address_block
    parts = [
        addr.get(key) for key in
        ("bno", "flno", "bnm", "st", "loc", "city", "dst", "stcd", "pncd")
    ]
    joined = ", ".join(str(p).strip() for p in parts if not is_blank(p))
    return joined or None


def _return_rows(data) -> list:
    """The filed-returns array, under whichever key it arrived."""
    if not isinstance(data, dict):
        return []
    for key in ("EFiledlist", "efiledlist", "returns", "filings", "ret"):
        rows = _first(data, key)
        if isinstance(rows, list):
            return rows
    return []


def _iso(value) -> str | None:
    """GSTN dates are DD/MM/YYYY. Unlike FileSure, this one really is."""
    if is_blank(value):
        return None
    text = str(value).strip().split(" ")[0]
    if "-" in text and len(text) >= 10:
        return text[:10]
    parts = text.split("/")
    if len(parts) != 3:
        return None
    try:
        day, month, year = (int(p) for p in parts)
    except ValueError:
        return None
    if year < 100 or not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _period_key(period) -> tuple[int, int]:
    """``ret_prd`` is MMYYYY. Sorting it as text puts December before July."""
    text = str(period or "").strip()
    if len(text) != 6 or not text.isdigit():
        return (0, 0)
    return (int(text[2:]), int(text[:2]))


def _months_since(period) -> int | None:
    year, month = _period_key(period)
    if not year:
        return None
    today = datetime.now(timezone.utc).date()
    return (today.year - year) * 12 + (today.month - month)


def _current_fy(today: date | None = None) -> str:
    """Indian financial year, April to March, as ``2025-26``."""
    today = today or datetime.now(timezone.utc).date()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"
