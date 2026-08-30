"""The check orchestrator — STEP 0 to STEP 10 of the call sequence.

    STEP 0  Intake                no API, nothing compulsory
    STEP 1  Resolve identity      only when no CIN was supplied
    STEP 2  Unlock state          FREE — always before any paid unlock
    STEP 3  Unlock if needed      ₹330
    STEP 4  Company master        feeds S1, S2; directors and charges inline
    STEP 5  PARALLEL BLOCK        dispatched together
    STEP 6  Dependent calls       need a value from step 5
    STEP 7  In-house computation  dup, rp, conflict
    STEP 8  Score                 SCAN + point ledger
    STEP 9  Report                template assembly
    STEP 10 Analyst decision      binding, signed, audited

FOUR RULES THIS MODULE EXISTS TO ENFORCE
----------------------------------------
1. A FAILING SOURCE DOES NOT STOP THE OTHERS. Each check is isolated. Three
   retries, then it is recorded ``unavailable`` — never ``pass``.

2. A BLANK REQUIRED INPUT SKIPS ONE CHECK, NEVER THE RUN. It is recorded as
   ``skipped_missing_input`` and appears on the findings page. It must not
   vanish.

3. NEVER POST AN UNLOCK WITHOUT THE FREE GET FIRST. Three unlocks cost more
   than 6,600 filing downloads at ₹0.05, and the check that prevents a
   duplicate costs nothing.

4. EVERY OUTCOME IS WRITTEN, INCLUDING THE NON-OUTCOMES. A check that could
   not run leaves a row explaining why, because in an audit product silence
   must never look like a clean result.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.checks import CHECKS_BY_ID, expand_selection
from app.config import Settings, get_settings
from app.db.models import AuditLog, Unlock, Vendor, VendorCheck, VendorCheckInput
from app.domain.types import CheckStatus
from app.providers import archive as archive_mod
from app.providers import filesure as fs_mod
from app.providers import inhouse
from app.providers import whoisxml as wx_mod
from app.providers.base import (
    NotConfigured,
    PaidCallRefused,
    ProviderError,
    ProviderParseGap,
    ProviderRejected,
    ProviderUnavailable,
    SandboxLimitation,
    Spend,
    is_blank,
)

logger = logging.getLogger(__name__)

#: Checks safe to dispatch together — independent, and elapsed time becomes
#: the slowest call rather than their sum.
PARALLEL_BLOCK = ("filings", "fin", "whois", "reput", "ssl", "avail", "cdx", "mentions", "dprof")

#: Checks needing a value produced by the parallel block.
DEPENDENT_BLOCK = ("rwhois", "shot", "dcontact", "download")


@dataclass
class Finding:
    """One check's outcome, ready to persist."""

    check_id: str
    status: CheckStatus
    value: str = ""
    detail: str = ""
    raw: dict | None = None
    cost_paisa: int = 0
    credits: int = 0
    error: str | None = None
    #: Stamped at CONSTRUCTION — when the provider returned, not when the
    #: row was written. The parallel block runs nine checks over tens of
    #: seconds. Application clock, not SQL now(), which is TRANSACTION START
    #: time and would stamp every row with the second the run began.
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RunResult:
    vendor_id: str
    findings: list[Finding] = field(default_factory=list)
    spend: Spend = field(default_factory=Spend)
    unlock_purchased: bool = False
    ambiguous_candidates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def examined(self) -> int:
        return sum(1 for f in self.findings if f.status.was_examined)

    @property
    def skipped(self) -> list[Finding]:
        return [f for f in self.findings if not f.status.was_examined]


