"""Shared provider machinery: HTTP, retries, cost tracking, error taxonomy.

THE CENTRAL RULE
----------------
A call that fails produces ``unavailable``. It never produces ``pass``, and
it never silently disappears. Three retries with backoff, then the finding
is recorded as unexamined with the reason attached. In an audit product the
difference between "we looked and it was fine" and "we could not look" is
the entire product, and it has to survive a flaky network.

PAID CALLS
----------
Every request that costs money goes through ``spend()``, which refuses when
``allow_paid_calls`` is false. That default means a misconfigured staging
box cannot spend real money against FileSure's wallet — the failure mode is
a refused call and a loud error, not a surprise invoice.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Base for anything that stops a call producing evidence."""

    #: When true, a retry might succeed.
    transient = False


class ProviderUnavailable(ProviderError):
    """The provider could not be reached, or failed after every retry."""

    transient = True


class ProviderRejected(ProviderError):
    """The provider answered, and said no — bad key, no credits, 4xx."""

    transient = False


class NotConfigured(ProviderError):
    """No credential for this provider. Not an error — a coverage gap."""

    transient = False


class PaidCallRefused(ProviderError):
    """A call that costs money, with paid calls disabled."""

    transient = False


class ProviderParseGap(ProviderError):
    """The provider answered, and this adapter could not read the answer.

    Every provider bug found against live data so far failed the same way:
    the call succeeded, the normaliser found nothing, and the check reported
    CLEAN. Every adapter here was written from a reference document, and
    every document checked against a real payload has been wrong.

    So the assumption is inverted: a normaliser that comes back empty from a
    NON-EMPTY payload means this adapter is out of date, not that there is
    nothing to find. Recorded ``unavailable``.

    Carries the payload, which the runner persists — a response we have paid
    for and cannot read is the one artefact needed to fix the adapter.
    """

    transient = False

    def __init__(self, message: str, payload: Any = None):
        super().__init__(message)
        #: The response that could not be read. May be None when the caller
        #: had nothing to hand.
        self.payload = payload


class SandboxLimitation(ProviderError):
    """The provider served a sandbox stub instead of real data.

    Distinct from a failure: the call worked, but what came back is not
    evidence about this vendor. Recorded as unavailable, never as a pass.
    """

    transient = False


@dataclass
class Spend:
    """What one run actually cost, kept in three separate currencies.

    Rupees, WhoisXML credits and screenshot credits draw on three different
    pools. Adding them produces a number that means nothing, so they never
    meet.
    """

    paisa: int = 0
    credits: int = 0
    screenshots: int = 0
    #: Wallet balance reported by the provider on the last billed call —
    #: FileSure returns it inline, which is cheaper than polling /usage.
    wallet_balance_paisa: int | None = None
    calls: list[dict] = field(default_factory=list)

    def record(self, endpoint: str, *, paisa: int = 0, credits: int = 0,
               screenshots: int = 0, wallet_after: int | None = None) -> None:
        self.paisa += paisa
        self.credits += credits
        self.screenshots += screenshots
        if wallet_after is not None:
            self.wallet_balance_paisa = wallet_after
        self.calls.append(
            {"endpoint": endpoint, "paisa": paisa, "credits": credits,
             "screenshots": screenshots}
        )


@dataclass
class ProviderResponse:
    """A raw provider answer, before any interpretation."""

    payload: Any
    status_code: int
    #: Bytes for binary endpoints (screenshots, filing PDFs).
    content: bytes | None = None
    paisa_charged: int = 0
    wallet_after: int | None = None


