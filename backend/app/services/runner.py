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
from app.providers import ecourts as ec_mod
from app.providers import finagg as fa_mod
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

#: Run sequentially, first, and in this order: later checks read the CIN and
#: the master payload these produce.
SEQUENTIAL_BLOCK = ("ustatus", "master", "dirs", "charges")

#: Free, local, no provider — run last, order irrelevant.
INHOUSE_BLOCK = ("dup", "rp", "conflict")

#: Checks whose runner needs a value the catalog cannot express as
#: ``requires`` — the dependency is on a FIELD of another finding, not on
#: the finding existing. These are forced into a later wave than the check
#: they read, on top of whatever the catalog says.
_EXTRA_ORDERING: dict[str, tuple[str, ...]] = {
    "rwhois": ("whois",),
    "shot": ("avail",),
    "dcontact": ("dprof",),
    "download": ("filings",),
    # casedetail reads the first CNR out of the courtsearch finding.
    "casedetail": ("courtsearch",),
}


def _waves(runnable: list[str], done_already: set[str] | None = None) -> list[list[str]]:
    """Group ``runnable`` into dependency-ordered waves.

    Everything inside a wave is independent and is dispatched together;
    each wave sees the findings of every wave before it. Derived from the
    catalog's ``requires`` graph rather than from a hand-maintained tuple,
    so a new check is executed the moment it is catalogued — the previous
    hardcoded PARALLEL_BLOCK/DEPENDENT_BLOCK silently dropped every check
    that nobody remembered to add to them.
    """
    done_already = done_already or set()
    pending = [c for c in runnable
               if c not in SEQUENTIAL_BLOCK and c not in INHOUSE_BLOCK
               and c not in done_already]
    pending_set = set(pending)

    def prereqs(check_id: str) -> set[str]:
        definition = CHECKS_BY_ID.get(check_id)
        needs = set(definition.requires if definition else ())
        needs |= set(_EXTRA_ORDERING.get(check_id, ()))
        # Only prerequisites that are actually running this time constrain
        # ordering. A prerequisite that was skipped is the dispatcher's
        # problem, not the scheduler's.
        return needs & pending_set

    waves: list[list[str]] = []
    done: set[str] = set()
    while pending:
        wave = [c for c in pending if prereqs(c) <= done]
        if not wave:
            # A cycle, or a prerequisite that cannot resolve. Run the rest
            # in one wave rather than dropping them on the floor.
            logger.warning("check dependency cycle among %s — running as one wave",
                           pending)
            wave = list(pending)
        waves.append(wave)
        done.update(wave)
        pending = [c for c in pending if c not in done]
    return waves


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


def _first_cnr(prior: dict) -> str | None:
    """The first CNR the case search turned up, if it ran."""
    found = prior.get("courtsearch")
    rows = ((found.raw or {}).get("results") or []) if found and found.raw else []
    for row in rows:
        if row.get("cnr"):
            return row["cnr"]
    return None