class CheckRunner:
    """Runs a vendor's selected checks and writes every outcome."""

    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.spend = Spend()
        self.filesure = fs_mod.FileSureProvider(self.settings, spend=self.spend)
        self.whoisxml = wx_mod.WhoisXmlProvider(self.settings, spend=self.spend)
        self.archive = archive_mod.ArchiveProvider(self.settings, spend=self.spend)

    def close(self) -> None:
        for provider in (self.filesure, self.whoisxml, self.archive):
            provider.close()

    # =================================================================

    def run(self, vendor: Vendor) -> RunResult:
        result = RunResult(vendor_id=vendor.id, spend=self.spend)
        selected = expand_selection(list(vendor.selected or []))
        inputs = self._inputs(vendor)

        self._audit(vendor.id, "RUN_STARTED",
                    f"{len(selected)} checks selected (prerequisites expanded)")

        # --- unconfigured providers and blank required inputs, up front --
        runnable: list[str] = []
        for check_id in selected:
            definition = CHECKS_BY_ID.get(check_id)
            if definition is None:
                continue
            if not definition.is_configured:
                result.findings.append(
                    Finding(check_id, CheckStatus.NOT_CONFIGURED, "No provider",
                            "No provider is wired up for this check on this platform.")
                )
                continue
            missing = self._missing_inputs(definition, inputs, selected, vendor)
            if missing:
                result.findings.append(
                    Finding(
                        check_id, CheckStatus.SKIPPED_MISSING_INPUT, "Not run",
                        f"Required input not provided: {', '.join(missing)}. "
                        f"The call was never made.",
                    )
                )
                continue
            runnable.append(check_id)

        # --- STEP 1: resolve identity when no CIN was supplied -----------
        cin = vendor.cin
        if not cin and "resolve" in runnable:
            cin = self._resolve_identity(vendor, inputs, result)

        # --- STEP 2/3: unlock lifecycle ----------------------------------
        needs_unlock = any(
            CHECKS_BY_ID[c].needs_company_unlock for c in runnable if c in CHECKS_BY_ID
        )
        if needs_unlock and cin:
            self._ensure_unlock(vendor, cin, result)

        # --- STEP 4: master, sequential — later steps depend on it -------
        master_payload: dict | None = None
        for check_id in ("ustatus", "master", "dirs", "charges"):
            if check_id not in runnable:
                continue
            finding = self._run_one(check_id, vendor, cin, inputs, master_payload, result)
            result.findings.append(finding)
            if check_id == "master" and finding.status.was_examined:
                master_payload = finding.raw

        # --- STEP 5: parallel block --------------------------------------
        parallel = [c for c in runnable if c in PARALLEL_BLOCK]
        if parallel:
            with ThreadPoolExecutor(max_workers=min(8, len(parallel))) as pool:
                futures = {
                    pool.submit(
                        self._run_one, check_id, vendor, cin, inputs, master_payload, result
                    ): check_id
                    for check_id in parallel
                }
                for future in as_completed(futures):
                    result.findings.append(future.result())

        # --- STEP 6: dependent calls -------------------------------------
        by_id = {f.check_id: f for f in result.findings}
        for check_id in (c for c in runnable if c in DEPENDENT_BLOCK):
            result.findings.append(
                self._run_one(check_id, vendor, cin, inputs, master_payload, result, by_id)
            )

        # --- STEP 7: in-house --------------------------------------------
        for check_id in ("dup", "rp", "conflict"):
            if check_id in runnable:
                result.findings.append(self._run_inhouse(check_id, vendor))

        self._persist(vendor, result)
        self._audit(
            vendor.id, "RUN_COMPLETE",
            f"{result.examined} examined, {len(result.skipped)} not examined · "
            f"₹{self.spend.paisa / 100:.2f} + {self.spend.credits} credits",
            actor="system",
        )
        return result

    # =================================================================
    # One check
    # =================================================================

    def _run_one(
        self, check_id: str, vendor: Vendor, cin: str | None, inputs: dict,
        master: dict | None, result: RunResult, prior: dict | None = None,
    ) -> Finding:
        """Isolate every failure so one bad source cannot stop the rest."""
        try:
            return self._dispatch(check_id, vendor, cin, inputs, master, result, prior or {})
        except NotConfigured as exc:
            return Finding(check_id, CheckStatus.NOT_CONFIGURED, "Not configured", str(exc))
        except PaidCallRefused as exc:
            return Finding(
                check_id, CheckStatus.SKIPPED_MISSING_INPUT, "Paid call refused", str(exc)
            )
        except SandboxLimitation as exc:
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Sandbox key",
                f"The provider served a sandbox response rather than real data: {exc}. "
                f"This is not a finding about the vendor.",
                error=str(exc),
            )
        except ProviderRejected as exc:
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Provider rejected the call", str(exc),
                error=str(exc),
            )
        except ProviderParseGap as exc:
            # The source answered; WE could not read it. An application
            # defect, not a finding about the vendor.
            logger.error("parse gap in check %s: %s", check_id, exc)
            # Persist the payload: a paid response we cannot read is the
            # one artefact needed to fix the adapter.
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Response not understood",
                f"{exc} This is an adapter defect, not a finding about the vendor.",
                raw={
                    "_parse_gap": str(exc),
                    "_note": (
                        "The provider's response, kept because this adapter could "
                        "not read it. Send this to whoever maintains the adapter — "
                        "the call does not need to be paid for again."
                    ),
                    "payload": exc.payload,
                },
                error=str(exc),
            )
        except ProviderUnavailable as exc:
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Source unavailable",
                f"{exc} — recorded as unexamined, not as a pass.", error=str(exc),
            )
        except ProviderError as exc:
            return Finding(check_id, CheckStatus.UNAVAILABLE, "Check failed", str(exc),
                           error=str(exc))
        except Exception as exc:  # noqa: BLE001 — one bad check must not kill a run
            logger.exception("unhandled error in check %s", check_id)
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Unexpected error",
                f"{type(exc).__name__}: {exc}", error=str(exc),
            )

    def _dispatch(
        self, check_id: str, vendor: Vendor, cin: str | None, inputs: dict,
        master: dict | None, result: RunResult, prior: dict,
    ) -> Finding:
        get = lambda key, default="": inputs.get(check_id, {}).get(key, default)  # noqa: E731
        fs, wx, ar = self.filesure, self.whoisxml, self.archive

        # ---- MCA ----------------------------------------------------
        if check_id == "ustatus":
            status = fs.unlock_status(cin or "")
            return Finding(
                check_id, CheckStatus.PASS,
                "Unlocked" if status.unlocked else "Not unlocked",
                f"Expires {status.expires_at}." if status.expires_at
                else "No active unlock on file.",
                raw=status.__dict__,
            )

        if check_id == "master":
            if not cin:
                return Finding(check_id, CheckStatus.FAIL, "Not a registered company",
                               "No CIN — MCA holds no record for this entity.")
            payload = fs.company_master(cin)
            facts = fs_mod.normalise_master(payload)
            active = str(facts.get("status", "")).lower() == "active"
            renamed = bool(facts.get("name_history"))
            return Finding(
                check_id,
                CheckStatus.PASS if active else CheckStatus.WARN,
                f"{facts.get('status', 'Unknown')} · {facts.get('cin')}",
                f"Incorporated {facts.get('incorporated_on')} · "
                f"{facts.get('class_of_company')} · paid-up "
                f"₹{(facts.get('paidup_capital') or 0) / 10_000_000:.2f} Cr"
                + (" · company has been renamed previously" if renamed else ""),
                raw={"facts": facts, "payload": payload},
            )

        if check_id == "dirs":
            if not master:
                return Finding(check_id, CheckStatus.SKIP, "N/A",
                               "Company master did not return, so no directors are on file.")
            directors = fs_mod.normalise_directors(master.get("payload", master))
            disqualified = [d for d in directors if d["disqualified"]]
            return Finding(
                check_id,
                CheckStatus.FAIL if disqualified else CheckStatus.PASS,
                f"{len(directors)} director{'s' if len(directors) != 1 else ''}",
                (f"{len(disqualified)} disqualified: "
                 f"{', '.join(d['name'] for d in disqualified)}. ")
                if disqualified else
                ", ".join(f"{d['name']} (DIN {d['din']})" for d in directors) or "None listed.",
                raw={"directors": directors},
            )

        if check_id == "charges":
            if not master:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No master data on file.")
            charges = fs_mod.normalise_charges(master.get("payload", master))
            open_charges = charges["open"]
            if not open_charges:
                return Finding(check_id, CheckStatus.PASS, "No open charges",
                               f"{len(charges['closed'])} historical charges, all satisfied.",
                               raw=charges)
            return Finding(
                check_id, CheckStatus.WARN,
                f"{len(open_charges)} open charge · ₹{charges['open_total'] / 10_000_000:.2f} Cr",
                "; ".join(
                    f"{c['holder']} ₹{(c['amount'] or 0) / 10_000_000:.2f} Cr "
                    f"created {c['created_on']}, not satisfied"
                    for c in open_charges
                ),
                raw=charges,
            )

        if check_id == "resolve":
            candidates = fs.resolve_company(
                get("q", vendor.name), state=get("state"), city=get("city"),
                limit=int(get("limit", 10) or 10),
            )
            if not candidates:
                return Finding(check_id, CheckStatus.WARN, "No CIN found",
                               "No MCA registration traced — consistent with a "
                               "proprietorship or partnership firm.",
                               raw={"candidates": []})
            top = candidates[0]
            strong = [c for c in candidates if (c.get("matchScore") or 0) >= 0.9]
            if len(strong) > 1:
                return Finding(
                    check_id, CheckStatus.WARN, f"{len(strong)} strong matches",
                    "More than one company matches this name closely. The "
                    "ambiguity is surfaced rather than resolved automatically — "
                    "auditing the wrong company is worse than auditing none.",
                    raw={"candidates": candidates},
                )
            return Finding(check_id, CheckStatus.PASS,
                           f"{top.get('cin')} · {top.get('company')}",
                           f"Match score {top.get('matchScore')}.",
                           raw={"candidates": candidates})

        if check_id == "filings":
            if not cin:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No CIN.")
            year = get("year")
            rows, meta = fs.filings(
                cin, form_id=get("formId", ""), year=int(year) if year else None,
                limit=int(get("limit", 50) or 50),
            )
            if not rows:
                return Finding(check_id, CheckStatus.WARN, "No filings returned",
                               "MCA holds no filings matching this filter.",
                               raw={"rows": [], "meta": meta})
            latest = rows[0]
            return Finding(
                check_id, CheckStatus.PASS, "Filings on record",
                f"Most recent {latest.get('formId')} filed "
                f"{latest.get('dateOfFiling')} · {meta.get('total', len(rows))} total "
                f"(page limit honoured: {meta.get('limit')})",
                raw={"rows": rows, "meta": meta},
            )

        if check_id == "fin":
            if not cin:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No CIN.")
            year = get("year")
            data = fs.latest_financials(
                cin, form_type=get("formType", "AOC-4") or "AOC-4",
                year=int(year) if year else None,
                scope=get("scope", "standalone") or "standalone",
            )
            if not data:
                return Finding(
                    check_id, CheckStatus.WARN, "No financials filed",
                    "The requested form type is not among those available for "
                    "this company — a gap in the record, not a failed call.",
                )
            facts = fs_mod.normalise_financials(data)
            revenue = facts.get("revenue")
            gaps = facts.get("year_gaps") or []
            return Finding(
                check_id,
                CheckStatus.PASS if facts["positive_net_worth"] else CheckStatus.WARN,
                (f"Revenue ₹{revenue / 10_000_000:.2f} Cr" if revenue else "Filed financials"),
                f"{facts['scope']} · FY ending {facts['period_end']} · net worth "
                f"₹{(facts['net_worth'] or 0) / 10_000_000:.2f} Cr"
                + (f" · filing gaps in {gaps}" if gaps else ""),
                raw=facts,
            )

        if check_id == "dprof":
            dins = [get("din")] if get("din") else [
                d["din"] for d in (prior.get("dirs").raw or {}).get("directors", [])
                if prior.get("dirs") and prior["dirs"].raw
            ]
            dins = [d for d in dins if d]
            if not dins:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No DIN available.")
            profiles = [fs.director_profile(din) for din in dins[:5]]
            active_elsewhere = sum(
                1 for p in profiles
                for c in (p.get("companyData") or [])
                # Empty string, not null, in a real payload — is_blank
                # covers both. "is None" alone reported every sitting
                # director as having resigned.
                if is_blank(c.get("cessationDate"))
            )
            return Finding(check_id, CheckStatus.PASS, f"{len(profiles)} profiles retrieved",
                           f"{active_elsewhere} active directorships across all profiles.",
                           raw={"profiles": profiles})

        # ---- WhoisXML ------------------------------------------------
        if check_id == "whois":
            domain = get("domainName", vendor.domain or "")
            mode = "preview" if "preview" in str(get("mode", "")) else "purchase"
            data = wx.whois_history(domain, mode=mode)
            age = data.get("age_years")
            return Finding(
                check_id,
                CheckStatus.PASS if (age or 0) >= 2 else CheckStatus.WARN,
                f"Domain age {age} yrs" if age is not None else "Ownership history retrieved",
                f"Registered {data.get('created')} · registrant "
                f"{data.get('registrant') or 'privacy-protected'} · "
                f"{data.get('registrar_changes')} registrar change(s)",
                raw=data, credits=50 if mode == "purchase" else 0,
            )

        if check_id == "reput":
            data = wx.domain_reputation(get("domainName", vendor.domain or ""),
                                        mode=get("mode", "fast") or "fast")
            score = data.get("score") or 0
            return Finding(
                check_id,
                CheckStatus.PASS if score >= 80 else CheckStatus.WARN,
                f"Trust score {score}",
                "; ".join(w["warning"] for w in data["warnings"]) or "No warnings raised.",
                raw=data, credits=1,
            )

        if check_id == "ssl":
            data = wx.ssl_certificate(get("domainName", vendor.domain or ""))
            if not data.get("present"):
                return Finding(check_id, CheckStatus.FAIL, "No certificate",
                               "No SSL certificate served for this domain.", raw=data,
                               credits=1)
            trusted = data.get("trusted_ca")
            return Finding(
                check_id,
                CheckStatus.PASS if trusted else CheckStatus.FAIL,
                "Valid SSL" if trusted else "Untrusted certificate",
                f"{data.get('issuer')} · valid to {data.get('valid_to')}"
                + (" · wildcard" if data.get("wildcard") else ""),
                raw=data, credits=1,
            )

        if check_id == "rwhois":
            term = get("searchTerm") or (
                (prior.get("whois").raw or {}).get("registrant_email")
                or (prior.get("whois").raw or {}).get("registrant")
                if prior.get("whois") and prior["whois"].raw else ""
            )
            data = wx.reverse_whois(term or "", search_type=get("searchType", "current"))
            if not data.get("queried"):
                return Finding(check_id, CheckStatus.SKIP, "No registrant to search",
                               "Ownership history returned no registrant value, so a "
                               "portfolio search would have been meaningless.", raw=data)
            return Finding(check_id, CheckStatus.PASS,
                           f"{data['count']} domains, same owner",
                           f"Searched on '{data['term']}'. A varied portfolio is "
                           f"consistent with an agency; near-identical variants of "
                           f"one brand would suggest typosquatting.",
                           raw=data, credits=1)

        if check_id == "shot":
            image = wx.screenshot(get("url", vendor.website or ""),
                                  image_format=get("imageOutputFormat", "JPG"))
            return Finding(check_id, CheckStatus.PASS, "Screenshot captured",
                           f"{len(image)} bytes.", raw={"bytes": len(image)})

        # ---- archive.org --------------------------------------------
        if check_id == "avail":
            data = ar.availability(get("url", vendor.domain or ""),
                                   timestamp=get("timestamp", ""))
            if not data["archived"]:
                return Finding(check_id, CheckStatus.FAIL, "Never archived",
                               "archived_snapshots is empty — no web presence on record.",
                               raw=data)
            return Finding(check_id, CheckStatus.PASS, "Archived",
                           f"Last captured {data.get('last_seen')}.", raw=data)

        if check_id == "cdx":
            data = ar.timeline(
                get("url", vendor.domain or ""),
                match_type="domain" if "domain" in str(get("matchType", "domain")) else "exact",
                limit=int(get("limit", 50) or 50),
                date_from=str(get("from", "")).replace("-", ""),
                date_to=str(get("to", "")).replace("-", ""),
            )
            outages = data.get("outages") or []
            if data["captures"] == 0:
                return Finding(check_id, CheckStatus.FAIL, "No captures",
                               "No archived snapshots at all.", raw=data)
            return Finding(
                check_id,
                CheckStatus.PASS if data["continuous"] else CheckStatus.WARN,
                f"{data['captures']} captures"
                + (f", {len(outages)} outage(s)" if outages else ", no outages"),
                f"First successful capture {data.get('first_ok_capture')}"
                + ("; " + "; ".join(
                    f"{o['status']} from {o['from']} to {o['to']}" for o in outages[:3]
                ) if outages else ""),
                raw=data,
            )

        if check_id == "mentions":
            data = ar.mentions(get("q", vendor.name), rows=int(get("rows", 50) or 50))
            return Finding(check_id, CheckStatus.PASS, f"{data['found']} loose hits",
                           data["note"], raw=data)

        if check_id == "usage":
            data = fs.account_usage()
            balance = (data.get("wallet") or {}).get("balancePaisa", 0)
            return Finding(check_id, CheckStatus.PASS,
                           f"Wallet ₹{balance / 100:,.2f}", "Account usage retrieved.",
                           raw=data)

        return Finding(check_id, CheckStatus.SKIP, "Not implemented",
                       f"No runner is wired for check '{check_id}'.")

    # =================================================================

    def _run_inhouse(self, check_id: str, vendor: Vendor) -> Finding:
        try:
            if check_id == "dup":
                res = inhouse.check_duplicate(self.session, vendor)
                if not res.matched:
                    return Finding(check_id, CheckStatus.PASS, "No duplicate",
                                   f"No match across {res.compared_against} vendors.",
                                   raw=res.as_payload())
                top = res.matches[0]
                return Finding(
                    check_id,
                    CheckStatus.FAIL if top["confidence"] == "conclusive" else CheckStatus.WARN,
                    f"Possible duplicate of #{top['vendorId']}",
                    f"{top['rule']} ({top['confidence']}): {top['detail']}",
                    raw=res.as_payload(),
                )

            if check_id == "rp":
                res = inhouse.check_related_party(self.session, vendor)
                if not res.matched:
                    return Finding(check_id, CheckStatus.PASS, "No related party",
                                   f"No shared directors or addresses across "
                                   f"{res.compared_against} vendors.", raw=res.as_payload())
                top = res.matches[0]
                return Finding(check_id, CheckStatus.WARN,
                               f"Related to #{top['vendorId']}", top["detail"],
                               raw=res.as_payload())

            if check_id == "conflict":
                res = inhouse.check_conflict(self.session, vendor)
                if res.compared_against == 0:
                    # Nothing was compared. This must not read as "no conflict".
                    return Finding(
                        check_id, CheckStatus.UNAVAILABLE, "No employee register",
                        "No employee register is connected, so nothing was compared. "
                        "This is a coverage gap, not a clean result.",
                        raw=res.as_payload(),
                    )
                if not res.matched:
                    return Finding(check_id, CheckStatus.PASS, "No conflict",
                                   f"No overlap across {res.compared_against} employees.",
                                   raw=res.as_payload())
                top = res.matches[0]
                return Finding(check_id, CheckStatus.FAIL, "Conflict of interest",
                               f"{top['rule']}: director matches employee "
                               f"{top.get('employee')}.", raw=res.as_payload())
        except Exception as exc:  # noqa: BLE001
            logger.exception("in-house check %s failed", check_id)
            return Finding(check_id, CheckStatus.UNAVAILABLE, "Check failed",
                           str(exc), error=str(exc))

        return Finding(check_id, CheckStatus.SKIP, "Not implemented", "")

    # =================================================================

    def _resolve_identity(self, vendor: Vendor, inputs: dict, result: RunResult) -> str | None:
        finding = self._run_one("resolve", vendor, None, inputs, None, result)
        result.findings.append(finding)
        candidates = (finding.raw or {}).get("candidates", [])
        strong = [c for c in candidates if (c.get("matchScore") or 0) >= 0.9]
        if len(strong) > 1:
            # Ambiguity is surfaced, never resolved automatically.
            result.ambiguous_candidates = strong
            result.notes.append(
                f"{len(strong)} companies match this name closely — an analyst must "
                f"pick before MCA checks can run."
            )
            return None
        if strong:
            cin = strong[0].get("cin")
            vendor.cin = cin
            self._audit(vendor.id, "CIN_RESOLVED", f"Resolved to {cin}", actor="system")
            return cin
        return None

    def _ensure_unlock(self, vendor: Vendor, cin: str, result: RunResult) -> None:
        """STEP 2 then STEP 3 — never the other way round."""
        try:
            existing = self.session.scalar(
                select(Unlock).where(
                    Unlock.scope == "company", Unlock.identifier == cin,
                    Unlock.expires_at > datetime.now(timezone.utc),
                )
            )
            if existing:
                result.notes.append(
                    f"Company already unlocked until {existing.expires_at:%Y-%m-%d} — "
                    f"₹330 not spent again."
                )
                vendor.unlocked = True
                return

            status, paid = self.filesure.ensure_unlocked(cin)
            vendor.unlocked = status.unlocked
            if not paid:
                result.notes.append("Unlock already active at the provider — no charge.")
                return
            if status.sandbox:
                result.notes.append(
                    "Unlock returned sandbox:true — no real unlock occurred. "
                    "A live key is needed before financials can be read."
                )
                return

            result.unlock_purchased = True
            expires = datetime.now(timezone.utc) + timedelta(days=365)
            if status.expires_at:
                try:
                    expires = datetime.fromisoformat(status.expires_at.replace("Z", "+00:00"))
                except ValueError:
                    pass
            self.session.add(
                Unlock(scope="company", identifier=cin, vendor_id=vendor.id,
                       cost_paisa=fs_mod.COMPANY_UNLOCK_PAISA, expires_at=expires)
            )
            self._audit(vendor.id, "COMPANY_UNLOCKED",
                        f"₹330 · {cin} · expires {expires:%Y-%m-%d}", actor="system")
        except (NotConfigured, PaidCallRefused) as exc:
            result.notes.append(f"Unlock not attempted: {exc}")
        except ProviderError as exc:
            result.notes.append(f"Unlock failed: {exc}. Checks needing it will be skipped.")

    # =================================================================

    def _inputs(self, vendor: Vendor) -> dict[str, dict[str, str]]:
        rows = self.session.scalars(
            select(VendorCheckInput).where(VendorCheckInput.vendor_id == vendor.id)
        ).all()
        out: dict[str, dict[str, str]] = {}
        for row in rows:
            out.setdefault(row.check_id, {})[row.key] = row.value
        return out

    def _missing_inputs(
        self, definition, inputs: dict, selected: list[str], vendor: Vendor
    ) -> list[str]:
        missing = []
        for param in definition.params:
            if not param.required:
                continue
            if param.from_result and param.from_result in selected:
                continue  # another check supplies it
            value = inputs.get(definition.id, {}).get(param.key, "")
            if not value and param.from_vendor:
                value = getattr(vendor, param.from_vendor, "") or ""
            if not str(value).strip():
                missing.append(param.label)
        return missing

    def _persist(self, vendor: Vendor, result: RunResult) -> None:
        """Write every outcome, including the non-outcomes."""
        for finding in result.findings:
            existing = self.session.scalar(
                select(VendorCheck).where(
                    VendorCheck.vendor_id == vendor.id,
                    VendorCheck.check_id == finding.check_id,
                )
            )
            row = existing or VendorCheck(vendor_id=vendor.id, check_id=finding.check_id)

            # fetched_at has server_default=now() but no onupdate, so a
            # re-run kept the FIRST run's timestamp. Written explicitly.
            row.fetched_at = finding.fetched_at
            # Every write is an attempt. Previously stuck at 1 forever, which
            # hid how many times a flaky source had been re-run.
            row.attempts = (existing.attempts + 1) if existing else 1

            row.status = finding.status.value
            row.value = finding.value
            row.detail = finding.detail
            # The real payload — this is what makes a historical score
            # defensible. Never a template in production.
            row.raw_response = finding.raw
            row.cost_paisa = finding.cost_paisa
            row.credits = finding.credits
            row.error = finding.error
            self.session.add(row)
        self.session.flush()

    def _audit(self, vendor_id: str, action: str, detail: str, actor: str = "system") -> None:
        self.session.add(
            AuditLog(vendor_id=vendor_id, actor=actor, action=action, detail=detail)
        )
