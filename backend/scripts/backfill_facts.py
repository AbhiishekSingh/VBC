"""Rebuild `vendor_checks.facts` from payloads already on file.

NO NETWORK. NO CREDITS. NOT ONE PAISA.

This is the property the whole facts design exists for. `facts` is a
projection of `raw_response`, so it can be thrown away and rebuilt at any
time — which means a parse defect is fixed by bumping the parser and running
this, not by re-paying a provider for data already stored. Four such defects
have been found so far (see vbc-provider-parse-guards.md); this is how the
fifth gets corrected across every historical vendor.

It is also how existing rows get a middle tier without re-running checks that
cost ₹5 to ₹330 each.

    python -m scripts.backfill_facts --dry-run          # see what would change
    python -m scripts.backfill_facts                    # every vendor
    python -m scripts.backfill_facts --vendor 234485    # just one
    python -m scripts.backfill_facts --check gst --force

By default a row is skipped when its facts are already at the current parser
version. `--force` rebuilds regardless, which is what you want after fixing a
parser without bumping PARSER_VERSION.

SAFETY
------
`raw_response` is opened read-only and never written. A row that raises is
counted, named, and skipped — one unreadable payload must not stop a
backfill of three thousand.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Vendor, VendorCheck
from app.db.session import get_engine
from app.domain.facts import PARSER_VERSION
from app.providers import factsets as fx


def _subject(vendor: Vendor | None) -> str | None:
    """The name provider answers are checked back against."""
    if vendor is None:
        return None
    return vendor.legal_name or vendor.name


def _payload(raw: dict) -> dict:
    """Some checks store {"facts": …, "payload": …}; most store the payload.

    Both shapes are in the database already, so the reader accommodates both
    rather than pretending history is tidy.
    """
    return raw.get("payload", raw) if isinstance(raw, dict) else {}


def _parsed(raw: dict) -> dict:
    """The normaliser's output, for the checks that stored it alongside."""
    return raw.get("facts", raw) if isinstance(raw, dict) else {}


#: check_id -> (raw, vendor) -> facts blob.
#:
#: Every entry unwraps the shape that check actually stored. Where a check
#: never ran on this deployment its entry is simply never called.
BUILDERS: dict[str, Callable[[dict, Any], dict]] = {
    # --- MCA ---------------------------------------------------------
    "master":     lambda r, v: fx.master(_parsed(r), subject=_subject(v)),
    "dirs":       lambda r, v: fx.directors(r.get("directors") or []),
    "dprof":      lambda r, v: fx.director_profiles(r.get("profiles") or []),
    "dresolve":   lambda r, v: fx.director_candidates(r.get("candidates") or []),
    "dcontact":   lambda r, v: fx.director_contacts(r.get("contacts") or []),
    "charges":    lambda r, v: fx.charges(r),
    "filings":    lambda r, v: fx.filings(r.get("rows") or [], r.get("meta") or {}),
    "fin":        lambda r, v: fx.financials(_parsed(r)),
    "resolve":    lambda r, v: fx.resolve_candidates(r.get("candidates") or [],
                                                     subject=_subject(v)),
    "download":   lambda r, v: fx.filing_document(str(r.get("filingId") or ""),
                                                  int(r.get("bytes") or 0),
                                                  str(r.get("sha256") or "")),
    "frefresh":   lambda r, v: fx.refresh_receipt(
                      r, what="Filings refresh",
                      cached=bool(r.get("fromCache") or r.get("from_cache"))),
    "refresh":    lambda r, v: fx.company_update(
                      r.get("trigger") or {}, r.get("status") or {},
                      polls=int(r.get("polls") or 0),
                      done=str((r.get("status") or {}).get("status") or "").lower()
                      in ("completed", "complete", "done", "success")),
    "ustatus":    lambda r, v: fx.unlock_status(r),
    "usage":      lambda r, v: fx.usage(r),
    # --- domain ------------------------------------------------------
    "whois":      lambda r, v: fx.whois(r),
    "reput":      lambda r, v: fx.reputation(r),
    "ssl":        lambda r, v: fx.ssl(r, domain=getattr(v, "domain", None)),
    "rwhois":     lambda r, v: fx.reverse_whois(r),
    "shot":       lambda r, v: fx.screenshot(int(r.get("bytes") or 0),
                                             getattr(v, "website", None)),
    # --- web presence -------------------------------------------------
    "avail":      lambda r, v: fx.availability(r),
    "cdx":        lambda r, v: fx.timeline(r),
    "mentions":   lambda r, v: fx.mentions(r),
    # --- tax ----------------------------------------------------------
    "gst":        lambda r, v: fx.gst(r, subject=_subject(v)),
    "gstret":     lambda r, v: fx.gst_returns(r),
    # --- litigation ---------------------------------------------------
    "courtsearch":  lambda r, v: fx.case_search(r, subject=_subject(v)),
    "courthearing": lambda r, v: fx.hearings(r),
    "casedetail":   lambda r, v: fx.case_detail(r),
    "courtorders":  lambda r, v: fx.orders(str(r.get("cnr") or ""),
                                           r.get("orders") or []),
    "courtorderai": lambda r, v: fx.orders(str(r.get("cnr") or ""),
                                           r.get("orders") or [], generated=True),
    "causelist":    lambda r, v: fx.causelist(r, subject=_subject(v)),
    "court":        lambda r, v: fx.legal_check(r),
    "caserefresh":  lambda r, v: fx.job_receipt(r, what="A case refresh"),
    # --- internal -----------------------------------------------------
    "dup":        lambda r, v: fx.inhouse(r, kind="duplicate"),
    "rp":         lambda r, v: fx.inhouse(r, kind="related party"),
    "conflict":   lambda r, v: fx.inhouse(r, kind="conflict"),
    # --- reference ----------------------------------------------------
    "courtcaps":  lambda r, v: fx.catalog(
        "The filters this account's Case Search accepts.",
        list(r.get("fields") or [])),
    "courtenums": lambda r, v: fx.catalog(
        "Case status and bench type codes, read live from the source.",
        list(r.keys()) if isinstance(r, dict) else []),
    "courtstructure": lambda r, v: fx.catalog(
        "The court hierarchy this search covers.",
        [str(x.get("name") or x.get("district") or x) if isinstance(x, dict) else str(x)
         for x in (r.get("rows") or [])]),
    "courtdates": lambda r, v: fx.catalog(
        "Dates for which this court has cause-list data.",
        [str(d) for d in (r.get("dates") or [])]),
    "courtchecks": lambda r, v: fx.catalog(
        "Legal checks submitted on this account.",
        [str((i or {}).get("code") or i) for i in (r.get("items") or [])]),
}


