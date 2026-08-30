"""archive.org adapter. Free, no key, no account.

Documented behaviours handled here:

  * ``archived_snapshots`` is an EMPTY OBJECT ``{}`` when a domain was
    never archived — check for ``closest`` before reading it.
  * ``status`` is a STRING, not a number.
  * CDX returns an ARRAY OF ARRAYS with positional columns, and with
    ``output=json`` row 0 is a header row. Without
    ``filter=statuscode:200`` and ``collapse=digest`` most of what comes
    back is duplicate redirect noise.
  * Advanced Search returns millions of loose keyword hits — 2.4M for
    "google" — so it is bonus-only and every hit needs relevance checking.
  * Metadata items can carry ``access-restricted-item: true``, meaning the
    files cannot be viewed or cited as evidence.

The real value here is the OUTAGE TIMELINE. A site that returned 403 for
six weeks, or only went live last December, is a fact about the business
that no registry holds.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.providers.base import HttpProvider, ParseGuard, Spend

logger = logging.getLogger(__name__)

#: Positional columns for a CDX row. Order is fixed by the API.
CDX_COLUMNS = ("urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length")

#: How to read a CDX status code, per the archive.org evaluation report.
#:
#:   200          real page content              -> the site was up
#:   301 / 302    redirect (http->https, ->www)  -> NEUTRAL, not an outage
#:   403          crawler blocked / forbidden    -> FLAG, site inaccessible
#:   404 / 5xx    not found / server error       -> FLAG, site broken
#:
#: The 301/302 distinction matters more than it looks. Nearly every site
#: redirects http to https, so counting redirects as outages would report a
#: perfectly healthy site as intermittently down — a WRONG finding on an
#: audit report, not merely a missing one. It would also stop risk rule r5
#: ("continuous web presence, no outages", +10) from ever firing.
#:
#: Tested against the amazon.com sample in the report: 20 consecutive 302s
#: with an identical digest, which is redirect noise, not an outage.
NEUTRAL_STATUS_CODES = frozenset({"301", "302", "307", "308"})
OK_STATUS_CODES = frozenset({"200"})


def is_outage_status(code: str | None) -> bool:
    """True only for codes that mean the site was genuinely unreachable."""
    text = str(code or "").strip()
    if not text or text in OK_STATUS_CODES or text in NEUTRAL_STATUS_CODES:
        return False
    return text[0] in ("4", "5")


class ArchiveProvider(HttpProvider):
    name = "archive"

    def __init__(self, settings=None, client=None, spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()  # always zero — kept for a uniform interface

    def availability(self, domain: str, *, timestamp: str = "") -> dict:
        """Has this domain ever been archived, and when was it last seen."""
        params = {"url": domain}
        if timestamp:
            params["timestamp"] = timestamp
        response = self.request(
            "GET", f"{self.settings.archive_base_url}/wayback/available", params=params
        )
        payload = response.payload or {}
        snapshots = payload.get("archived_snapshots") or {}

        # {} means never archived. Reading it without this check is a
        # documented way to crash on a legitimate finding.
        closest = snapshots.get("closest")
        if not closest:
            return {"archived": False, "first_seen": None, "last_seen": None}

        return {
            "archived": True,
            # status is a STRING here, not an int.
            "status": str(closest.get("status", "")),
            "available": bool(closest.get("available")),
            "last_seen": _from_wayback_timestamp(closest.get("timestamp")),
            "snapshot_url": closest.get("url"),
        }

    def timeline(
        self, domain: str, *, match_type: str = "domain", limit: int = 50,
        date_from: str = "", date_to: str = "",
    ) -> dict:
        """Web presence timeline: when it went live, and any outages."""
        params = {
            "url": domain,
            "matchType": match_type,
            "output": "json",
            "collapse": "timestamp:8",
            "limit": limit,
        }
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to

        response = self.request(
            "GET", f"{self.settings.wayback_base_url}/cdx/search/cdx", params=params
        )
        rows = response.payload or []
        if not isinstance(rows, list) or not rows:
            return {"captures": 0, "first_capture": None, "last_capture": None,
                    "outages": [], "ok_captures": 0, "continuous": False}

        # Row 0 is a header when output=json.
        body = rows[1:] if rows and rows[0] and str(rows[0][0]) == "urlkey" else rows
        captures = [dict(zip(CDX_COLUMNS, row)) for row in body if isinstance(row, list)]

        ok = [c for c in captures if str(c.get("statuscode")) in OK_STATUS_CODES]
        # Only 4xx/5xx count. Redirects are normal and must not be reported
        # as downtime — see NEUTRAL_STATUS_CODES above.
        bad = [c for c in captures if is_outage_status(c.get("statuscode"))]
        redirects = [
            c for c in captures if str(c.get("statuscode")) in NEUTRAL_STATUS_CODES
        ]

        # CDX rows are POSITIONAL. A column-order change maps timestamps
        # onto statuscode and the timeline becomes plausible fiction.
        guard = ParseGuard("archive.timeline")
        guard.expect("statuscode", raw=body,
                     parsed=[c.get("statuscode") for c in captures if c.get("statuscode")],
                     hint=f"positional CDX columns {CDX_COLUMNS}")
        guard.expect("timestamp", raw=body,
                     parsed=[c.get("timestamp") for c in captures if c.get("timestamp")],
                     hint="column 1 of a CDX row · drives the outage timeline")
        guard.raise_if_gaps(payload=rows)

        return {
            "captures": len(captures),
            "ok_captures": len(ok),
            "first_capture": _from_wayback_timestamp(captures[0].get("timestamp")) if captures else None,
            "last_capture": _from_wayback_timestamp(captures[-1].get("timestamp")) if captures else None,
            "first_ok_capture": _from_wayback_timestamp(ok[0].get("timestamp")) if ok else None,
            "outages": _outage_windows(bad),
            # Reported separately so a reader can see they were considered
            # and deliberately not treated as downtime.
            "redirects": len(redirects),
            # A site with no successful captures at all has no evidenced
            # web presence, whatever its domain registration says.
            "continuous": bool(ok) and not _outage_windows(bad),
            "status_breakdown": _status_counts(captures),
        }

    def mentions(self, query: str, *, rows: int = 50) -> dict:
        """Bonus only. Millions of loose hits; every one needs relevance review."""
        response = self.request(
            "GET",
            f"{self.settings.archive_base_url}/advancedsearch.php",
            params={
                "q": query,
                "output": "json",
                "rows": rows,
                "fl[]": ["identifier", "title", "description"],
            },
        )
        payload = response.payload or {}
        found = payload.get("response", {}).get("numFound", 0)
        docs = payload.get("response", {}).get("docs", []) or []
        return {
            "found": found,
            "returned": len(docs),
            "docs": docs[:rows],
            # Said plainly so nobody reads a big number as significance.
            "note": (
                "Loose keyword matches across all uploads. A high count is "
                "not evidence of anything until each hit is relevance-checked."
            ),
        }

    def metadata(self, identifier: str) -> dict:
        """Follow-up on a search hit. Check access restriction before citing."""
        response = self.request(
            "GET", f"{self.settings.archive_base_url}/metadata/{identifier}"
        )
        payload = response.payload or {}
        meta = payload.get("metadata", {}) or {}
        return {
            "identifier": identifier,
            "title": meta.get("title"),
            "collection": meta.get("archiveit-collection-name") or meta.get("collection"),
            # True means the files cannot be shown to a client as evidence.
            "access_restricted": str(meta.get("access-restricted-item", "")).lower() == "true",
        }


# ---------------------------------------------------------------------


def _from_wayback_timestamp(value: str | None) -> str | None:
    """Wayback stamps are YYYYMMDDhhmmss. Normalise to ISO."""
    if not value:
        return None
    text = str(value)
    if len(text) < 8:
        return None
    try:
        return datetime.strptime(text[:14].ljust(14, "0"), "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return None


def _status_counts(captures: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for capture in captures:
        code = str(capture.get("statuscode") or "unknown")
        counts[code] = counts.get(code, 0) + 1
    return counts


def _outage_windows(bad: list[dict]) -> list[dict]:
    """Consecutive non-200 captures, grouped into readable windows.

    "Returned 403 for six weeks in early 2026" is a finding an analyst can
    act on; a list of 19 individual timestamps is not.
    """
    if not bad:
        return []
    windows: list[dict] = []
    current = {
        "from": _from_wayback_timestamp(bad[0].get("timestamp")),
        "to": _from_wayback_timestamp(bad[0].get("timestamp")),
        "status": str(bad[0].get("statuscode")),
        "captures": 1,
    }
    for capture in bad[1:]:
        status = str(capture.get("statuscode"))
        stamp = _from_wayback_timestamp(capture.get("timestamp"))
        if status == current["status"]:
            current["to"] = stamp
            current["captures"] += 1
        else:
            windows.append(current)
            current = {"from": stamp, "to": stamp, "status": status, "captures": 1}
    windows.append(current)
    return windows