def _order_files(detail_raw: dict) -> list[str]:
    """Order filenames from a case-detail payload, judgments first.

    Judgments are the operative outcome; interim orders are procedural. When
    the fetch is capped, the caller should get the ones that decided
    something.
    """
    names: list[str] = []
    for key in ("judgment_orders", "interim_orders"):
        for order in detail_raw.get(key) or []:
            if not isinstance(order, dict):
                continue
            name = order.get("filename") or order.get("orderUrl") or order.get("order")
            if name:
                names.append(str(name).rsplit("/", 1)[-1])
    return names


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
        self.finagg = fa_mod.FinaggProvider(self.settings, spend=self.spend)
        self.ecourts = ec_mod.EcourtsProvider(self.settings, spend=self.spend)

    def close(self) -> None:
        for provider in (self.filesure, self.whoisxml, self.archive,
                         self.finagg, self.ecourts):
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
        for check_id in SEQUENTIAL_BLOCK:
            if check_id not in runnable:
                continue
            finding = self._run_one(check_id, vendor, cin, inputs, master_payload, result)
            result.findings.append(finding)
            if check_id == "master" and finding.status.was_examined:
                master_payload = finding.raw

        # --- STEP 5: every remaining provider check, in dependency waves --
        # Within a wave the checks are independent, so they go out together;
        # each wave reads the findings of the ones before it.
        # `resolve` (STEP 1) and anything else already dispatched must not
        # be run a second time.
        already = {f.check_id for f in result.findings}
        for wave in _waves(runnable, already):
            by_id = {f.check_id: f for f in result.findings}
            if len(wave) == 1:
                result.findings.append(
                    self._run_one(wave[0], vendor, cin, inputs,
                                  master_payload, result, by_id)
                )
                continue
            with ThreadPoolExecutor(max_workers=min(8, len(wave))) as pool:
                futures = [
                    pool.submit(self._run_one, check_id, vendor, cin, inputs,
                                master_payload, result, by_id)
                    for check_id in wave
                ]
                for future in as_completed(futures):
                    result.findings.append(future.result())

        # --- STEP 6: in-house --------------------------------------------
        for check_id in INHOUSE_BLOCK:
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
        except ec_mod.LegalCheckPending as exc:
            # A subclass of ProviderUnavailable, caught FIRST because the
            # code has to survive. The check is paid for and still running
            # on the provider's side; storing the code turns the next run
            # into a free collection instead of a second charge.
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Still running", str(exc),
                raw={"code": exc.code, "_pending": True},
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
        except ValueError as exc:
            # Input the adapter validated and REFUSED — a CIN typed into a
            # CNR field, a search filter the capability catalog does not
            # list. The call was never made, so this is a skipped check,
            # not a failure of the source. Reported as "Unexpected error"
            # before, which read like a crash.
            return Finding(
                check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                "Invalid input", str(exc), error=str(exc),
            )
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
        fs, wx, ar, fa = self.filesure, self.whoisxml, self.archive, self.finagg
        ec = self.ecourts

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

        # ---- GST · FinAGG GSP -----------------------------------------
        #
        # Both calls use the Common APIs, which read published GSTN data
        # and need no taxpayer consent. FinAGG's Taxpayer APIs are not
        # wired here on purpose: they authenticate as the taxpayer via an
        # OTP to their registered mobile, and a vendor being assessed does
        # not supply one.
        if check_id == "gst":
            gstin = get("gstin", vendor.gst or "")
            data = fa.search_gstin(gstin)
            if data["is_cancelled"]:
                status, value = CheckStatus.FAIL, "Registration cancelled"
            elif data["is_suspended"]:
                status, value = CheckStatus.FAIL, "Registration suspended"
            elif data["is_active"]:
                status, value = CheckStatus.PASS, "Registered and active"
            else:
                # A status we do not recognise is not a pass. Reporting an
                # unknown state as clean is the failure this product exists
                # to prevent.
                status = CheckStatus.WARN
                value = f"Status '{data['status']}' not recognised"
            return Finding(
                check_id, status, value,
                f"{data['legal_name'] or data['trade_name'] or 'Name not returned'} · "
                f"{data['taxpayer_type'] or 'type not returned'} · "
                f"registered {data['registered_on'] or 'date not returned'}"
                + (f" · cancelled {data['cancelled_on']}" if data["cancelled_on"] else "")
                + (f" · {data['additional_place_count']} additional "
                   f"place(s) of business"
                   if data.get("additional_place_count") else ""),
                raw=data,
            )

        if check_id == "gstret":
            gstin = get("gstin", vendor.gst or "")
            data = fa.returns_metadata(gstin, fy=get("fy") or None)
            months = data["months_since_last_filing"]
            if not data["filing_count"]:
                status = CheckStatus.FAIL
                value = f"No returns filed in {data['financial_year']}"
            elif months is not None and months > 3:
                status = CheckStatus.FAIL
                value = f"Last filed {months} months ago"
            elif months is not None and months > 1:
                status = CheckStatus.WARN
                value = f"Last filed {months} months ago"
            else:
                status = CheckStatus.PASS
                value = f"{data['filing_count']} returns filed"
            detail = (
                f"Latest {data['latest_period'] or '—'} filed "
                f"{data['latest_filed_on'] or '—'} · "
                f"types {', '.join(data['return_types']) or '—'}"
            )
            if data.get("fell_back_to_prior_fy"):
                # The analyst must see that the year reported is not the
                # current one, or "12 returns filed" reads as this year's.
                detail += (
                    f" · read from FY {data['financial_year']}: the current "
                    f"financial year has no filings due yet"
                )
            return Finding(check_id, status, value, detail, raw=data)

        if check_id == "courtsearch":
            party = get("parties", vendor.legal_name or vendor.name or "")
            if not party.strip():
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No party name",
                               "Court records are searched by the registered "
                               "legal name; the trade name will not match.")
            data = ec.case_search(
                parties=party,
                courtCodes=get("courtCodes") or None,
                filingDateFrom=get("filingDateFrom") or None,
            )
            count = data["count"]
            # A hit is not automatically adverse — a company recovering a
            # debt appears here alongside one being wound up. The side is in
            # petitioners/respondents, and judging it is the analyst's job.
            return Finding(
                check_id,
                CheckStatus.WARN if count else CheckStatus.PASS,
                f"{count} case(s) naming this party" if count else "No cases found",
                (f"Review the parties on each — appearing as petitioner is not "
                 f"the same fact as appearing as respondent."
                 if count else
                 f"Searched {', '.join(data['query'])} with no matches."),
                raw=data,
            )

        if check_id == "courthearing":
            found = prior.get("courtsearch")
            cnrs = [
                r["cnr"] for r in ((found.raw or {}).get("results") or [])
                if found and found.raw and r.get("cnr")
            ] if found else []
            if not cnrs:
                return Finding(check_id, CheckStatus.SKIP, "No cases to check",
                               "The case search found nothing to look up "
                               "hearings for.")
            data = ec.cnr_causelist_batch(cnrs)
            listed = data["listed_count"]
            return Finding(
                check_id,
                CheckStatus.WARN if listed else CheckStatus.PASS,
                f"{listed} of {data['checked']} listed for hearing",
                "An upcoming listing means the matter is live, not merely "
                "historical." if listed else
                "None of the matched cases are currently listed.",
                raw=data,
            )

        if check_id == "casedetail":
            cnr = get("cnr") or _first_cnr(prior)
            if not cnr:
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No CNR", "Supply a CNR, or run the case search "
                               "first so one can be taken from its results.")
            data = ec.case_detail(cnr)
            parties = " v ".join(filter(None, [
                ", ".join(data["petitioners"]) or None,
                ", ".join(data["respondents"]) or None,
            ]))
            # A pending matter is a live exposure; a disposed one is history.
            # But DISPOSED alone says nothing — a withdrawal and a conviction
            # are both "disposed", so the disposal TYPE carries the finding.
            status = CheckStatus.WARN if data["is_pending"] else CheckStatus.PASS
            return Finding(
                check_id, status,
                f"{data.get('case_status') or 'status unknown'}"
                + (f" · {data['disposal_type_raw']}" if data.get("disposal_type_raw") else ""),
                " · ".join(filter(None, [
                    parties or None,
                    data.get("case_type_sub") or data.get("case_type_label"),
                    data.get("acts_and_sections"),
                    data.get("court_name"),
                    f"filed {data['filing_date']}" if data.get("filing_date") else None,
                    f"{data['order_count']} order(s)" if data.get("order_count") else None,
                ])),
                raw=data,
            )

        if check_id in ("courtorders", "courtorderai"):
            detail = prior.get("casedetail")
            raw = (detail.raw or {}) if detail else {}
            cnr = raw.get("cnr")
            files = _order_files(raw)[: self.settings.ecourts_max_orders]
            if not cnr or not files:
                return Finding(check_id, CheckStatus.SKIP, "No orders to read",
                               "The case detail listed no judgment or interim "
                               "orders to fetch.")
            fetched = []
            for name in files:
                if check_id == "courtorders":
                    fetched.append(ec.order_markdown(cnr, name))
                else:
                    fetched.append(ec.order_ai(cnr, name))
            unreadable = sum(
                1 for f in fetched
                if check_id == "courtorders" and not f.get("markdown_available")
            )
            return Finding(
                check_id, CheckStatus.PASS,
                f"{len(fetched)} order(s) retrieved",
                (f"Capped at {self.settings.ecourts_max_orders} per case."
                 + (f" {unreadable} could not be converted to text — the PDF is "
                    f"still there." if unreadable else "")
                 + (" Analysis is generated by the PROVIDER's model, not by VBC "
                    "— it is a sourced finding, not registry fact."
                    if check_id == "courtorderai" else "")),
                raw={"cnr": cnr, "orders": fetched},
            )

        if check_id == "causelist":
            party = get("litigant", vendor.legal_name or vendor.name or "")
            if not party.strip():
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No party name", "Cause lists are searched by name.")
            data = ec.causelist_search(
                party, state=get("state") or None,
                limit=int(get("limit", "100") or 100),
                offset=int(get("offset", "0") or 0),
            )
            count = data["count"]
            more = data.get("truncated")
            return Finding(
                check_id, CheckStatus.WARN if count else CheckStatus.PASS,
                f"{count}{'+' if more else ''} listing(s) under this name",
                ("Name match is fuzzy — the list includes any party whose "
                 "name contains the search term, which for a group name "
                 "returns unrelated companies. An analyst must confirm "
                 "which rows are this vendor before any of it counts."
                 + (f" Capped at {data['limit']} — there are more."
                    if more else ""))
                if count else "Nothing scheduled under this name.",
                raw=data,
            )
        # ---- Admin · reference data. No SCAN parameter, no risk rule. ----
        if check_id == "courtcaps":
            data = ec.search_capabilities()
            return Finding(check_id, CheckStatus.PASS,
                           f"{len(data['fields'])} searchable field(s)",
                           "The authoritative list of Case Search filters.",
                           raw=data)

        if check_id == "courtenums":
            data = ec.enums(get("types", "caseStatus,benchType") or "caseStatus,benchType")
            return Finding(check_id, CheckStatus.PASS,
                           f"{len(data)} enum group(s)",
                           "Live codes — fetched rather than hard-coded.", raw=data)

        if check_id == "courtstructure":
            rows = ec.court_structure(get("state") or None,
                                      get("districtCode") or None)
            return Finding(check_id, CheckStatus.PASS, f"{len(rows)} entries",
                           "High courts appear as districts and the Supreme "
                           "Court as a state.", raw={"rows": rows})

        if check_id == "courtdates":
            dates = ec.available_dates(
                state=get("state"), districtCode=get("districtCode"),
                courtComplexCode=get("courtComplexCode"),
                courtNo=get("courtNo"), court=get("court"),
            )
            return Finding(check_id, CheckStatus.PASS, f"{len(dates)} date(s)",
                           "Dates holding cause-list data.", raw={"dates": dates})

        if check_id == "caserefresh":
            cnr = get("cnr") or _first_cnr(prior)
            if not cnr:
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No CNR", "Nothing to refresh.")
            data = ec.case_refresh(cnr)
            return Finding(
                check_id, CheckStatus.PASS, data.get("status") or "queued",
                f"{data.get('message') or 'Queued'} · "
                f"{data.get('estimated_time') or 'a few seconds'}. Re-run the "
                f"case detail check afterwards to see refreshed data.",
                raw=data,
            )

        if check_id == "courtchecks":
            data = ec.list_legal_checks(
                status=get("status") or None,
                page_size=int(get("page_size", "20") or 20),
            )
            return Finding(check_id, CheckStatus.PASS,
                           f"{len(data['items'])} legal check(s)",
                           "Every check submitted on this account.", raw=data)

        # ---- Litigation · eCourtsIndia LegalCheck ---------------------
        if check_id == "court":
            name = get("subjectName", vendor.legal_name or vendor.name or "")
            if not name.strip():
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No legal name",
                               "A court search needs the registered legal name; "
                               "the trade name will not match court records.")

            # A code stored by an EARLIER RUN means that check is paid for
            # and was still running when the request had to return. Collect
            # it rather than submitting — and paying — a second time.
            prior_code = self._prior_legal_check_code(vendor.id)

            data = ec.run_legal_check(
                subject_name=name,
                subject_type=get("subjectType", "company") or "company",
                # Stable per vendor, so an HTTP-level retry collects the
                # existing job instead of starting a second paid one.
                idempotency_key=f"vbc-{vendor.id}-court",
                client_ref_no=vendor.id,
                existing_code=prior_code,
                min_score=self.settings.ecourts_min_score,
            )

            band = data.get("risk_band") or "UNKNOWN"
            confidence = data.get("identity_confidence")
            confident = bool(data.get("confident"))
            count = data.get("match_count", 0)

            if not confident:
                # Named, not scored. r13 checks the same flag, so this
                # cannot move the ledger — it goes to a human instead.
                status = CheckStatus.WARN
                value = f"{band} band, identity confidence {confidence}"
                detail = (
                    f"Below the {ec_mod.MIN_IDENTITY_CONFIDENCE:.0f}% confidence "
                    f"threshold, so this is NOT scored. Matches may belong to a "
                    f"similarly-named party — an analyst should confirm whether "
                    f"'{name}' is the subject before this counts against the "
                    f"vendor."
                )
            elif band in ("HIGH", "MEDIUM"):
                status = CheckStatus.FAIL
                value = f"{band} litigation risk"
                detail = (f"{count} matter(s) matched at {confidence}% identity "
                          f"confidence · model {data.get('model')} · "
                          f"floor min_score={data.get('min_score_applied')}")
            else:
                status = CheckStatus.PASS
                value = f"{band or 'LOW'} litigation risk"
                detail = (f"{count} matter(s) matched at {confidence}% identity "
                          f"confidence · model {data.get('model')}")

            return Finding(check_id, status, value, detail, raw=data)

        return Finding(check_id, CheckStatus.SKIP, "Not implemented",
                       f"No runner is wired for check '{check_id}'.")

    # =================================================================

    def _prior_legal_check_code(self, vendor_id: str) -> str | None:
        """The LegalCheck code a previous run left behind, if any.

        LegalCheck is queued and charged at submit. When a run exhausts its
        poll budget the job keeps going on eCourts' side, so the code is
        stored with the unavailable finding. Reading it back turns a second
        attempt into a free collection instead of a second charge.
        """
        row = self.session.query(VendorCheck).filter(
            VendorCheck.vendor_id == vendor_id,
            VendorCheck.check_id == "court",
        ).one_or_none()
        if row is None or not isinstance(row.raw_response, dict):
            return None
        code = row.raw_response.get("code")
        return str(code) if code else None

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