def backfill(
    session: Session, *,
    vendor_id: str | None = None,
    check_id: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    stmt = select(VendorCheck)
    if vendor_id:
        stmt = stmt.where(VendorCheck.vendor_id == vendor_id)
    if check_id:
        stmt = stmt.where(VendorCheck.check_id == check_id)

    vendors: dict[str, Vendor | None] = {}
    tally = {"built": 0, "skipped_current": 0, "no_payload": 0,
             "no_builder": 0, "failed": 0}
    failures: list[str] = []

    for row in session.scalars(stmt):
        if not force and row.facts and row.parser_version == PARSER_VERSION:
            tally["skipped_current"] += 1
            continue
        if not isinstance(row.raw_response, dict) or not row.raw_response:
            # Nothing was stored — a skipped check, or one that never ran.
            # Correct to leave alone: the screen falls back to its status line.
            tally["no_payload"] += 1
            continue
        builder = BUILDERS.get(row.check_id)
        if builder is None:
            tally["no_builder"] += 1
            continue

        if row.vendor_id not in vendors:
            vendors[row.vendor_id] = session.get(Vendor, row.vendor_id)

        try:
            blob = builder(row.raw_response, vendors[row.vendor_id])
        except Exception as exc:  # noqa: BLE001 — one bad payload must not stop 3000
            tally["failed"] += 1
            failures.append(f"  {row.vendor_id}/{row.check_id}: "
                            f"{type(exc).__name__}: {exc}")
            continue

        if not dry_run:
            row.facts = blob
            row.parser_version = PARSER_VERSION
            session.add(row)
        tally["built"] += 1

    if not dry_run:
        session.commit()

    if failures:
        print("\nPayloads this parser could not read "
              "(the payload is untouched and still on file):", file=sys.stderr)
        for line in failures[:20]:
            print(line, file=sys.stderr)
        if len(failures) > 20:
            print(f"  … and {len(failures) - 20} more", file=sys.stderr)
    return tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vendor", help="one vendor id")
    ap.add_argument("--check", help="one check id")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even rows already at the current parser version")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()

    # get_engine(), not a module-level `engine`: session.py builds it
    # lazily on purpose, and importing the attribute would open a
    # connection at import time.
    with Session(get_engine()) as session:
        tally = backfill(session, vendor_id=args.vendor, check_id=args.check,
                         force=args.force, dry_run=args.dry_run)

    print(f"\nparser version {PARSER_VERSION}"
          f"{'  (DRY RUN — nothing written)' if args.dry_run else ''}")
    print(f"  built              {tally['built']}")
    print(f"  already current    {tally['skipped_current']}")
    print(f"  no stored payload  {tally['no_payload']}")
    print(f"  no parser yet      {tally['no_builder']}")
    print(f"  failed             {tally['failed']}")
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
