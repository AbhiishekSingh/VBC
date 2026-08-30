"""WhoisXML adapter.

One API key across all products, but CREDITS ARE PER-PRODUCT POOLS, not a
single balance. The screenshot pool is the tightest thing on the platform
at ten calls, so it is guarded separately.

Documented behaviours handled here:

  * ``testResults`` is a VARIABLE-LENGTH array — iterate, never index.
  * Reverse WHOIS returns HTTP 200 with ``domainsCount: 0`` for a
    placeholder term. A successful call is not proof of a correct query.
  * WHOIS History occasionally returns a record containing only
    "Closing connections because of Timeout" — a failed lookup on their
    side, which must be filtered out before it is reported as ownership
    history.
  * SSL returns the CURRENT certificate only. It cannot evidence when
    HTTPS was first enabled, and a ~90-day window is normal auto-renewal
    rather than a red flag.
  * Screenshot returns raw JPEG bytes, not JSON.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import Settings
from app.providers.base import HttpProvider, NotConfigured, ParseGuard, Spend

logger = logging.getLogger(__name__)

WHOIS_HISTORY_URL = "https://whois-history.whoisxmlapi.com/api/v1"
DOMAIN_REPUTATION_URL = "https://domain-reputation.whoisxmlapi.com/api/v2"
SSL_CERTIFICATES_URL = "https://ssl-certificates.whoisxmlapi.com/api/v1"
REVERSE_WHOIS_URL = "https://reverse-whois.whoisxmlapi.com/api/v2"
SCREENSHOT_URL = "https://website-screenshot.whoisxmlapi.com/api/v1"

WHOIS_HISTORY_CREDITS = 50  # purchase mode; preview returns a count only
REPUTATION_CREDITS = 1
SSL_CREDITS = 1
REVERSE_WHOIS_CREDITS = 1

#: A record carrying only this text is a failed lookup on WhoisXML's side,
#: not a fact about the domain.
TIMEOUT_MARKER = "closing connections because of timeout"


class WhoisXmlProvider(HttpProvider):
    name = "whoisxml"

    def __init__(self, settings: Settings | None = None, client=None, spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()

    def _require_key(self) -> None:
        if not self.settings.whoisxml_configured:
            raise NotConfigured(
                "WhoisXML has no API key configured. Set VBC_WHOISXML_API_KEY. "
                "Until then domain checks report not_configured rather than failing."
            )

    # -----------------------------------------------------------------

    def whois_history(self, domain: str, *, mode: str = "purchase") -> dict:
        """Registrant, registrar and nameserver changes over time.

        ``purchase`` costs 50 credits and returns records; ``preview``
        returns only a count. Failed-lookup records are filtered out here so
        they never reach a report as ownership history.
        """
        self._require_key()
        credits = WHOIS_HISTORY_CREDITS if mode == "purchase" else 0
        response = self.request(
            "GET",
            WHOIS_HISTORY_URL,
            params={
                "apiKey": self.settings.whoisxml_api_key,
                "domainName": domain,
                "mode": mode,
                "outputFormat": "JSON",
            },
        )
        self.spend.record("whois-history", credits=credits)

        payload = response.payload or {}
        records = payload.get("records", []) or []
        usable = [r for r in records if _is_real_record(r)]
        dropped = len(records) - len(usable)
        if dropped:
            logger.info("whois_history(%s): dropped %d failed lookups", domain, dropped)

        return {
            "records_count": payload.get("recordsCount", len(records)),
            "records": usable,
            "dropped_failed_lookups": dropped,
            **_summarise_history(usable),
        }

    def domain_reputation(self, domain: str, *, mode: str = "fast") -> dict:
        self._require_key()
        response = self.request(
            "GET",
            DOMAIN_REPUTATION_URL,
            params={
                "apiKey": self.settings.whoisxml_api_key,
                "domainName": domain,
                "mode": mode,
            },
        )
        self.spend.record("domain-reputation", credits=REPUTATION_CREDITS)
        payload = response.payload or {}
        # Variable-length array — iterate, never index a fixed position.
        warnings = [
            {"test": t.get("test"), "warning": t.get("warningDescription")}
            for t in (payload.get("testResults") or [])
            if isinstance(t, dict) and t.get("warningDescription")
        ]
        # Zero is a REAL score (the worst), not an absence.
        guard = ParseGuard("whoisxml.reputation")
        guard.expect("score", raw=payload, parsed=payload.get("reputationScore"),
                     hint="reputationScore · feeds the domain reputation check")
        guard.raise_if_gaps(payload=payload)
        return {
            "score": payload.get("reputationScore"),
            "mode": payload.get("mode", mode),
            "warnings": warnings,
            "test_count": len(payload.get("testResults") or []),
        }

    def ssl_certificate(self, domain: str) -> dict:
        """CURRENT certificate only — there is no history behind this."""
        self._require_key()
        response = self.request(
            "GET",
            SSL_CERTIFICATES_URL,
            params={"apiKey": self.settings.whoisxml_api_key, "domainName": domain},
        )
        self.spend.record("ssl-certificates", credits=SSL_CREDITS)
        payload = response.payload or {}
        certs = payload.get("certificates", []) or []
        if not certs:
            return {"present": False}

        cert = certs[0]
        issuer = cert.get("issuer", {}) or {}
        organisation = issuer.get("organization") or ""
        subject = cert.get("subject", {}) or {}
        names = cert.get("dnsNames", []) or []
        # No issuer and no validity window is a renamed schema, not a
        # missing certificate. "No trusted CA" is a FAIL in the runner, so
        # a gap here would manufacture an adverse finding.
        guard = ParseGuard("whoisxml.ssl")
        guard.expect_any("issuer", raw=cert,
                         parsed=[organisation, issuer.get("commonName")],
                         hint="certificates[0].issuer.organization / .commonName")
        guard.expect("valid_to", raw=cert, parsed=cert.get("validTo"),
                     hint="certificates[0].validTo")
        guard.raise_if_gaps(payload=payload)
        return {
            "present": True,
            "issuer": organisation or issuer.get("commonName"),
            "valid_from": cert.get("validFrom"),
            "valid_to": cert.get("validTo"),
            "common_name": subject.get("commonName"),
            "dns_names": names,
            "wildcard": any(str(n).startswith("*.") for n in names),
            "validation_type": cert.get("validationType"),
            "key_algorithm": cert.get("keyAlgorithm"),
            "key_size": cert.get("keySize"),
            # A self-signed or untrusted certificate is the finding; a short
            # ~90-day window is normal auto-renewal and is NOT a red flag.
            "trusted_ca": bool(organisation) and "self" not in organisation.lower(),
        }

    def reverse_whois(self, term: str, *, search_type: str = "current") -> dict:
        """Other domains under the same registrant.

        A placeholder term returns 200 with ``domainsCount: 0``, so a
        successful call is not proof of a correct query — the term used is
        returned alongside the result so a reader can judge it.
        """
        self._require_key()
        if not term or not term.strip():
            return {"queried": False, "reason": "no registrant term available", "count": 0,
                    "domains": []}

        response = self.request(
            "POST",
            REVERSE_WHOIS_URL,
            json={
                "apiKey": self.settings.whoisxml_api_key,
                "searchType": search_type,
                "mode": "purchase",
                "punycode": True,
                "basicSearchTerms": {"include": [term]},
            },
        )
        self.spend.record("reverse-whois", credits=REVERSE_WHOIS_CREDITS)
        payload = response.payload or {}
        return {
            "queried": True,
            "term": term,
            "count": payload.get("domainsCount", 0),
            "domains": payload.get("domainsList", []) or [],
        }

    def screenshot(self, url: str, *, image_format: str = "JPG") -> bytes:
        """Raw JPEG bytes, not JSON. ONLY 10 free credits on the platform."""
        self._require_key()
        response = self.request(
            "GET",
            SCREENSHOT_URL,
            params={
                "apiKey": self.settings.whoisxml_api_key,
                "url": url,
                "imageOutputFormat": image_format,
            },
            binary=True,
        )
        self.spend.record("website-screenshot", screenshots=1)
        return response.content or b""


# ---------------------------------------------------------------------


#: Date fields, in the order they are actually preferred.
#:
#: The reference document showed ``createdDateNormalized``. THE LIVE API DOES
#: NOT RETURN THAT FIELD. A real response carries ``createdDateISO8601`` and
#: ``createdDateRaw`` instead. Reading only the documented name produced
#: created=None and age_years=None for every domain — which silently meant
#: the whois check could never PASS and risk rule r4 ("domain older than 2
#: years", +10) could never fire.
#:
#: All three names are tried, so this works against the live API and against
#: anything older that still uses the documented shape.
_CREATED_FIELDS = ("createdDateISO8601", "createdDateNormalized", "createdDateRaw")
_EXPIRES_FIELDS = ("expiresDateISO8601", "expiresDateNormalized", "expiresDateRaw")


def _first_date(record: dict, fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = record.get(field)
        if value:
            return str(value)
    return None


def _is_real_record(record: dict) -> bool:
    """Filter WhoisXML's own failed lookups out of ownership history.

    A record whose text is only "Closing connections because of Timeout" is
    their lookup failing, not a fact about the domain. It still carries a
    registrarName, so the marker check has to come first.
    """
    if not isinstance(record, dict):
        return False
    blob = str(record).lower()
    if TIMEOUT_MARKER in blob:
        return False
    return bool(
        record.get("registrarName")
        or record.get("registrantContact")
        or _first_date(record, _CREATED_FIELDS)
    )


def _summarise_history(records: list[dict]) -> dict:
    """Domain age and registrant continuity, the two facts that feed S3."""
    if not records:
        return {"created": None, "expires": None, "age_years": None,
                "registrant": None, "registrar_changes": 0}

    # The EARLIEST creation date across all records is the domain's real
    # birthday — later records can carry a re-registration date.
    created_values = [d for d in (_first_date(r, _CREATED_FIELDS) for r in records) if d]
    created = min(created_values) if created_values else None

    age_years = None
    if created:
        try:
            created_dt = datetime.fromisoformat(str(created)[:10]).replace(tzinfo=timezone.utc)
            age_years = (datetime.now(timezone.utc) - created_dt).days // 365
        except ValueError:
            pass

    # Records come back newest-first.
    newest = records[0]
    contact = newest.get("registrantContact", {}) or {}
    registrars = {r.get("registrarName") for r in records if r.get("registrarName")}

    # Records came back, so the domain has a history. No creation date
    # parsed means the field was renamed, not that there is no birthday.
    guard = ParseGuard("whoisxml.whois_history")
    guard.expect_any(
        "created",
        raw=records,
        parsed=[created],
        hint=f"tried {_CREATED_FIELDS} · domain age feeds SCAN S3 and rule r4",
    )
    guard.raise_if_gaps(payload={"records": records})

    return {
        "created": created,
        "expires": _first_date(newest, _EXPIRES_FIELDS),
        "age_years": age_years,
        "registrant": contact.get("organization") or contact.get("name"),
        "registrant_email": contact.get("email"),
        "registrant_country": contact.get("country"),
        # Privacy protection is common and not itself adverse, but it does
        # mean the registrant cannot corroborate the vendor's identity.
        "privacy_protected": not (contact.get("organization") or contact.get("name")),
        "registrar_changes": max(0, len(registrars) - 1),
        "registrars": sorted(r for r in registrars if r),
    }