class HttpProvider:
    """Base class: a client, retries, and the spend guard."""

    name: str = "provider"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.settings.http_timeout_seconds,
                headers={"User-Agent": "VBC-VendorIntelligence/1.0"},
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -----------------------------------------------------------------
    # Spend guard
    # -----------------------------------------------------------------

    def guard_paid(self, endpoint: str, paisa: int) -> None:
        """Refuse a billable call unless paid calls are explicitly enabled."""
        if paisa <= 0:
            return
        if not self.settings.allow_paid_calls:
            raise PaidCallRefused(
                f"{endpoint} costs {paisa} paisa and paid calls are disabled. "
                f"Set VBC_ALLOW_PAID_CALLS=true to permit real spend."
            )

    # -----------------------------------------------------------------
    # HTTP with retry
    # -----------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        binary: bool = False,
        **kwargs: Any,
    ) -> ProviderResponse:
        """One request, retried on transient failure with exponential backoff.

        Retries on connection errors, timeouts, 429 and 5xx. Does NOT retry
        a 4xx — the provider answered and said no, and hammering it will
        not change that answer.
        """
        attempts = self.settings.http_max_retries
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self.client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt < attempts:
                    self._backoff(attempt)
                    continue
                raise ProviderUnavailable(
                    f"{self.name}: {method} {url} failed after {attempts} "
                    f"attempts — {type(exc).__name__}: {exc}"
                ) from exc

            if response.status_code == 429 or response.status_code >= 500:
                last = ProviderUnavailable(
                    f"{self.name}: HTTP {response.status_code} on {url}"
                )
                if attempt < attempts:
                    self._backoff(attempt, response)
                    continue
                raise last

            if response.status_code >= 400:
                raise ProviderRejected(
                    f"{self.name}: HTTP {response.status_code} on {url} — "
                    f"{self._error_detail(response)}"
                )

            return self._build(response, binary=binary)

        raise ProviderUnavailable(f"{self.name}: exhausted retries on {url}") from last

    def _backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        # Honour Retry-After when the provider bothers to send one.
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(min(int(retry_after), 30))
                return
        delay = self.settings.http_backoff_base_seconds * (2 ** (attempt - 1))
        logger.warning("%s: retry %d in %.1fs", self.name, attempt, delay)
        time.sleep(delay)

    def _error_detail(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except Exception:
            return response.text[:200]
        if isinstance(body, dict) and "error" in body:
            error = body["error"]
            if isinstance(error, dict):
                return f"{error.get('code', '?')}: {error.get('message', '')}"
            return str(error)[:200]
        return str(body)[:200]

    def _build(self, response: httpx.Response, *, binary: bool) -> ProviderResponse:
        if binary:
            return ProviderResponse(
                payload=None, status_code=response.status_code, content=response.content
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailable(
                f"{self.name}: response was not JSON — {response.text[:120]}"
            ) from exc
        return ProviderResponse(payload=payload, status_code=response.status_code)


# ---------------------------------------------------------------------
# Small shared helpers for the gotchas the payloads actually contain
# ---------------------------------------------------------------------


def as_bool(value: Any) -> bool:
    """FileSure returns booleans as STRINGS: "false" is not falsy in Python.

    ``DirectorDisqualified: "false"`` read with a truthiness test flags every
    director as disqualified. This is the single most dangerous gotcha in
    the whole integration.

    Live payloads also use "Y"/"N", which the reference never mentioned.
    Without "y" a DISQUALIFIED director reads as clean — a missed adverse
    finding, which is worse than a false one because nobody investigates it.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return bool(value)


def is_blank(value: Any) -> bool:
    """None and "" alike. FileSure uses both for "no value"."""
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def parse_date(value: str | None, *, prefer: str = "mdy") -> str | None:
    """Slashed dates to ISO, inferring day-first vs month-first per value.

    FileSure company master is MM/DD/YYYY, not the documented DD/MM/YYYY.
    The payload settles it by carrying both forms of the same dates:
    dateOfIncorporation "12/05/2020" alongside date_of_incorporation
    "2020-12-05". Read day-first, that company is seven months older than
    it is — straight into SCAN S2, with nothing to flag it.

    But one payload mixes both: financialYear "31/03/2024" (day-first) sits
    two keys from "03/31/2025 00:00:00" (month-first). So the order is
    inferred per value — a component above 12 can only be a day — and
    ``prefer`` decides only the genuinely ambiguous ones.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    # Already ISO (director profiles, commonData, XBRL filingDate).
    if "-" in text and len(text) >= 10:
        return text[:10]

    # Trailing clock time: "03/31/2025 00:00:00".
    text = text.split(" ")[0]
    parts = text.split("/")
    if len(parts) != 3:
        return None
    try:
        first, second, year = (int(p) for p in parts)
    except ValueError:
        return None
    if year < 100:  # two-digit years are too ambiguous to guess at
        return None

    if first > 12:
        day, month = first, second
    elif second > 12:
        month, day = first, second
    elif prefer == "dmy":
        day, month = first, second
    else:
        month, day = first, second

    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


#: The old name. Kept so nothing breaks on import, but it no longer means
#: "day first" — see parse_date, which infers the order per value.
parse_ddmmyyyy = parse_date


def as_int(value: Any) -> int | None:
    """Money and counts arrive as STRINGS. Summing them concatenates."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def has_content(value: Any) -> bool:
    """True when a value carries information. 0 and False count; "" and [] do not."""
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) > 0
    return True


class ParseGuard:
    """Detects an adapter that has fallen behind the API it reads.

    Answers one mechanical question: did the payload contain something here
    that we failed to extract? Only "raw had content, parsed did not" trips
    it, and that has one cause — a field moved, was renamed, or changed
    encoding. A company with genuinely no charges passes cleanly, because
    its raw block is empty too.

        guard = ParseGuard("filesure.master")
        guard.expect("status", raw=company, parsed=result["status"],
                     hint="commonData.status")
        guard.raise_if_gaps(payload=data)

    Gaps are collected before raising, so one run surfaces all of them.
    """

    def __init__(self, source: str):
        self.source = source
        self.gaps: list[str] = []

    def expect(self, field: str, *, raw: Any, parsed: Any, hint: str = "") -> None:
        """Record a gap when ``raw`` has content but ``parsed`` does not."""
        if has_content(raw) and not has_content(parsed):
            self.gaps.append(f"{field} ({hint})" if hint else field)

    def expect_any(self, label: str, *, raw: Any, parsed: list[Any], hint: str = "") -> None:
        """As ``expect``, but satisfied when ANY of several fields parsed.

        For alternatives that carry the same fact — revenue under either of
        two taxonomies, a creation date under any of three field names.
        """
        if has_content(raw) and not any(has_content(p) for p in parsed):
            self.gaps.append(f"{label} ({hint})" if hint else label)

    def raise_if_gaps(self, payload: Any = None) -> None:
        """Raise if anything was unreadable. Always pass ``payload`` — a
        discarded response has to be bought again to be diagnosed."""
        if not self.gaps:
            return
        fields = ", ".join(self.gaps)
        raise ProviderParseGap(
            f"{self.source}: the provider returned data, but this adapter could "
            f"not read {len(self.gaps)} field(s) from it — {fields}. The response "
            f"shape has probably changed. Recorded as unexamined rather than "
            f"clean. The response is stored with this result — open it and send "
            f"it to whoever maintains the adapter; the call does not need to be "
            f"paid for again.",
            payload=payload,
        )


def note_unknown_keys(source: str, payload: Any, known: set[str]) -> list[str]:
    """Log unknown top-level keys — the earliest signal of shape drift."""
    if not isinstance(payload, dict):
        return []
    unknown = sorted(set(payload) - known)
    if unknown:
        logger.info("%s: unrecognised response keys %s", source, unknown)
    return unknown


def dig(payload: Any, *path: str, default: Any = None) -> Any:
    """Walk nested dicts without a chain of .get() calls.

    Tolerant by design: ``/update/status`` has no ``meta`` object at all,
    and assuming one exists is a documented way to crash a poll loop.
    """
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current if current is not None else default
