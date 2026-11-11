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

import base64
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.checks import CHECKS_BY_ID, expand_selection
from app.config import Settings, get_settings
from app.db.models import AuditLog, Unlock, Vendor, VendorCheck, VendorCheckInput
from app.db.models import StoredDocument as StoredDocumentRow
from app.domain.validation import detect_id_type, split_subjects
from app.domain.facts import crore as _crore
from app.domain.facts import paisa as _paisa
from app.domain.facts import human_date as _human_date
from app.domain.types import CheckStatus
from app.providers import archive as archive_mod
from app.providers import factsets
from app.services import documents as docs
from app.services import provider_state
from app.providers import filesure as fs_mod
from app.providers import ecourts as ec_mod
from app.providers import finagg as fa_mod
from app.providers import gridlines as gl_mod
from app.providers import inhouse
from app.providers import vision as vision_mod
from app.providers import whoisxml as wx_mod
from app.providers.base import (
    NotConfigured,
    PaidCallRefused,
    ProviderAccountBlocked,
    ProviderError,
    ProviderOutOfCredits,
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
    #: The renderable middle tier — see ``app.domain.facts``. DERIVED from
    #: ``raw`` and rebuildable from it, so a parse defect is fixed by
    #: re-running the parser over stored payloads rather than re-paying the
    #: provider. Never load-bearing: a status is decided before this is
    #: built, and a screen falls back to ``value``/``detail`` without it.
    facts: dict | None = None
    cost_paisa: int = 0
    credits: int = 0
    error: str | None = None
    #: Set when the provider refused the ACCOUNT rather than the request
    #: (401/402/403) — the provider's own words, verbatim. Carried on the
    #: finding rather than written to ``provider_outages`` on the spot
    #: because checks run in a thread pool and one SQLAlchemy Session is
    #: not safe across threads. ``run`` reconciles it once the pool has
    #: joined; nothing is visible to other sessions before the commit at
    #: the end of the run either way, so nothing is lost by waiting.
    account_blocked: str | None = None
    account_blocked_status: int | None = None
    #: Stamped at CONSTRUCTION — when the provider returned, not when the
    #: row was written. The parallel block runs nine checks over tens of
    #: seconds. Application clock, not SQL now(), which is TRANSACTION START
    #: time and would stamp every row with the second the run began.
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


#: Providers that are not outside accounts and so can never be "blocked":
#: in-house derivations and checks with no provider at all.
_NOT_AN_ACCOUNT = frozenset({"in_house", "none", ""})


def _provider_of(check_id: str) -> str | None:
    """The outside account a check spends against, or None.

    One spelling of the provider name, taken from the catalog, used by the
    outage table, the runner and the API. If the runner recorded
    "filesure" and the API asked about "FileSure", a blocked provider
    would stay invisible on the screen that exists to show it.
    """
    definition = CHECKS_BY_ID.get(check_id)
    if definition is None:
        return None
    provider = getattr(definition.provider, "value", "")
    return None if provider in _NOT_AN_ACCOUNT else provider


#: Providers that bill from SEPARATE POOLS per product, so a refusal says
#: nothing about their other endpoints.
#:
#: Only WhoisXML, and it was proven rather than assumed. On 6 Nov 2026 one
#: key, from one IP, inside a minute:
#:
#:     ssl-certificates  200      domain-reputation  200
#:     whois-history     403      reverse-whois      403
#:
#: The Domain Research Suite subscription had lapsed. Treating that as a
#: provider-wide outage would have disabled two checks that were answering
#: normally.
#:
#: FileSure, eCourts and FinAGG each draw on ONE wallet — a refusal there
#: genuinely is account-wide, and splitting them would mean every endpoint
#: discovering an empty wallet separately, which is the failure this whole
#: mechanism exists to stop.
_PER_PRODUCT_PROVIDERS = frozenset({"whoisxml"})

#: Providers whose **403** means "this credential is not entitled to THIS
#: product", rather than something account-wide.
#:
#: Evidence, from one Gridlines run on 7 Nov 2026 — same key, same
#: second:
#:
#:     /profile-api/mobile/address-lookup      403
#:     /epfo-api/fetch-uan                     200
#:     /profile-api/mobile/prefill             200
#:     /profile-api/mobile/digital-footprint   200
#:
#: with the body ``FORBIDDEN_ACCESS: Credential does not have access to
#: this product``. Recorded account-wide, that single refusal held all
#: five person checks on every later run — the platform causing a wider
#: outage than the one it exists to prevent, which is exactly the
#: failure the WhoisXML pool split was built to stop and which was then
#: not applied here.
#:
#: Keyed by STATUS and PROVIDER, never by reading the provider's prose.
#: A 403 does not mean the same thing everywhere: WhoisXML returns one
#: for an empty balance, a revoked key AND a blocked IP, all genuinely
#: account-wide, which is why it is absent from this set and gets its
#: separate pools a different way.
#:
#: 401 and 402 stay account-wide for everyone. An empty wallet really
#: does affect every product, and discovering that five times over is
#: the failure the shared outage record exists to prevent.
_PRODUCT_SCOPED_403 = frozenset({"gridlines"})


def _outage_scope(check_id: str, status: int | None) -> tuple[str, str] | None:
    """Which pool a REFUSAL covers — not the same question as billing.

    ``_billing_scope`` answers "whose wallet does this spend from".
    This answers "how far does this refusal reach", and the two differ
    for an entitlement error: Gridlines bills one wallet, but a 403 on
    one of its products says nothing about the other four.
    """
    scope = _billing_scope(check_id)
    if scope is None:
        return None
    provider, product = scope
    if status == 403 and provider in _PRODUCT_SCOPED_403:
        return provider, check_id
    return provider, product


def _hold_scopes(check_id: str) -> list[tuple[str, str]]:
    """Every open outage that should stop this check running.

    BOTH the wallet-wide pool and this check's own product pool, because
    a refusal is stored under whichever of the two it reached. Checking
    only the billing scope would leave a product-scoped block unable to
    hold the very check it was recorded for.
    """
    scope = _billing_scope(check_id)
    if scope is None:
        return []
    provider, product = scope
    scopes = [(provider, product)]
    if provider in _PRODUCT_SCOPED_403 and product != check_id:
        scopes.append((provider, check_id))
    return scopes


def _billing_scope(check_id: str) -> tuple[str, str] | None:
    """``(provider, product)`` — which POOL this check spends from.

    ``product`` is "" when the provider bills from a single wallet, which
    is the common case and preserves provider-wide blocking for it.

    The product key is the check id rather than the endpoint path: the two
    are one-to-one for WhoisXML, and a check id is stable, already in the
    catalog, and readable in a database row. An endpoint path would drift
    the moment a provider renamed a route.
    """
    provider = _provider_of(check_id)
    if provider is None:
        return None
    if provider in _PER_PRODUCT_PROVIDERS:
        return provider, check_id
    return provider, ""


def _checks_in_scope(provider: str, product: str) -> list[str]:
    """Every check a given outage actually covers.

    The API hands this to the screen so the browser never has to know how
    a provider bills. Without it, Step 2 would need its own copy of
    ``_PER_PRODUCT_PROVIDERS``, and the two would drift — which is exactly
    how the scoring engine once ended up 25 points apart from itself.
    """
    # A product-scoped 403 is stored under the CHECK ID it was refused
    # for, so its outage covers that one check and nothing else. Without
    # this branch the API would report an empty `blockedChecks` for it,
    # Step 2 would grey nothing, and the runner would hold a check the
    # screen had just offered — the two disagreeing about what can run.
    if provider in _PRODUCT_SCOPED_403 and product in CHECKS_BY_ID:
        return [product]
    return [
        c.id for c in CHECKS_BY_ID.values()
        if _billing_scope(c.id) == (provider, product)
    ]


def _first_cnr(prior: dict) -> str | None:
    """The first CNR the case search turned up, if it ran."""
    found = prior.get("courtsearch")
    rows = ((found.raw or {}).get("results") or []) if found and found.raw else []
    for row in rows:
        if row.get("cnr"):
            return row["cnr"]
    return None


def _dins_from(prior: dict) -> list[str]:
    """Every DIN the directors list turned up, if it ran.

    Written as a function because the inline comprehension this replaces had
    a latent crash: the `if prior.get("dirs")` guard sits AFTER the iterable
    expression in a comprehension, so `prior.get("dirs").raw` was evaluated
    before the guard could reject a missing finding. With `dirs` absent —
    deselected, or a wave that reordered — it raised AttributeError, which
    `_run_one` caught as "Unexpected error" and recorded UNAVAILABLE. That
    reports an adapter crash when the truth is simply that no DIN was
    available, and the two call for very different responses.
    """
    found = prior.get("dirs")
    if found is None or not found.raw:
        return []
    rows = found.raw.get("directors") or []
    return [d["din"] for d in rows if isinstance(d, dict) and d.get("din")]


def _one_line(check_id: str, data: dict) -> str:
    """The headline for a single-subject person check."""
    if check_id == "prefill":
        return str(data.get("name") or "No identity returned")
    if check_id == "epfomember":
        return f"UAN {data['uan']}" if data.get("uan") else "No UAN returned"
    if check_id == "footprint":
        # ACCOUNTS, not platforms checked. The list holds every platform
        # the source looked at, including the ones with no account and
        # the ones it could not reach, so its length would report
        # "18 accounts found" for a number that has eight.
        rows = [p for p in (data.get("platforms") or []) if isinstance(p, dict)]
        found = sum(1 for p in rows if p.get("present") is True)
        unchecked = sum(1 for p in rows if p.get("present") is None)
        if not rows:
            return "No online presence returned"
        return (f"{found} of {len(rows) - unchecked} platforms"
                + (f", {unchecked} unchecked" if unchecked else ""))
    rows = data.get("employments") or []
    if not rows:
        return "No employment history returned"
    first = rows[0] if isinstance(rows[0], dict) else {}
    employer = (first.get("establishment_name") or first.get("employer_name")
                or first.get("establishment") or first.get("employer"))
    # The EMPLOYER, not a count. "3 employment record(s)" is a number
    # about our parsing; the name of where somebody works is the finding.
    if employer and len(rows) == 1:
        return str(employer)
    if employer:
        return f"{employer} + {len(rows) - 1} more"
    return f"{len(rows)} employment record(s)"


def _subjects(raw: str | None, fallback: str | None = None) -> list[str]:
    """The list of mobile numbers a person-level check runs against.

    ONE CHECK, MANY PEOPLE. A company with five directors is five
    lookups, and an analyst should enter five numbers rather than run the
    same check five times and lose which answer belonged to whom.

    Stored in the existing `vendor_check_inputs` row — one per line, or
    comma separated, whichever the analyst typed. No schema change: the
    column is already Text and already unique on (vendor, check, key).

    The splitting itself lives in `app.domain.validation`, which is also
    what the field validator and the form use. One definition, so the box
    cannot accept a value this would send differently — the mismatch that
    had SSL being told one domain while the screen showed another.
    """
    return split_subjects(
        (raw or "").strip() or (fallback or "").strip()
    )


def _director_names(prior: dict) -> list[str]:
    """The board, for the LegalCheck submit.

    Sent as `subject.directors` so the provider can tell two companies of
    the same name apart by who runs them. Same guard order as `_dins_from`
    above, for the same reason: `dirs` may not have run.
    """
    found = prior.get("dirs")
    if found is None or not found.raw:
        return []
    rows = found.raw.get("directors") or []
    return [str(d["name"]).strip() for d in rows
            if isinstance(d, dict) and not is_blank(d.get("name"))]


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

    #: False while the provider's background download/extraction is still
    #: running. Unlocking is ASYNCHRONOUS — the POST returns in
    #: milliseconds, the documents land ten to thirty minutes later, and
    #: until they do the provider answers filings and extractions with
    #: nothing. Read by the checks that depend on those documents so an
    #: unfinished job is never reported as a vendor with no filings.
    documents_ready: bool = True
    #: The stage the provider last reported, for the note on those rows.
    refresh_stage: str | None = None

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
        self.vision = vision_mod.VisionProvider(self.settings, spend=self.spend)
        self.gridlines = gl_mod.GridlinesProvider(self.settings, spend=self.spend)

    def close(self) -> None:
        for provider in (self.filesure, self.whoisxml, self.archive,
                         self.finagg, self.ecourts, self.vision,
                         self.gridlines):
            provider.close()

    # =================================================================

    def run(self, vendor: Vendor, *, only: list[str] | None = None) -> RunResult:
        """Run the vendor's selection, or only the checks named in ``only``.

        ``only`` EXISTS BECAUSE RE-RUNNING COSTS MONEY.

        Nothing here skips a check that already has a result — it runs
        what it is given and `_persist` increments `attempts`. That is
        correct for a deliberate re-run, and catastrophic for a "run more
        checks" control on the findings screen, which would silently
        re-call and re-bill the entire selection every time an analyst
        added one more. On a full MCA selection that is upwards of ₹40 a
        click, with nothing on screen to say so.

        So the findings screen passes the DELTA, and only the delta is
        called. Prerequisites are still expanded, because a new check
        that needs `master` must get it — but one already on file is not
        bought twice.
        """
        result = RunResult(vendor_id=vendor.id, spend=self.spend)
        selected = expand_selection(list(vendor.selected or []))

        if only is not None:
            wanted = expand_selection([c for c in only if c in selected])
            # Prerequisites ALREADY ON FILE are dropped rather than
            # re-bought. `master` fetched an hour ago is still `master`.
            already = {
                row.check_id for row in vendor.checks
                if row.status in ("pass", "warn", "fail")
            }
            selected = [c for c in wanted if c in only or c not in already]
            self._audit(
                vendor.id, "RUN_PARTIAL",
                f"Running {len(selected)} check(s) only: "
                f"{', '.join(selected) or 'none'}. "
                f"{len(already)} already on file were not re-run, and not "
                f"re-charged.",
            )

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

        # --- NOTHING IS HELD. EVERY SELECTED CHECK GETS ITS CALL. --------
        #
        # There used to be a hold step here. When a provider had
        # refused anybody recently, every check against it
        # was refused LOCALLY, free and instantly, with that provider's
        # own sentence attached. The idea was that one analyst meets the
        # error and nobody after them waits on a call that cannot
        # succeed.
        #
        # REMOVED, 7 Nov 2026, on the product owner's instruction, and
        # the live evidence was decisive. Gridlines refused ONE of its
        # five products — `FORBIDDEN_ACCESS: Credential does not have
        # access to this product` on address-lookup — while prefill,
        # digital-footprint and fetch-uan all returned 200 in the same
        # second. The hold turned that into five dead checks on every
        # subsequent run, and kept them dead, because nothing was left
        # to discover that four of them worked.
        #
        # Scoping the refusal more narrowly fixed that one case. It does
        # not fix the shape of the mistake: a cache of "this will fail"
        # is a prediction, and this platform's entire argument is that a
        # prediction must never stand in for an examination. "We did not
        # ask, because last time the answer was no" is exactly the kind
        # of unexamined-looking-like-clean that everything else here is
        # built to prevent.
        #
        # The cost of being wrong is not symmetrical either. A refused
        # call is rejected BEFORE billing — a 401, 402 or 403 charges
        # nothing — so the hold was saving latency, not money, and
        # paying for it with checks that could not recover on their own.
        #
        # Outages are still RECORDED (`_settle_provider_state` below)
        # and still shown: `/api/providers` reports what is refusing us
        # and why, in the provider's own words, so an analyst sees it
        # before they wait and somebody can go and pay the invoice. It
        # is information now, not a gate.
        self._audit(
            vendor.id, "RUN_NO_HOLD",
            f"{len(runnable)} checks will all be called. Provider refusals "
            f"are recorded and shown, never used to skip a call.",
            actor="system",
        )

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

        self._settle_provider_state(vendor, result)

        self._persist(vendor, result)
        self._audit(
            vendor.id, "RUN_COMPLETE",
            f"{result.examined} examined, {len(result.skipped)} not examined · "
            f"₹{self.spend.paisa / 100:.2f} + {self.spend.credits} credits",
            actor="system",
        )
        return result

    # =================================================================
    # Contact person — personal records
    # =================================================================

    #: The value sent to Gridlines in every `consent` field.
    #:
    #: A constant, but NOT a hardcoded assertion: it is only ever reached
    #: through `_person_consent`, which refuses to return it without
    #: either a recorded reference or an analyst attestation written to
    #: the audit log first. The difference is the whole point — when
    #: somebody asks on what basis a person's PAN was pulled, the answer
    #: is a name and a timestamp rather than a line of source.
    _CONSENT_GIVEN = "Y"

    def _person_consent(self, check_id: str, vendor: Vendor,
                        consent_ref: str) -> str | None:
        """The consent value for a Gridlines call, or None to refuse.

        SOFT GATE. A reference is not required; proceeding without one is
        allowed and RECORDED. What is never allowed is calling with
        nobody behind the claim.

        Hard gate mode (`VBC_GRIDLINES_CONSENT_SOFT_GATE=false`) turns the
        warning into a refusal, for a client whose policy needs the
        document on file before the call rather than after.
        """
        reference = (consent_ref or "").strip()
        if reference:
            self._audit(
                vendor.id, "PERSON_CHECK_CONSENT",
                f"{check_id}: consent recorded — {reference}. The contact "
                f"number's personal records were read on that basis.",
            )
            return self._CONSENT_GIVEN

        if not self.settings.gridlines_consent_soft_gate:
            return None

        self._audit(
            vendor.id, "PERSON_CHECK_CONSENT_UNVERIFIED",
            f"{check_id}: run with NO consent reference. This check reads a "
            f"named individual's personal records, and the analyst who ran "
            f"it attested that consent exists without citing it. Recorded "
            f"so the basis can be produced if it is ever asked for.",
        )
        return self._CONSENT_GIVEN

    def _run_person_check(self, check_id: str, vendor: Vendor,
                          get, prior: dict) -> Finding:
        """The five Gridlines checks — ONE CHECK, MANY PEOPLE.

        A company with five directors is five lookups, and they belong in
        one finding: run separately, the analyst ends up with five rows
        and no way to tell which answer belonged to whom.

        So each subject is called in turn and the results are kept as a
        LIST on one `vendor_checks` row, every entry tagged with the
        number it came from. The primary key is untouched, scoring is
        untouched (these feed nothing), and the facts layer already
        renders tables.

        THE LOOP STOPS ON AN ACCOUNT REFUSAL. A 402 on the second of five
        numbers means the next three will fail identically; carrying on
        would spend nothing but would turn one clear "top the account up"
        into five confusing failures.
        """
        gl = self.gridlines
        consent_ref = str(get("consentRef", "") or "").strip()
        consent = self._person_consent(check_id, vendor, consent_ref)
        if consent is None:
            return Finding(
                check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                "No consent reference",
                "This check reads named individuals' personal records and "
                "the consent gate is set to refuse without a reference. "
                "Record how consent was obtained, then run it. No call was "
                "made and nothing was charged.",
            )

        basis = (f"Consent reference: {consent_ref}." if consent_ref
                 else "No consent reference was recorded; the analyst "
                      "attested that consent exists.")
        personal = ("This is personal data about individuals — the holders "
                    "of these numbers — not a company record.")

        # ---- who are we running against --------------------------------
        if check_id == "emphistory":
            # THE UAN IS TYPED. NOTHING IS INHERITED.
            #
            # This used to fall back to whatever `epfomember` had
            # returned, and that made one endpoint's parse failure take
            # a second, working endpoint down with it: fetch-uan came
            # back in a shape this adapter could not read, so employment
            # history never ran at all, though it needed nothing from
            # it. The provider's own API has no such dependency —
            # fetch-by-uan wants a UAN and nothing else.
            #
            # `uan` is a required input in the catalog now, so a blank
            # is caught by the gate before a run starts. This stays as
            # the backstop for any caller that is not the form.
            pairs = [(None, u) for u in _subjects(str(get("uan", "") or ""))]
            if not pairs:
                return Finding(
                    check_id, CheckStatus.SKIPPED_MISSING_INPUT, "No UAN",
                    "This check needs at least one UAN — twelve digits, "
                    "one per line for several people. The call was never "
                    "made and nothing was charged.",
                )
        else:
            numbers = _subjects(str(get("mobile", "") or ""),
                                vendor.contact_mobile)
            if not numbers:
                return Finding(
                    check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                    "No contact number",
                    "This check needs at least one mobile number — one per "
                    "line for several people. Add one on the vendor record "
                    "or type them here. The call was never made and nothing "
                    "was charged.",
                )
            pairs = [(n, None) for n in numbers]

        # ---- call, once per subject ------------------------------------
        price = {
            "prefill": self.settings.gridlines_prefill_paisa,
            "footprint": self.settings.gridlines_footprint_paisa,
            "epfomember": self.settings.gridlines_epfo_member_paisa,
            "emphistory": self.settings.gridlines_employment_paisa,
        }[check_id]

        rows: list[dict] = []
        blocked: ProviderRejected | None = None
        for mobile, uan in pairs:
            label = mobile or uan or "—"
            # BOTH are kept on the row, not just whichever one was the
            # input. Employment history is called with a UAN, but the
            # analyst knows the directors by their numbers, and a table of
            # five UANs with no numbers beside them does not say whose
            # employment history is whose.
            who = {"subject": label, **({"uan": uan} if uan else {})}
            try:
                data = self._one_person_call(
                    gl, check_id, consent=consent, get=get,
                    mobile=mobile, uan=uan, vendor=vendor,
                )
                rows.append({**who, "ok": True, "data": data})
            except (ProviderOutOfCredits, ProviderAccountBlocked) as exc:
                # Every remaining subject would fail identically. Stop,
                # and let the outage machinery say so once.
                blocked = exc
                rows.append({**who, "ok": False, "error": str(exc)})
                break
            except (ProviderParseGap, ProviderError, ValueError) as exc:
                # ONE subject failing must not lose the other four. The
                # row records which, and why, and the status below counts
                # them honestly.
                #
                # AND IT KEEPS THE PAYLOAD. `ProviderParseGap` carries
                # the response precisely so the runner can persist it —
                # "a response we have paid for and cannot read is the
                # one artefact needed to fix the adapter". This loop
                # stored only the error string, so the first real EPFO
                # response was bought, found unreadable, and thrown
                # away: the stored row had an error and an empty
                # `_raw_keys`, and the only way to see the shape was to
                # pay for the call again.
                failed = {**who, "ok": False,
                          "error": f"{type(exc).__name__}: {exc}"}
                unread = getattr(exc, "payload", None)
                if unread is not None:
                    failed["unreadable_payload"] = unread
                rows.append(failed)

        raw = {"subjects": rows, "subject_count": len(pairs)}
        ok = [r for r in rows if r["ok"]]
        failed = [r for r in rows if not r["ok"]]
        cost = price * len(ok)

        if blocked is not None:
            return Finding(
                check_id, CheckStatus.UNAVAILABLE,
                "Provider refused this account",
                f"{blocked} Stopped after {len(ok)} of {len(pairs)}; the "
                f"remaining lookups would have failed identically.",
                raw=raw, cost_paisa=cost, error=str(blocked),
                account_blocked=str(blocked),
                account_blocked_status=getattr(blocked, "status", None),
                facts=factsets.person_subjects(check_id, raw),
            )

        if not ok:
            return Finding(
                check_id, CheckStatus.UNAVAILABLE,
                f"0 of {len(pairs)} returned",
                f"No lookup succeeded. Nothing here is a finding about "
                f"anybody — the calls did not produce an answer. {basis}",
                raw=raw, cost_paisa=cost,
                error=failed[0]["error"] if failed else None,
                facts=factsets.person_subjects(check_id, raw),
            )

        status = CheckStatus.PASS if not failed else CheckStatus.WARN
        value = (f"{len(ok)} of {len(pairs)} returned"
                 if len(pairs) > 1 else _one_line(check_id, ok[0]["data"]))
        detail = (
            (f"{len(failed)} lookup(s) did not return; those people are "
             f"NOT cleared, they were not examined. " if failed else "")
            + f"{personal} {basis}"
        )
        return Finding(
            check_id, status, value, detail,
            raw=raw, cost_paisa=cost,
            facts=factsets.person_subjects(check_id, raw),
        )

    def _one_person_call(self, gl, check_id: str, *, consent: str, get,
                         mobile: str | None, uan: str | None,
                         vendor: Vendor) -> dict:
        """One subject, one provider call."""
        if check_id == "prefill":
            return gl.mobile_prefill(
                mobile, consent=consent,
                first_name=str(get("firstName", "") or ""),
                last_name=str(get("lastName", "") or ""),
            )
        if check_id == "footprint":
            return gl.digital_footprint(
                mobile, consent=consent, email=str(get("email", "") or ""),
            )
        # `personaddr` is not in the catalog any more — Gridlines
        # refuses that product for this account — so the runner never
        # reaches this branch. `address_lookup` is kept on the provider
        # with its verified endpoint and body, so restoring the check is
        # one CheckDefinition away if the entitlement is ever bought.
        if check_id == "epfomember":
            return gl.epfo_member(
                mobile, consent=consent,
                pan=str(get("pan", vendor.pan or "") or "") or None,
            )
        return gl.employment_history(uan, consent=consent)

    # =================================================================
    # Provider account state
    # =================================================================

    def _hold_blocked_providers(
        self, runnable: list[str], result: RunResult
    ) -> list[str]:
        """DISABLED. Returns everything it is given.

        Kept as a named no-op rather than deleted so that the decision
        is visible where the behaviour used to be, and so the three
        tests that pin it fail loudly if anybody reinstates holding by
        accident.

        What it did: refused, locally and for free, every check against
        a provider that had recently refused somebody — with that
        provider's own sentence attached.

        Why it is gone, 7 Nov 2026, on the product owner's instruction:
        a cache of "this will fail" is a PREDICTION, and this platform's
        whole argument is that a prediction may never stand in for an
        examination. Live evidence made it concrete — Gridlines refused
        one of five products while three others returned 200 in the same
        second, and the hold turned that into five permanently dead
        checks with nothing left to discover otherwise.

        Refusals are still recorded and still shown. They are
        information for a person, not a gate in front of a call.
        """
        return runnable

    def _settle_provider_state(self, vendor: Vendor, result: RunResult) -> None:
        """Open, refresh or close outages from what this run just saw.

        Deferred to here rather than done inside ``_run_one`` because that
        runs in a thread pool and the Session is not thread-safe. Nothing
        is visible to anyone else until this run commits, so waiting costs
        nothing.

        A SUCCESSFUL call clears an open outage, which is what makes
        topping up a balance sufficient on its own: the probe gets through
        and the pool reopens for everybody with no second action.

        Everything here is keyed on the POOL — ``(provider, product)`` —
        so a dead WhoisXML product neither blocks nor is cleared by the
        WhoisXML products that are still answering.
        """
        blocked_now: dict[tuple[str, str], Finding] = {}
        answered: set[tuple[str, str]] = set()

        for finding in result.findings:
            # A REFUSAL is scoped by what it says, not by the wallet it
            # would have spent from — see `_outage_scope`. A successful
            # call still clears the wallet pool it bills to.
            scope = (_outage_scope(finding.check_id,
                                   finding.account_blocked_status)
                     if finding.account_blocked
                     else _billing_scope(finding.check_id))
            if scope is None:
                continue
            if finding.account_blocked:
                blocked_now.setdefault(scope, finding)
            elif finding.status.was_examined:
                # Proof the pool works: the provider answered about this
                # vendor. A 404 does not qualify — it never reaches here —
                # and neither does a parse gap, which is our fault and
                # leaves the account's standing unknown.
                answered.add(scope)

        for (provider, product), finding in blocked_now.items():
            provider_state.record_outage(
                self.session,
                provider,
                product=product,
                message=finding.account_blocked or "",
                http_status=finding.account_blocked_status,
                check_id=finding.check_id,
                vendor_id=vendor.id,
                source="run",
            )

        # A pool that both answered and refused in the same run stays
        # blocked: the refusal is the newer fact about the account, and a
        # cached or free endpoint answering proves nothing about the paid
        # balance.
        for provider, product in answered - set(blocked_now):
            if provider_state.clear_outage(
                self.session, provider, product=product,
                reason=f"a successful call on {vendor.id}",
            ):
                label = f"{provider}/{product}" if product else provider
                self._audit(
                    vendor.id,
                    "PROVIDER_RECOVERED",
                    f"{label} answered again during this run; its checks are "
                    f"available to everyone once more.",
                )

    # =================================================================
    # One check
    # =================================================================

    def _run_one(
        self, check_id: str, vendor: Vendor, cin: str | None, inputs: dict,
        master: dict | None, result: RunResult, prior: dict | None = None,
    ) -> Finding:
        """Isolate every failure so one bad source cannot stop the rest."""
        try:
            return self._flag_thin(
                self._dispatch(check_id, vendor, cin, inputs, master, result, prior or {})
            )
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
        except (ProviderOutOfCredits, ProviderAccountBlocked) as exc:
            # BEFORE ProviderRejected, which is their parent class. They sat
            # after it until 24 Oct 2026, so Python matched the parent first
            # and this branch never ran once — an empty wallet reported
            # "Provider rejected the call", which is exactly the wording
            # whose absence cost an hour diagnosing a 40-paisa shortfall on
            # the eCourts account. The comment claiming the order was right
            # sat directly above the unreachable code.
            #
            # These two say nothing about the vendor and everything about
            # OUR account, so they are true for every other check against
            # the same provider. Recorded once, here, so the next analyst
            # is told before they select anything instead of discovering it
            # the same way.
            out_of_credits = isinstance(exc, ProviderOutOfCredits)
            return Finding(
                check_id, CheckStatus.UNAVAILABLE,
                "Provider account out of credits" if out_of_credits
                else "Provider refused this account",
                f"{exc} Nothing about this vendor was examined, and this is "
                f"NOT a clean result — the check simply never ran. Every "
                f"other check from the same source is now marked unavailable "
                f"until the account is working again.",
                error=str(exc),
                account_blocked=str(exc),
                account_blocked_status=getattr(exc, "status", None),
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
        def get(key: str, default: Any = "") -> Any:
            """One stored input, falling back when it is BLANK as well as absent.

            This was `inputs.get(check_id, {}).get(key, default)`, and
            `dict.get` only applies its default when the key is MISSING. A
            key present with an empty string returned the empty string,
            and every fallback below is written `get("x", vendor.y or "")`
            — so the fallback silently stopped working the moment a value
            was stored and then cleared.

            `_missing_inputs` has no such hole: it tests `if not value and
            param.from_vendor`. So the two halves disagreed in the worst
            possible way —

                gate   sees aspiremgs.co.in  -> nothing is missing, run it
                call   sees ""               -> sends an empty domain

            — and the run went out and came back `HTTP 400: Input correct
            domain`, having passed every check that was supposed to stop
            exactly that. Seen live on vendor 234481.

            Whitespace counts as blank for the same reason: a space is not
            an answer, and no provider accepts one.
            """
            value = inputs.get(check_id, {}).get(key)
            if value is None:
                return default
            if isinstance(value, str) and not value.strip():
                return default
            return value
        fs, wx, ar, fa = self.filesure, self.whoisxml, self.archive, self.finagg
        ec = self.ecourts
        # The name every provider's answer is checked back against. A GSTIN
        # or CIN typed one character wrong resolves cleanly and returns a
        # real, healthy registration belonging to somebody else; nothing
        # else in the pipeline looks for that.
        subject = vendor.legal_name or vendor.name

        # The unlock's document job is asynchronous and takes 10–30 minutes.
        # These three checks read what it produces, so running them before
        # it finishes returns an empty answer that is indistinguishable from
        # a company with no filings and no filed accounts. UNAVAILABLE is
        # excluded from `was_examined`, so this can never become a positive
        # in SCAN or the risk ledger — which an empty-but-PASS result could.
        if (result is not None and not result.documents_ready
                and check_id in self._NEEDS_DOCUMENTS):
            stage = result.refresh_stage or "in progress"
            return Finding(
                check_id, CheckStatus.UNAVAILABLE, "Documents not ready",
                f"The company unlock is complete but the provider is still "
                f"downloading and extracting its documents (stage: {stage}); "
                f"that takes 10–30 minutes. The source returns nothing for "
                f"this check until it finishes, so this is recorded as "
                f"unexamined — NOT as a company with none. Re-run this check "
                f"shortly; the unlock is not charged again.",
                facts=factsets.refresh_pending(check_id, stage),
            )

        # ---- MCA ----------------------------------------------------
        if check_id == "ustatus":
            status = fs.unlock_status(cin or "")
            return Finding(
                check_id, CheckStatus.PASS,
                "Unlocked" if status.unlocked else "Not unlocked",
                f"Expires {status.expires_at}." if status.expires_at
                else "No active unlock on file.",
                raw=status.__dict__,
                facts=factsets.unlock_status(status.__dict__),
            )

        if check_id == "refresh":
            if not cin:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No CIN.")
            # ₹150 and a 48-hour cooldown — by a wide margin the most
            # expensive way to get nothing in this system. Refused before
            # the call, not diagnosed after it.
            cooling, until = self._cooling_down(
                vendor.id, check_id, self.settings.filesure_update_cooldown_hours)
            if cooling:
                raise PaidCallRefused(
                    f"This company was updated from MCA too recently — the "
                    f"source's 48-hour cooldown lifts {_human_date(until)} "
                    f"{until:%H:%M} UTC. Calling now bills ₹150 and returns "
                    f"the same data."
                )

            triggered = fs.trigger_update(cin)
            triggered["_fetched_at"] = datetime.now(timezone.utc).isoformat()

            # The data is NOT fresh when trigger_update returns — it answers
            # `pending`. Polling is free. Reading master data without it
            # means reading the stale values just paid to replace.
            budget = self.settings.filesure_update_poll_budget_seconds
            interval = self.settings.filesure_update_poll_interval_seconds
            deadline = time.monotonic() + budget
            state = triggered
            polls = 0
            while time.monotonic() < deadline:
                status_text = str(state.get("status") or "").lower()
                if status_text in ("completed", "complete", "done", "success", "failed"):
                    break
                time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
                state = fs.update_status(cin)
                polls += 1

            final = str(state.get("status") or "unknown").lower()
            done = final in ("completed", "complete", "done", "success")
            payload = {"trigger": triggered, "status": state, "polls": polls,
                       "_fetched_at": triggered["_fetched_at"]}
            return Finding(
                check_id,
                CheckStatus.PASS if done else CheckStatus.WARN,
                "Company data refreshed" if done else f"Update {final}",
                (f"Completed after {polls} poll(s). Re-run the company master "
                 f"check to read the refreshed record."
                 if done else
                 f"Charged and still running after {polls} poll(s) — the poll "
                 f"budget ({budget:.0f}s) ran out, not the job. It continues "
                 f"on the source's side; re-run the company master check "
                 f"later rather than paying for a second update."),
                raw=payload,
                facts=factsets.company_update(triggered, state, polls=polls, done=done),
            )

        if check_id == "master":
            if not cin:
                return Finding(check_id, CheckStatus.FAIL, "Not a registered company",
                               "No CIN — MCA holds no record for this entity.")
            # idType TIGHTENS the provider's validation, so sending one
            # that contradicts the identifier is worse than sending none:
            # an LLPIN submitted as "cin" comes back 400 INVALID_CIN and
            # the LLP cannot be audited at all. That was a real bug once.
            #
            # The form now derives this field from what was typed, so it
            # usually agrees. This is the guard for when it does not — a
            # value saved before the identifier was edited, an older row,
            # or a shape we do not recognise. Where the stored choice and
            # the actual identifier disagree, send NOTHING and let the
            # provider work it out, which is what it does well.
            #
            # "Auto-detect" is no longer offered but is still honoured:
            # rows written before it was removed still carry it.
            id_type = str(get("idType", "") or "").strip().lower()
            if id_type in ("", "auto-detect", "auto"):
                id_type = None
            elif id_type != detect_id_type(cin):
                self._audit(
                    vendor.id, "ID_TYPE_IGNORED",
                    f"Stored idType '{id_type}' does not match the shape of "
                    f"{cin}; sent without one so the provider can detect it.",
                )
                id_type = None

            payload, record_meta = fs.company_master_with_meta(cin, id_type)
            facts = fs_mod.normalise_master(payload, meta=record_meta)
            active = str(facts.get("status", "")).lower() == "active"
            renamed = bool(facts.get("name_history"))

            # The record's age, stated once and plainly.
            #
            # This used to read "⚠ MCA record last refreshed N days ago —
            # this status is as of then, not today" when the record was
            # old. Accurate, but it put a warning about OUR SOURCE on a
            # line a client reads as a verdict on their vendor. Same
            # neutral phrasing now whether the record is a week old or two
            # years old; the reader can judge the number.
            age = facts.get("record_age_days")
            age_note = f" · record refreshed {age} days ago" if age is not None else ""

            return Finding(
                check_id,
                CheckStatus.PASS if active else CheckStatus.WARN,
                f"{facts.get('status', 'Unknown')} · {facts.get('cin')}",
                # Through the same formatters the detail panel uses. These
                # were raw: the summary line read "Incorporated 1973-05-08 ·
                # paid-up ₹13532.54 Cr" directly above a panel saying
                # "08 May 1973" and "₹13,532.54 Cr" — one screen, one fact,
                # two spellings.
                f"Incorporated {_human_date(facts.get('incorporated_on')) or '—'} · "
                f"{facts.get('class_of_company')} · paid-up "
                f"{_crore(facts.get('paidup_capital')) or '—'}"
                + (" · company has been renamed previously" if renamed else "")
                + age_note,
                raw={"facts": facts, "payload": payload},
                facts=factsets.master(facts, subject=subject),
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
                # Derived from the master payload — no call of its own, so
                # no payload of its own. Named explicitly so the row points
                # at the evidence instead of looking like it lost it.
                raw={"directors": directors, "_derived_from": "master"},
                facts=factsets.directors(directors),
            )

        if check_id == "charges":
            if not master:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No master data on file.")
            charges = fs_mod.normalise_charges(master.get("payload", master))
            open_charges = charges["open"]
            if not open_charges:
                return Finding(check_id, CheckStatus.PASS, "No open charges",
                               f"{len(charges['closed'])} historical charges, all satisfied.",
                               raw=charges, facts=factsets.charges(charges))
            return Finding(
                check_id, CheckStatus.WARN,
                f"{len(open_charges)} open charge · {_crore(charges['open_total'])}",
                "; ".join(
                    f"{c['holder']} {_crore(c['amount']) or '—'} "
                    f"created {_human_date(c['created_on']) or '—'}, not satisfied"
                    for c in open_charges
                ),
                raw=charges,
                facts=factsets.charges(charges),
            )

        if check_id == "resolve":
            candidates, resolve_payload = fs.resolve_company(
                get("q", vendor.name), state=get("state"), city=get("city"),
                limit=int(get("limit", 10) or 10),
            )
            if not candidates:
                return Finding(check_id, CheckStatus.WARN, "No CIN found",
                               "No MCA registration traced — consistent with a "
                               "proprietorship or partnership firm.",
                               raw={"candidates": [], "payload": resolve_payload},
                               facts=factsets.resolve_candidates([], subject=subject))
            top = candidates[0]
            strong = [c for c in candidates if (c.get("matchScore") or 0) >= 0.9]
            if len(strong) > 1:
                return Finding(
                    check_id, CheckStatus.WARN, f"{len(strong)} strong matches",
                    "More than one company matches this name closely. The "
                    "ambiguity is surfaced rather than resolved automatically — "
                    "auditing the wrong company is worse than auditing none.",
                    raw={"candidates": candidates, "payload": resolve_payload},
                    facts=factsets.resolve_candidates(candidates, subject=subject),
                )
            return Finding(check_id, CheckStatus.PASS,
                           f"{top.get('cin')} · {top.get('company')}",
                           f"Match score {top.get('matchScore')}.",
                           raw={"candidates": candidates, "payload": resolve_payload},
                           facts=factsets.resolve_candidates(candidates,
                                                             subject=subject))

        if check_id == "filings":
            if not cin:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No CIN.")
            year = get("year")
            # 200 is the provider's ceiling, and one call costs ₹5 whatever
            # the limit — so the old default of 50 bought a quarter of the
            # data for the same money. `page` was never wired at all, which
            # meant page 1 was the only page anyone could ever reach.
            rows, meta, filings_payload = fs.filings(
                cin, form_id=get("formId", ""), year=int(year) if year else None,
                limit=min(int(get("limit", 200) or 200), 200),
                page=max(int(get("page", 1) or 1), 1),
            )
            if not rows:
                return Finding(check_id, CheckStatus.WARN, "No filings returned",
                               "MCA holds no filings matching this filter.",
                               raw={"rows": [], "meta": meta,
                                    "payload": filings_payload},
                               facts=factsets.filings([], meta))
            latest = rows[0]
            return Finding(
                check_id, CheckStatus.PASS, "Filings on record",
                f"Most recent {latest.get('formId')} filed "
                f"{_human_date(latest.get('dateOfFiling')) or '—'} · "
                f"{meta.get('total', len(rows))} total "
                f"(page limit honoured: {meta.get('limit')})",
                raw={"rows": rows, "meta": meta, "payload": filings_payload},
                facts=factsets.filings(rows, meta),
            )

        if check_id == "download":
            filing_id = get("filingId")
            if not cin or not filing_id:
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No filing selected",
                               "Pick a filing from the filing history first — "
                               "the download is by filing ID.")
            content = fs.download_filing(cin, filing_id)
            if not content:
                return Finding(check_id, CheckStatus.UNAVAILABLE, "Empty document",
                               "The source returned no bytes for this filing. "
                               "Recorded as unexamined, not as a missing filing.",
                               raw={"filingId": filing_id, "bytes": 0})

            # The PDF itself cannot go in JSONB and there is no document
            # store yet. A SHA-256 is kept so the file that was fetched can
            # still be IDENTIFIED later — which is most of what evidence
            # needs to do — and the gap is stated rather than implied.
            stored, note = self._keep_document(
                content, vendor.id, check_id, f"{filing_id}.pdf")
            digest = stored.sha256 if stored else hashlib.sha256(content).hexdigest()
            return Finding(
                check_id, CheckStatus.PASS,
                f"Document retrieved · {len(content):,} bytes",
                (f"SHA-256 {digest[:16]}… — stored and attached to this report."
                 if stored else
                 f"SHA-256 {digest[:16]}… — identified but NOT retained: {note}"),
                raw={
                    "filingId": filing_id, "cin": cin, "bytes": len(content),
                    "sha256": digest,
                    "stored": bool(stored),
                    "url": stored.url if stored else None,
                },
                facts=factsets.filing_document(
                    filing_id, len(content), digest,
                    href=stored.url if stored else None, note=note),
            )

        if check_id == "frefresh":
            if not cin:
                return Finding(check_id, CheckStatus.SKIP, "N/A", "No CIN.")
            # BEFORE the call, never after: this endpoint bills on request
            # and serves the cache while cooling down, so a cooldown read
            # from the response is a cooldown discovered after paying ₹5.
            cooling, until = self._cooling_down(
                vendor.id, check_id, self.settings.filesure_filings_refresh_cooldown_hours)
            if cooling:
                raise PaidCallRefused(
                    f"Filings were last refreshed too recently — the source's "
                    f"cooldown lifts {_human_date(until)} "
                    f"{until:%H:%M} UTC. Calling now bills ₹5 and returns the "
                    f"same cached filings."
                )
            data = fs.refresh_filings(cin)
            data["_fetched_at"] = datetime.now(timezone.utc).isoformat()
            cached = bool(data.get("fromCache") or data.get("from_cache"))
            return Finding(
                check_id,
                CheckStatus.WARN if cached else CheckStatus.PASS,
                "Served from cache" if cached else "Refresh requested",
                ("Billed, but no fresh pull from MCA happened — the source "
                 "returned its cache. The filings on file are no newer than "
                 "they were."
                 if cached else
                 "MCA filings refresh queued. Re-run the filing history check "
                 "afterwards to read the new data."),
                raw=data,
                facts=factsets.refresh_receipt(data, what="Filings refresh",
                                               cached=cached),
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
                (f"Revenue {_crore(revenue)}" if revenue else "Filed financials"),
                f"{facts['scope']} · FY ending "
                f"{_human_date(facts['period_end']) or '—'} · net worth "
                f"{_crore(facts['net_worth']) or '₹0'}"
                + (f" · filing gaps in {gaps}" if gaps else ""),
                # Was ``raw=facts``: the normaliser's output was stored and
                # the provider's own response thrown away. A parse defect
                # here could not be detected afterwards, let alone corrected,
                # because the bytes it misread were gone. Both are kept now,
                # under the same two keys the master check uses.
                raw={"facts": facts, "payload": data},
                facts=factsets.financials(facts),
            )

        if check_id == "dprof":
            dins = [get("din")] if get("din") else _dins_from(prior)
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
            # ENDED directorships are counted too. The payload carries
            # them in a second block, `mcaSignatoryCessationMasterHistory`,
            # which this summary ignored — so a director who had resigned
            # from two companies was described as holding one
            # directorship, full stop. A role someone left, at a company
            # that later failed, is exactly what this check is bought for.
            ended_elsewhere = sum(
                len(p.get("mcaSignatoryCessationMasterHistory") or [])
                for p in profiles
            )
            detail = (
                f"{active_elsewhere} active "
                f"{'directorship' if active_elsewhere == 1 else 'directorships'}"
            )
            detail += (
                f" and {ended_elsewhere} ended"
                if ended_elsewhere else " and none ended"
            )
            detail += ", across all profiles."
            return Finding(
                check_id, CheckStatus.PASS,
                f"{len(profiles)} "
                f"{'profile' if len(profiles) == 1 else 'profiles'} retrieved",
                detail,
                raw={"profiles": profiles},
                facts=factsets.director_profiles(profiles),
            )

        if check_id == "dresolve":
            query = get("q")
            if not query.strip():
                return Finding(check_id, CheckStatus.SKIPPED_MISSING_INPUT,
                               "No name to resolve",
                               "A DIN lookup needs a director's name as filed "
                               "with MCA; an informal or shortened name will "
                               "not match.")
            candidates = fs.resolve_director(query, limit=int(get("limit", 10) or 10))
            if not candidates:
                return Finding(check_id, CheckStatus.WARN, "No DIN found",
                               f"MCA holds no director matching '{query}'. A "
                               f"person can hold no DIN and still be an "
                               f"officer, so this is a gap, not a clearance.",
                               raw={"candidates": candidates},
                               facts=factsets.director_candidates(candidates, query=query))

            # totalDirectorshipCount is free and is the one genuinely
            # interesting number this endpoint returns: an implausible board
            # count is the classic mass-director / dummy-director pattern.
            alarm = self.settings.filesure_directorship_alarm
            loaded = [c for c in candidates
                      if (c.get("totalDirectorshipCount") or 0) >= alarm]
            top = candidates[0]
            # `fullName`, not `name` — the latter is not a key this endpoint
            # returns, and the summary line read "None 0, None 0, None 10".
            # `status` is the field that actually separates these people: a
            # search for one name returns several DINs, of which typically
            # one is Approved and holding directorships and the rest are
            # Lapsed and holding none.
            live = [c for c in candidates
                    if str(c.get("status") or "").lower() == "approved"
                    and (c.get("totalDirectorshipCount") or 0)]
            return Finding(
                check_id,
                CheckStatus.WARN if (len(candidates) > 1 or loaded) else CheckStatus.PASS,
                f"{top.get('din')} · {top.get('fullName') or top.get('name')}"
                if len(candidates) == 1 else f"{len(candidates)} possible matches",
                (f"{len(loaded)} of these sit on {alarm}+ boards — the "
                 f"mass-director pattern. Confirm which person is meant "
                 f"before a DIN is used downstream."
                 if loaded else
                 (f"One is active: DIN {live[0].get('din')}, "
                  f"{live[0].get('totalDirectorshipCount')} directorships "
                  f"including {(factsets.company_names(live[0]) or ['—'])[0]}. "
                  f"The rest are lapsed."
                  if len(live) == 1 and len(candidates) > 1 else
                  " · ".join(
                      f"{c.get('din')} {c.get('status') or '?'} "
                      f"({c.get('totalDirectorshipCount') or 0} boards)"
                      for c in candidates[:5]))),
                raw={"candidates": candidates},
                facts=factsets.director_candidates(
                    candidates, query=query, alarm=alarm),
            )

        if check_id == "dcontact":
            # Blank DIN means "every director found on the company", which is
            # a ₹50 unlock EACH plus the ₹0.05 read — ₹1,250 for a 25-person
            # board. Capped for the same reason ecourts_max_orders exists:
            # one ticked box must not become an unbounded bill.
            dins = ([get("din")] if get("din") else _dins_from(prior))
            dins = [d for d in dins if d][: self.settings.filesure_max_director_contacts]
            if not dins:
                return Finding(check_id, CheckStatus.SKIP, "N/A",
                               "No DIN available — run the directors list "
                               "first, or supply one.")
            contacts, unlocked_now = [], 0
            for din in dins:
                _, purchased = fs.ensure_director_unlocked(din)
                unlocked_now += 1 if purchased else 0
                record = fs.director_contact(din)
                record["din"] = din
                contacts.append(record)

            reachable = sum(1 for c in contacts if c.get("email") or c.get("mobile"))
            return Finding(
                check_id,
                CheckStatus.PASS if reachable else CheckStatus.WARN,
                f"{reachable} of {len(contacts)} contactable",
                (f"{unlocked_now} director unlock(s) purchased this run. "
                 f"Mobile numbers are returned masked by MCA."
                 if reachable else
                 "MCA holds no contact details for these directors — common "
                 "where filings were made through a practitioner."),
                raw={"contacts": contacts},
                facts=factsets.director_contacts(contacts),
            )

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
                facts=factsets.whois(data),
            )

        if check_id == "dwhois":
            data = wx.whois_current(get("domainName", vendor.domain or ""))
            age_days = data.get("age_days")
            years = round(age_days / 365.25, 1) if isinstance(age_days, int) else None

            # NOT REGISTERED IS THE ADVERSE ONE. A vendor quoting a
            # domain nobody owns is a finding; a young domain is not.
            if data.get("registered") is False:
                status = CheckStatus.FAIL
                value = "Not registered"
            elif years is None:
                # Registered, but the source gave no creation date. That
                # is a gap in the answer, not a clean result — saying
                # "domain age —" beside a green tick would be exactly
                # the thing this product refuses to do.
                status = CheckStatus.WARN
                value = "Registered · age unknown"
            else:
                status = CheckStatus.PASS if years >= 2 else CheckStatus.WARN
                value = f"Domain age {years} yrs"

            holder = data.get("registrant_name") or (
                "registrant redacted" if data.get("masked") else "registrant not given"
            )
            return Finding(
                check_id,
                status,
                value,
                f"Registered {data.get('created') or 'date not given'} · "
                f"{holder} · registrar {data.get('registrar') or 'not given'}"
                + (" · contacts redacted at the registry"
                   if data.get("masked") else ""),
                raw=data, credits=1,
                facts=factsets.whois_current(data),
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
                facts=factsets.reputation(data),
            )

        # ---- P · contact person — PERSONAL records · Gridlines --------
        #
        # The consent value sent to Gridlines comes from here and nowhere
        # else. `_person_consent` warns-and-records when no reference was
        # given, so the attestation is a named analyst rather than a
        # constant in the adapter. See app/providers/gridlines.py.
        if check_id in ("prefill", "footprint", "epfomember", "emphistory"):
            return self._run_person_check(check_id, vendor, get, prior)

        if check_id == "ssl":
            domain = get("domainName", vendor.domain or "")
            data = wx.ssl_certificate(domain)
            if not data.get("present"):
                return Finding(check_id, CheckStatus.FAIL, "No certificate",
                               "No SSL certificate served for this domain.", raw=data,
                               credits=1, facts=factsets.ssl(data, domain=domain))
            trusted = data.get("trusted_ca")
            return Finding(
                check_id,
                CheckStatus.PASS if trusted else CheckStatus.FAIL,
                "Valid SSL" if trusted else "Untrusted certificate",
                f"{data.get('issuer')} · valid to {data.get('valid_to')}"
                + (" · wildcard" if data.get("wildcard") else ""),
                raw=data, credits=1,
                # Expiry and host mismatch are raised as FLAGS, not as a
                # status. A certificate issued to a related host is a fact
                # about the evidence, and a parser does not get to decide it
                # makes the vendor adverse.
                facts=factsets.ssl(data, domain=domain),
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
                               "portfolio search would have been meaningless.", raw=data,
                               facts=factsets.reverse_whois(data))
            return Finding(check_id, CheckStatus.PASS,
                           f"{data['count']} domains, same owner",
                           f"Searched on '{data['term']}'. A varied portfolio is "
                           f"consistent with an agency; near-identical variants of "
                           f"one brand would suggest typosquatting.",
                           raw=data, credits=1,
                           facts=factsets.reverse_whois(data))

        if check_id == "shot":
            url = get("url", vendor.website or "")
            image = wx.screenshot(url, image_format=get("imageOutputFormat", "JPG"))
            return Finding(check_id, CheckStatus.PASS, "Screenshot captured",
                           f"{len(image)} bytes.", raw={"bytes": len(image)},
                           facts=factsets.screenshot(len(image), url or None))

        # ---- archive.org --------------------------------------------
        if check_id == "avail":
            data = ar.availability(get("url", vendor.domain or ""),
                                   timestamp=get("timestamp", ""))
            if not data["archived"]:
                return Finding(check_id, CheckStatus.FAIL, "Never archived",
                               "archived_snapshots is empty — no web presence on record.",
                               raw=data, facts=factsets.availability(data))
            return Finding(check_id, CheckStatus.PASS, "Archived",
                           f"Last captured {data.get('last_seen')}.", raw=data,
                           facts=factsets.availability(data))

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
                               "No archived snapshots at all.", raw=data,
                               facts=factsets.timeline(data))
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
                facts=factsets.timeline(data),
            )

        if check_id == "mentions":
            data = ar.mentions(get("q", vendor.name), rows=int(get("rows", 50) or 50))
            return Finding(check_id, CheckStatus.PASS, f"{data['found']} loose hits",
                           data["note"], raw=data, facts=factsets.mentions(data))

        if check_id == "usage":
            data = fs.account_usage()
            balance = (data.get("wallet") or {}).get("balancePaisa", 0)
            return Finding(check_id, CheckStatus.PASS,
                           f"Wallet {_paisa(balance)}", "Account usage retrieved.",
                           raw=data, facts=factsets.usage(data))

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
                # The entity-mismatch flag lives here. A GSTIN one character
                # wrong returns a real, active registration belonging to
                # someone else — PASS, clean detail line, wrong company.
                facts=factsets.gst(data, subject=subject),
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
            return Finding(check_id, status, value, detail, raw=data,
                           facts=factsets.gst_returns(data))

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
                # Two flags nothing else catches: a search term that drifted
                # from the vendor's legal name, and results that carry a CNR
                # and nothing else. Twenty index stubs currently read as
                # twenty cases found.
                facts=factsets.case_search(data, subject=subject),
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
                facts=factsets.hearings(data),
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
                # The payload carries every field twice — flattened, and
                # again inside court_case_data under camelCase names. The
                # reconciliation happens in the parser; the screen sees one
                # set of fields, not two spellings of the same case.
                facts=factsets.case_detail(data),
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
                # pdf_base64 stays in raw AND is now written to the document
                # store, so the link in the panel opens the actual order
                # rather than describing one. The base64 never reaches the
                # browser either way — 50 KB per order, and unreadable.
                facts=factsets.orders(
                    cnr, self._keep_orders(fetched, vendor.id, check_id),
                    generated=check_id == "courtorderai"),
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
                facts=factsets.causelist(data, subject=subject),
            )
        # ---- Admin · reference data. No SCAN parameter, no risk rule. ----
        #
        # These are REFERENCE shape on purpose. They are real calls with real
        # responses, but they describe the API rather than the vendor, and
        # rendering them among the findings puts a list of sortable field
        # names in front of a client with no explanation of why it is in
        # their report.
        if check_id == "courtcaps":
            data = ec.search_capabilities()
            return Finding(check_id, CheckStatus.PASS,
                           f"{len(data['fields'])} searchable field(s)",
                           "The authoritative list of Case Search filters.",
                           raw=data,
                           facts=factsets.catalog(
                               "The filters this account's Case Search accepts. "
                               "Checked before every search so an unsupported "
                               "filter fails loudly instead of being ignored.",
                               list(data.get("fields") or []),
                           ))

        if check_id == "courtenums":
            data = ec.enums(get("types", "caseStatus,benchType") or "caseStatus,benchType")
            return Finding(check_id, CheckStatus.PASS,
                           f"{len(data)} enum group(s)",
                           "Live codes — fetched rather than hard-coded.", raw=data,
                           facts=factsets.catalog(
                               "Case status and bench type codes, read live from "
                               "the source rather than hard-coded here.",
                               list(data.keys()) if isinstance(data, dict) else [],
                           ))

        if check_id == "courtstructure":
            rows = ec.court_structure(get("state") or None,
                                      get("districtCode") or None)
            return Finding(check_id, CheckStatus.PASS, f"{len(rows)} entries",
                           "High courts appear as districts and the Supreme "
                           "Court as a state.", raw={"rows": rows},
                           facts=factsets.catalog(
                               "The court hierarchy this search covers. High "
                               "courts appear as districts and the Supreme Court "
                               "as a state.",
                               [str(r.get("name") or r.get("district") or r)
                                for r in rows if isinstance(r, (dict, str))],
                           ))

        if check_id == "courtdates":
            dates = ec.available_dates(
                state=get("state"), districtCode=get("districtCode"),
                courtComplexCode=get("courtComplexCode"),
                courtNo=get("courtNo"), court=get("court"),
            )
            return Finding(check_id, CheckStatus.PASS, f"{len(dates)} date(s)",
                           "Dates holding cause-list data.", raw={"dates": dates},
                           facts=factsets.catalog(
                               "Dates for which this court has cause-list data.",
                               [_human_date(d) or str(d) for d in dates],
                           ))

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
                facts=factsets.job_receipt(data, what="A case refresh"),
            )

        if check_id == "courtchecks":
            data = ec.list_legal_checks(
                status=get("status") or None,
                page_size=int(get("page_size", "20") or 20),
            )
            return Finding(check_id, CheckStatus.PASS,
                           f"{len(data['items'])} legal check(s)",
                           "Every check submitted on this account.", raw=data,
                           facts=factsets.catalog(
                               "Legal checks submitted on this account — an "
                               "account-level record, not a finding about this "
                               "vendor.",
                               [str((i or {}).get("code") or i)
                                for i in (data.get("items") or [])],
                           ))

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

            # Everything VBC already knows about this company goes with the
            # submit. The report's `identity_confidence` is what separates a
            # defensible finding from a name collision, and below
            # `ecourts_min_score` the result is shown but never scored — so
            # anything that raises confidence directly buys usable findings.
            # A CIN is unique; a company name is not.
            data = ec.run_legal_check(
                subject_name=name,
                subject_type=get("subjectType", "company") or "company",
                # Stable per vendor, so an HTTP-level retry collects the
                # existing job instead of starting a second paid one.
                idempotency_key=f"vbc-{vendor.id}-court",
                client_ref_no=vendor.id,
                existing_code=prior_code,
                cin=cin,
                directors=_director_names(prior),
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

            return Finding(check_id, status, value, detail, raw=data,
                           facts=factsets.legal_check(data))

        return Finding(check_id, CheckStatus.SKIP, "Not implemented",
                       f"No runner is wired for check '{check_id}'.")

    # =================================================================

    def _keep_document(
        self, content: bytes, vendor_id: str, check_id: str, filename: str,
        *, kind: str = "pdf",
    ) -> tuple[docs.StoredDocument | None, str]:
        """Write a fetched document to the store and index it.

        Returns ``(stored, note)``. A failure returns ``(None, why)`` and is
        NEVER allowed to fail the check: the provider answered, the call was
        paid for, and the finding it produced is still true. Losing the file
        is our housekeeping problem, and the row says so in those words
        rather than reporting an adverse result about the vendor.
        """
        try:
            stored = docs.store(content, kind=kind, settings=self.settings)
        except docs.DocumentStoreFull as exc:
            logger.error("document store full: %s", exc)
            return None, str(exc)
        except (ValueError, OSError) as exc:
            logger.error("could not store document for %s: %s", check_id, exc)
            return None, f"the document could not be written ({exc})."

        if not stored.deduplicated:
            self.session.add(StoredDocumentRow(
                sha256=stored.sha256, vendor_id=vendor_id, check_id=check_id,
                filename=filename, bytes=stored.bytes,
                media_type=docs.MEDIA_TYPES.get(kind, "application/octet-stream"),
            ))
        return stored, ""

    def _ocr(self, content: bytes, check_id: str) -> dict | None:
        """Read a scanned order, when that is switched on and configured.

        Returns None when OCR did not happen — off, no key, refused, or it
        failed. None is not an error state: the order keeps its PDF and the
        row says no text was available, which was true before this existed
        and is still true.

        Nothing here may raise. The order was fetched and paid for; failing
        the whole check because a reading aid was unavailable would turn a
        successful retrieval into an unexamined one, which is the one thing
        this codebase refuses to do.
        """
        if not self.settings.vision_ocr_orders:
            return None
        try:
            return self.vision.read_pdf(content)
        except (ProviderError, ValueError) as exc:
            logger.warning("%s: OCR unavailable (%s): %s",
                           check_id, type(exc).__name__, exc)
            return None

    def _keep_orders(self, fetched: list[dict], vendor_id: str,
                     check_id: str) -> list[dict]:
        """Decode each order's base64 PDF to a real file, and link it.

        Each order arrives as a ~50 KB base64 string. Held only in
        `raw_response` it is unreadable to everyone; written out, it is the
        document a court actually issued. The base64 stays in raw as the
        evidence it always was.
        """
        out = []
        for order in fetched:
            row = dict(order)
            blob = row.get("pdf_base64")
            if blob:
                try:
                    content = base64.b64decode(blob, validate=False)
                except (ValueError, TypeError) as exc:
                    logger.warning("%s: undecodable pdf_base64: %s", check_id, exc)
                    content = b""
                if content:
                    name = str(row.get("filename") or "order").rsplit("/", 1)[-1]
                    stored, note = self._keep_document(
                        content, vendor_id, check_id,
                        name if name.lower().endswith(".pdf") else f"{name}.pdf")
                    if stored:
                        row["href"] = stored.url
                        row["sha256"] = stored.sha256
                        row["bytes"] = stored.bytes
                    else:
                        row["store_note"] = note

            # The text half. A signed PDF is the evidence; the text is what
            # a person reads, and it is the only one of the two that opens
            # in a panel rather than a viewer. Stored on the same terms as
            # the PDF so both survive a re-render of the facts.
            text = str(row.get("markdown") or row.get("content") or "")
            if text.strip():
                row["text_source"] = "filed"
            elif content:
                # Nothing filed as text — the order is a scan. OCR is the
                # only way to read it, and what comes back is a MACHINE'S
                # READING of an image, not what the court wrote. The flag
                # travels with it so nothing downstream can lose that.
                ocr = self._ocr(content, check_id)
                if ocr and ocr.get("text"):
                    text = str(ocr["text"])
                    row["text_source"] = "ocr"
                    row["ocr_language"] = ocr.get("language")
                    row["ocr_truncated"] = bool(ocr.get("truncated"))
                elif ocr:
                    row["ocr_note"] = ("read, but no text on any page — a "
                                       "signature sheet or a blank page.")

            if text.strip():
                base = str(row.get("filename") or "order").rsplit("/", 1)[-1]
                stored, note = self._keep_document(
                    text.encode("utf-8"), vendor_id, check_id,
                    f"{base.rsplit('.', 1)[0]}.txt", kind="text")
                if stored:
                    row["text_href"] = stored.url
                elif not row.get("store_note"):
                    row["store_note"] = note
            out.append(row)
        return out

    @staticmethod
    def _flag_thin(finding: Finding) -> Finding:
        """Attach the thin-result flag, if this response earned one.

        Applied at the ONE point every finding passes through, rather than
        in each of the thirty-odd dispatch branches — a guard that has to be
        remembered per check is a guard that will be forgotten on the
        thirty-first.

        Never changes a status. It appends a flag a person reads, because
        "the parser probably missed something" is a suspicion, and a
        suspicion must not move a score.
        """
        if not finding.facts or not finding.status.was_examined:
            return finding
        raw = finding.raw or {}
        payload = raw.get("payload", raw) if isinstance(raw, dict) else raw
        flag = factsets.thin_result(payload, finding.facts)
        if flag:
            finding.facts.setdefault("flags", []).insert(0, flag)
            logger.warning(
                "%s: %d fields populated from a %s-byte payload — possible "
                "renamed field", finding.check_id,
                sum(1 for f in finding.facts.get("fields") or []
                    if f.get("value") not in (None, "", "—")),
                len(str(payload)),
            )
        return finding

    def _prior_raw(self, vendor_id: str, check_id: str) -> dict:
        """What a previous run stored for this check, if anything.

        Used by the two cooldown guards. Both refresh endpoints bill on
        request and serve the cache while they are cooling down, so the
        cooldown has to be read from what we already know rather than from
        the response — by then the money is spent.
        """
        row = self.session.query(VendorCheck).filter(
            VendorCheck.vendor_id == vendor_id,
            VendorCheck.check_id == check_id,
        ).one_or_none()
        if row is None or not isinstance(row.raw_response, dict):
            return {}
        return row.raw_response

    def _cooling_down(
        self, vendor_id: str, check_id: str, hours: float,
    ) -> tuple[bool, datetime | None]:
        """Is this paid refresh still inside the provider's cooldown?

        Prefers ``cooldownUntil`` as the provider reported it; falls back to
        the last fetch plus the configured window when the provider did not
        say. Returns the moment it lifts so the message can name it.
        """
        prior = self._prior_raw(vendor_id, check_id)
        now = datetime.now(timezone.utc)

        stated = prior.get("cooldownUntil") or prior.get("cooldown_until")
        if stated:
            try:
                until = datetime.fromisoformat(str(stated).replace("Z", "+00:00"))
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                return until > now, until
            except ValueError:
                logger.info("%s: unparseable cooldownUntil %r", check_id, stated)

        fetched = prior.get("_fetched_at")
        if fetched:
            try:
                last = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                until = last + timedelta(hours=hours)
                return until > now, until
            except ValueError:
                pass
        return False, None

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
                                   raw=res.as_payload(),
                                   facts=factsets.inhouse(res.as_payload(),
                                                          kind="duplicate"))
                top = res.matches[0]
                return Finding(
                    check_id,
                    CheckStatus.FAIL if top["confidence"] == "conclusive" else CheckStatus.WARN,
                    f"Possible duplicate of #{top['vendorId']}",
                    f"{top['rule']} ({top['confidence']}): {top['detail']}",
                    raw=res.as_payload(),
                    facts=factsets.inhouse(res.as_payload(), kind="duplicate"),
                )

            if check_id == "rp":
                res = inhouse.check_related_party(self.session, vendor)
                if not res.matched:
                    return Finding(check_id, CheckStatus.PASS, "No related party",
                                   f"No shared directors or addresses across "
                                   f"{res.compared_against} vendors.",
                                   raw=res.as_payload(),
                                   facts=factsets.inhouse(res.as_payload(),
                                                          kind="related party"))
                top = res.matches[0]
                return Finding(check_id, CheckStatus.WARN,
                               f"Related to #{top['vendorId']}", top["detail"],
                               raw=res.as_payload(),
                               facts=factsets.inhouse(res.as_payload(),
                                                      kind="related party"))

            if check_id == "conflict":
                res = inhouse.check_conflict(self.session, vendor)
                if res.compared_against == 0:
                    # Nothing was compared. This must not read as "no conflict".
                    return Finding(
                        check_id, CheckStatus.UNAVAILABLE, "No employee register",
                        "No employee register is connected, so nothing was compared. "
                        "This is a coverage gap, not a clean result.",
                        raw=res.as_payload(),
                        facts=factsets.inhouse(res.as_payload(), kind="conflict"),
                    )
                if not res.matched:
                    return Finding(check_id, CheckStatus.PASS, "No conflict",
                                   f"No overlap across {res.compared_against} employees.",
                                   raw=res.as_payload(),
                                   facts=factsets.inhouse(res.as_payload(),
                                                          kind="conflict"))
                top = res.matches[0]
                return Finding(check_id, CheckStatus.FAIL, "Conflict of interest",
                               f"{top['rule']}: director matches employee "
                               f"{top.get('employee')}.", raw=res.as_payload(),
                               facts=factsets.inhouse(res.as_payload(),
                                                      kind="conflict"))
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

    #: Checks that read documents the unlock's background job produces.
    #: Until that job finishes the provider returns nothing for them, and
    #: "nothing" from these three is indistinguishable from a company that
    #: genuinely has no filings and no filed accounts.
    _NEEDS_DOCUMENTS = ("filings", "download", "fin")

    def _apply_refresh_state(self, status, result: RunResult) -> None:
        """Record whether the unlock's document job has finished."""
        if status is None or status.sandbox:
            return
        result.refresh_stage = status.download_status
        if status.refresh_running:
            result.documents_ready = False
            result.notes.append(
                f"The provider is still preparing this company's documents "
                f"(download stage: {status.download_status}). Filings and "
                f"financials are recorded as UNAVAILABLE rather than absent."
            )

    def _note_refresh_progress(self, cin: str, result: RunResult) -> None:
        """Free status call, purely to find out whether documents have landed.

        Wrapped because it must never be the reason a run fails: not knowing
        the stage leaves today's behaviour in place, which is the safe
        direction — the checks still run and still report what they find.
        """
        try:
            self._apply_refresh_state(self.filesure.unlock_status(cin), result)
        except ProviderError as exc:
            logger.info("%s: could not read unlock progress: %s", cin, exc)

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
                # The unlock is on file, but the refresh it kicked off may
                # still be running — an unlock five minutes old is recorded
                # exactly like one from last year. The status call is FREE
                # (the provider's docs say so explicitly), so ask rather
                # than assume the documents have landed.
                self._note_refresh_progress(cin, result)
                return

            status, paid = self.filesure.ensure_unlocked(cin)
            vendor.unlocked = status.unlocked
            if not paid:
                result.notes.append("Unlock already active at the provider — no charge.")
                self._apply_refresh_state(status, result)
                return
            if status.sandbox:
                result.notes.append(
                    "Unlock returned sandbox:true — no real unlock occurred. "
                    "A live key is needed before financials can be read."
                )
                return

            result.unlock_purchased = True
            # Certain, not inferred: the provider's docs say `data.job` is
            # null immediately after the POST because the job has not been
            # registered yet. So a fresh unlock CANNOT have its documents —
            # no status call would tell us otherwise, and asking one would
            # only get a null job back and read as "ready".
            result.documents_ready = False
            result.refresh_stage = "just queued"
            result.notes.append(
                "Unlock purchased — the provider is now downloading this "
                "company's documents, which takes 10–30 minutes. Filings, "
                "filing downloads and filed financials are recorded as "
                "UNAVAILABLE on this run rather than as absent. Re-run them "
                "once the refresh completes; the unlock is not charged again."
            )
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

    @staticmethod
    def _would_erase_evidence(existing: VendorCheck | None, finding: Finding) -> bool:
        """Is this write about to replace a real payload with nothing?

        True only in the one narrow case: a row that already holds provider
        evidence, and a new finding that carries none. Everything else falls
        through and overwrites normally, because a re-run that DID reach the
        provider should of course replace what came before.

        Deliberately narrow in three ways:

        * An EXAMINED finding never preserves, even with an empty payload.
          A check that genuinely returns `{}` — no charges, no litigation —
          is a real answer, and holding yesterday's answer over it would
          hide a change in the vendor. Only unexamined statuses qualify.
        * A `_pending` receipt is not evidence, but it IS the poll code that
          makes the next collection free. It overwrites, as it always did.
        * A payload that is only our own request echo is not evidence
          either.
        """
        if existing is None or not existing.raw_response:
            return False
        if finding.status.was_examined:
            return False
        new = finding.raw
        if not new:
            return True
        if not isinstance(new, dict):
            return False
        if new.get("_pending"):
            return False
        # A dict carrying nothing but what we sent.
        return not (set(new) - {"request", "checkId", "_note"})

    def _persist(self, vendor: Vendor, result: RunResult) -> None:
        """Write every outcome, including the non-outcomes.

        RESULTS ACCUMULATE. A check used to hold exactly one, and a
        re-run overwrote it — which lost the thing the work is made of:
        the person checks are run once per director, and the second run
        erased the first.

        Each run is now its own row. Exactly one per (vendor, check) is
        PRIMARY, and that is the one SCAN, the risk score and the report
        read.

        A NEW RUN DOES NOT STEAL PRIMARY. Only the first result for a
        check takes it automatically; after that an analyst marks the
        one that counts. Promoting the newest would move the score
        silently every time somebody tried a different input, and the
        whole argument of this platform is that a number must not move
        without somebody choosing it.

        The cost of that choice is a result that is newer than the
        primary and not counted, so `/vendors/{id}` reports exactly that
        and the findings screen says it out loud. Loud is the point.

        THE EVIDENCE-PRESERVATION BRANCH IS GONE, and nothing is lost
        with it. It existed because a failed re-run would overwrite a
        real payload with nothing — observed live, a `casedetail` re-run
        that hit INSUFFICIENT_CREDITS blanking the response behind an
        already computed score. Appending makes that impossible rather
        than merely guarded against: the earlier row still holds its own
        payload because nothing writes to it. A failed run is recorded
        as what it is, a failed run, in a row of its own.
        """
        inputs = self._inputs(vendor)
        for finding in result.findings:
            had_primary = self.session.scalar(
                select(VendorCheck.id).where(
                    VendorCheck.vendor_id == vendor.id,
                    VendorCheck.check_id == finding.check_id,
                    VendorCheck.is_primary.is_(True),
                )
            )
            previous = len(self.session.scalars(
                select(VendorCheck.id).where(
                    VendorCheck.vendor_id == vendor.id,
                    VendorCheck.check_id == finding.check_id,
                )
            ).all())

            row = VendorCheck(
                vendor_id=vendor.id,
                check_id=finding.check_id,
                status=finding.status.value,
                value=finding.value,
                detail=finding.detail,
                raw_response=finding.raw,
                facts=finding.facts,
                parser_version=(finding.facts or {}).get("parserVersion"),
                cost_paisa=finding.cost_paisa,
                credits=finding.credits,
                error=finding.error,
                fetched_at=finding.fetched_at,
                # How many times this check has been run for this vendor,
                # counting this one. Previously stuck at 1 forever, which
                # hid how often a flaky source had been retried.
                attempts=previous + 1,
                is_primary=had_primary is None,
                # WHAT WAS ASKED, FOR THIS RESULT. `vendor_check_inputs`
                # holds one value per key, so it reflects whatever was
                # typed LAST — four runs against four directors would all
                # show the fourth director's number. Snapshotted here so a
                # result and the values it came from cannot drift apart.
                inputs=self._inputs_for(finding.check_id, inputs, vendor),
            )
            self.session.add(row)

            if had_primary is None and previous:
                # Every result for this check was deleted and a new one
                # arrived. Worth a line: a check silently becoming
                # countable again is the kind of thing somebody asks
                # about three months later.
                self._audit(
                    vendor.id, "CHECK_PRIMARY_SET",
                    f"{finding.check_id}: no result was marked as counting, "
                    f"so this run became the one the score reads.",
                )
        self.session.flush()

    def _inputs_for(self, check_id: str, inputs: dict, vendor: Vendor) -> dict:
        """The values this check actually ran with.

        Includes the vendor-record fallbacks, because a blank box whose
        value came off the vendor is still what was sent — and "What was
        asked" showing nothing for a call that plainly had an argument is
        how an analyst stops trusting the panel.
        """
        definition = CHECKS_BY_ID.get(check_id)
        if definition is None:
            return {}
        stored = inputs.get(check_id, {})
        out: dict[str, str] = {}
        for param in definition.params:
            # Same order of precedence as `_missing_inputs` and the
            # dispatch getter: what was typed, then the vendor record.
            # Three copies of this rule would be two too many, but the
            # other two read it to decide whether a call can be made and
            # this one to record what it was made WITH.
            value = stored.get(param.key, "")
            if not str(value).strip() and param.from_vendor:
                value = getattr(vendor, param.from_vendor, "") or ""
            if str(value).strip():
                out[param.key] = str(value).strip()
        return out

    def _audit(self, vendor_id: str, action: str, detail: str, actor: str = "system") -> None:
        self.session.add(
            AuditLog(vendor_id=vendor_id, actor=actor, action=action, detail=detail)
        )