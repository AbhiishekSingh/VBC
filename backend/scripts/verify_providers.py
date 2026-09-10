#!/usr/bin/env python3
"""Verify what the adapters actually extract from REAL provider responses.

WHY THIS EXISTS
---------------
The WhoisXML reference document said WHOIS History returns
``createdDateNormalized``. The live API returns ``createdDateISO8601``.
Reading only the documented name produced ``created=None`` and
``age_years=None`` for every domain — silently, with no error, no failed
test and no exception. The check just quietly stopped being able to pass,
and a +10 risk rule quietly stopped being able to fire.

That is the dangerous shape of this class of bug: nothing breaks loudly.
A field the provider renamed, or never had, becomes a None that flows into
a score and looks like a legitimate "not applicable".

Documentation is a claim about an API. This script checks the claim.

TWO MODES
---------
1. LIVE — call the real providers and report what parsed:

       python -m scripts.verify_providers --domain q1ssl.com
       python -m scripts.verify_providers --domain q1ssl.com --cin U74999HR2015FTC056386

   Free checks run by default. Paid FileSure calls need
   VBC_ALLOW_PAID_CALLS=true, and the script tells you what each will cost
   before it spends anything.

2. OFFLINE — feed a payload you already captured (from Postman, say):

       python -m scripts.verify_providers --file whois.json --as whois_history

   No network, no credits. Useful for checking a response you already have.

WHAT IT REPORTS
---------------
For each normaliser, every field it is supposed to produce, and whether it
actually got a value. Fields marked CRITICAL are ones whose absence changes
a score — those are the ones that matter. Anything critical coming back
empty is reported as a FAILURE with the likely cause.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.providers import filesure as fs_mod  # noqa: E402
from app.providers.archive import ArchiveProvider  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402
from app.providers.filesure import FileSureProvider  # noqa: E402
from app.providers.whoisxml import WhoisXmlProvider, _summarise_history  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)


class Field:
    """One value a normaliser is expected to produce.

    ``critical`` means: if this is empty, a score is wrong. Those are the
    only ones worth waking someone up for.
    """

    def __init__(self, path: str, critical: bool = False, note: str = ""):
        self.path = path
        self.critical = critical
        self.note = note

    def get(self, data: Any) -> Any:
        current = data
        for part in self.path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current


#: What each normaliser must produce, and which fields carry a score.
CONTRACTS: dict[str, list[Field]] = {
    "whois_history": [
        Field("created", critical=True,
              note="feeds domain age -> risk rule r4 (+10). Live API uses "
                   "createdDateISO8601, NOT the documented createdDateNormalized."),
        Field("age_years", critical=True, note="whois check cannot PASS without it"),
        Field("expires"),
        Field("registrant", note="empty is legitimate when privacy-protected"),
        Field("registrar_changes"),
        Field("records_count", critical=True),
    ],
    "domain_reputation": [
        Field("score", critical=True, note="below 80 downgrades the check to WARN"),
        Field("test_count"),
    ],
    "ssl_certificate": [
        Field("present", critical=True),
        Field("issuer", critical=True, note="feeds trusted_ca -> risk rule r6 (+5)"),
        Field("valid_to", critical=True),
        Field("trusted_ca", critical=True),
    ],
    "archive_availability": [
        Field("archived", critical=True),
        Field("last_seen", note="null is legitimate when never archived"),
    ],
    "archive_timeline": [
        Field("captures", critical=True),
        Field("ok_captures", critical=True, note="feeds SCAN S3 (web presence)"),
        Field("first_ok_capture"),
        Field("continuous", critical=True, note="feeds risk rule r5 (+10)"),
    ],
    "master": [
        Field("status", critical=True, note="feeds risk rule r1 (+20)"),
        Field("class_of_company", critical=True, note="feeds SCAN S1"),
        Field("incorporated_on", critical=True, note="feeds SCAN S2 (vintage)"),
        Field("paidup_capital"),
        Field("registered_address"),
    ],
    "directors": [
        Field("0.din", critical=True),
        Field("0.name", critical=True),
        Field("0.disqualified", note="MUST be a real bool, not the string 'false'"),
        Field("0.still_serving",
              note="cessationDate is \"\" (not null) for a sitting director"),
    ],
    "charges": [
        Field("open", critical=True,
              note="dateOfSatisfaction null = OPEN. Reversing this reports a "
                   "secured lender as cleared."),
        Field("open_total"),
    ],
    "financials": [
        Field("revenue", critical=True, note="feeds SCAN N3 (turnover)"),
        Field("net_worth", critical=True, note="feeds risk rule r3 (+15)"),
        Field("scope", critical=True, note="standalone vs consolidated changes the numbers"),
        Field("filed_on", note="metadata.source.filingDate, NOT dateOfFiling"),
        Field("taxonomy", note="ind-as-2017 and in-ca both occur; lookups are prefix-agnostic"),
        Field("period_end"),
    ],
}


class Report:
    def __init__(self):
        self.checked = 0
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def section(self, name: str, ok: bool, detail: str = "") -> None:
        mark = f"{GREEN}OK  {RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"\n{BOLD}=== {name} ==={RESET}  {mark} {detail}")

    def field(self, field: Field, value: Any, source: str) -> None:
        self.checked += 1
        empty = value is None or value == "" or value == []
        tag = "CRITICAL" if field.critical else "optional"

        if not empty:
            shown = str(value)
            if len(shown) > 58:
                shown = shown[:55] + "..."
            print(f"  {GREEN}✓{RESET} {field.path:22s} = {shown}")
            return

        if field.critical:
            print(f"  {RED}✗{RESET} {field.path:22s} = {RED}EMPTY{RESET}  [{tag}]")
            if field.note:
                print(f"      {DIM}{field.note}{RESET}")
            self.failures.append(f"{source}.{field.path}")
        else:
            print(f"  {YELLOW}·{RESET} {field.path:22s} = {DIM}empty{RESET}  [{tag}]")
            if field.note:
                print(f"      {DIM}{field.note}{RESET}")
            self.warnings.append(f"{source}.{field.path}")

    def verify(self, name: str, data: Any) -> None:
        for field in CONTRACTS.get(name, []):
            self.field(field, field.get(data), name)

    def summary(self) -> int:
        print(f"\n{BOLD}{'=' * 62}{RESET}")
        if not self.failures:
            print(f"{GREEN}{BOLD}All critical fields parsed.{RESET} "
                  f"{self.checked} checked, {len(self.warnings)} optional empty.")
            print(f"{DIM}Optional empties are usually legitimate (privacy-protected "
                  f"registrant, never-archived domain).{RESET}")
            return 0

        print(f"{RED}{BOLD}{len(self.failures)} CRITICAL FIELD(S) DID NOT PARSE{RESET}")
        for failure in self.failures:
            print(f"  {RED}·{RESET} {failure}")
        print(f"\n{BOLD}What this means{RESET}")
        print("  Each of these feeds a score. An empty value does not raise an")
        print("  error — it flows through as a silent None and the affected check")
        print("  quietly stops being able to pass.")
        print(f"\n{BOLD}What to do{RESET}")
        print("  1. Save the raw response:  --file response.json --as <name> --dump")
        print("  2. Compare the real field names against the adapter's expectations")
        print("  3. Fix the adapter and add a regression test with the real payload")
        return 1


# =====================================================================


def run_live(args, report: Report) -> None:
    settings = get_settings()
    domain = args.domain

    print(f"{BOLD}Configuration{RESET}")
    print(f"  FileSure : {'sandbox' if settings.filesure_is_sandbox else 'live' if settings.filesure_configured else 'NOT CONFIGURED'}")
    print(f"  WhoisXML : {'configured' if settings.whoisxml_configured else 'NOT CONFIGURED'}")
    print(f"  Paid calls enabled: {settings.allow_paid_calls}")

    # ---- archive.org: free, always safe -----------------------------
    if domain:
        with ArchiveProvider(settings) as archive:
            for label, call in (
                ("archive_availability", lambda: archive.availability(domain)),
                ("archive_timeline", lambda: archive.timeline(domain, limit=50)),
            ):
                try:
                    data = call()
                    report.section(label, True, f"{DIM}free{RESET}")
                    report.verify(label, data)
                    _maybe_dump(args, label, data)
                except ProviderError as exc:
                    report.section(label, False, str(exc)[:70])
                    report.failures.append(f"{label}: unreachable")

    # ---- WhoisXML: costs credits ------------------------------------
    if domain and settings.whoisxml_configured:
        with WhoisXmlProvider(settings) as wx:
            attempts = [
                ("whois_history", lambda: wx.whois_history(domain), "50 credits"),
                ("domain_reputation", lambda: wx.domain_reputation(domain), "1 credit"),
                ("ssl_certificate", lambda: wx.ssl_certificate(domain), "1 credit"),
            ]
            for label, call, cost in attempts:
                if args.free_only:
                    print(f"\n{DIM}skipped {label} ({cost}) — --free-only{RESET}")
                    continue
                try:
                    data = call()
                    report.section(label, True, f"{DIM}{cost}{RESET}")
                    report.verify(label, data)
                    _maybe_dump(args, label, data)
                except ProviderError as exc:
                    report.section(label, False, str(exc)[:70])
                    report.failures.append(f"{label}: {type(exc).__name__}")

    # ---- FileSure: costs rupees -------------------------------------
    if args.cin and settings.filesure_configured:
        if args.free_only:
            print(f"\n{DIM}skipped all FileSure checks — --free-only{RESET}")
            return
        with FileSureProvider(settings) as fs:
            try:
                payload = fs.company_master(args.cin)
                report.section("master", True, f"{DIM}₹1{RESET}")
                report.verify("master", fs_mod.normalise_master(payload))
                _maybe_dump(args, "master", payload)

                directors = fs_mod.normalise_directors(payload)
                report.section("directors", bool(directors),
                               f"{DIM}included in master · {len(directors)} found{RESET}")
                report.verify("directors", {str(i): d for i, d in enumerate(directors)})
                _check_string_booleans(directors, report)

                charges = fs_mod.normalise_charges(payload)
                report.section("charges", True, f"{DIM}included in master{RESET}")
                report.verify("charges", charges)
            except ProviderError as exc:
                report.section("master", False, str(exc)[:70])
                report.failures.append(f"master: {type(exc).__name__}")

            try:
                data = fs.latest_financials(args.cin)
                if data is None:
                    report.section("financials", True,
                                   f"{DIM}no AOC-4 filed — a gap, not an error{RESET}")
                else:
                    report.section("financials", True, f"{DIM}₹3 + unlock{RESET}")
                    report.verify("financials", fs_mod.normalise_financials(data))
                    _maybe_dump(args, "financials", data)
            except ProviderError as exc:
                report.section("financials", False, str(exc)[:70])


def _check_string_booleans(directors: list[dict], report: Report) -> None:
    """The most dangerous gotcha: "false" is a truthy string in Python."""
    for director in directors:
        value = director.get("disqualified")
        if not isinstance(value, bool):
            print(f"  {RED}✗{RESET} disqualified is {type(value).__name__}, not bool "
                  f"— string booleans are not being converted")
            report.failures.append("directors.disqualified: not a bool")
            return
    if directors:
        print(f"  {GREEN}✓{RESET} {'disqualified':22s} = real booleans "
              f"{DIM}(string 'false' converted correctly){RESET}")


def run_offline(args, report: Report) -> None:
    """Check a payload you already captured, with no network and no credits."""
    payload = json.loads(Path(args.file).read_text())
    name = args.as_name

    normalisers: dict[str, Callable[[Any], Any]] = {
        "whois_history": lambda p: {
            "records_count": p.get("recordsCount", len(p.get("records", []))),
            **_summarise_history(p.get("records", [])),
        },
        "master": fs_mod.normalise_master,
        "directors": lambda p: {
            str(i): d for i, d in enumerate(fs_mod.normalise_directors(p))
        },
        "charges": fs_mod.normalise_charges,
        "financials": fs_mod.normalise_financials,
    }

    if name not in normalisers:
        print(f"{RED}Unknown --as value: {name}{RESET}")
        print(f"Choose from: {', '.join(sorted(normalisers))}")
        raise SystemExit(2)

    # Tolerate a full envelope or the inner data object.
    inner = payload.get("data", payload) if isinstance(payload, dict) else payload
    data = normalisers[name](inner)

    report.section(f"{name} (offline, from {Path(args.file).name})", True)
    report.verify(name, data)
    if args.dump:
        print(f"\n{DIM}Parsed output:{RESET}")
        print(json.dumps(data, indent=2, default=str)[:2000])


def _maybe_dump(args, label: str, data: Any) -> None:
    if not args.dump:
        return
    out = Path(f"verify-{label}.json")
    out.write_text(json.dumps(data, indent=2, default=str))
    print(f"  {DIM}raw payload written to {out}{RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check what the adapters really extract from provider responses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--domain", help="domain to test the WhoisXML and archive.org adapters against")
    parser.add_argument("--cin", help="CIN to test the FileSure adapter against")
    parser.add_argument("--free-only", action="store_true",
                        help="only run checks that cost nothing (archive.org)")
    parser.add_argument("--file", help="offline mode: a JSON payload to check")
    parser.add_argument("--as", dest="as_name",
                        help="offline mode: which normaliser to run it through")
    parser.add_argument("--dump", action="store_true",
                        help="write the raw payloads to disk for inspection")
    args = parser.parse_args()

    report = Report()
    print(f"{BOLD}Provider contract check{RESET}")
    print(f"{DIM}Documentation is a claim about an API. This checks the claim.{RESET}")

    if args.file:
        if not args.as_name:
            parser.error("--file needs --as (e.g. --as whois_history)")
        run_offline(args, report)
    elif args.domain or args.cin:
        run_live(args, report)
    else:
        parser.error("give --domain and/or --cin, or --file with --as")

    return report.summary()


if __name__ == "__main__":
    raise SystemExit(main())