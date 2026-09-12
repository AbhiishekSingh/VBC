"""Runtime configuration, from the environment.

CREDENTIALS ARE NEVER IN CODE OR IN THE DATABASE. They come from the
environment, and the application refuses to make a paid call without one
rather than failing halfway through a run.

A provider with no key configured is not an error — it is a check that
reports ``not_configured``, exactly like the nine hooks. That distinction
runs through the whole product: something that was not examined must never
look like something that came back clean.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: The backend package root — app/config.py -> app -> backend.
#: .env is anchored here rather than to the current working directory,
#: because "env_file='.env'" resolves relative to wherever the process was
#: launched from. Running uvicorn from a different folder would otherwise
#: silently miss the file and fall back to defaults, which looks exactly
#: like a configuration that was never applied.
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VBC_",
        env_file=(BACKEND_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- database ------------------------------------------------------
    #: Override with VBC_DATABASE_URL in .env. The default assumes a local
    #: PostgreSQL on the standard port — adjust user, password and host.
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/vbc"

    # --- FileSure ------------------------------------------------------
    #: Header is `x-api-key`. Test keys are fsk_test_…, live keys fsk_live_…
    #: A test key returns SANDBOX_ONLY for real DINs, and unlock responses
    #: come back with sandbox:true and null timestamps — so a green run
    #: against a test key is not evidence the live path works.
    filesure_api_key: str = ""
    filesure_base_url: str = "https://api.filesure.in"
    #: The ₹150 company update is asynchronous — it returns `pending` and the
    #: data is NOT fresh when it does. Polling has to fit inside the same
    #: synchronous request as every other check, and nginx cuts at 120s.
    filesure_update_poll_budget_seconds: float = 45.0
    filesure_update_poll_interval_seconds: float = 3.0
    #: Cooldowns the PROVIDER enforces. Held here so a second call inside the
    #: window can be refused BEFORE it is made: both endpoints bill on
    #: request and serve the cache when they are still cooling down, so
    #: discovering the cooldown from the response means discovering it after
    #: paying. ₹150 and ₹5 respectively.
    filesure_update_cooldown_hours: float = 48.0
    filesure_filings_refresh_cooldown_hours: float = 6.0
    #: Ceiling on director contact lookups when no DIN is given and the whole
    #: board is resolved. Each one needs a ₹50 unlock plus the ₹0.05 read, so
    #: a 25-director board is ₹1,250 from one ticked box — the same trap
    #: `ecourts_max_orders` exists for. (₹50 per DIRECTOR_UNLOCK_PAISA; the
    #: docstring on `director_contact` still says ₹10 and is stale.)
    filesure_max_director_contacts: int = 5
    #: A director on this many boards is the classic mass-director pattern.
    #: Not adverse on its own, so it raises a flag and never a status.
    filesure_directorship_alarm: int = 20

    # --- WhoisXML ------------------------------------------------------
    #: One key across all products, but credits are per-product POOLS, not
    #: one balance. The screenshot pool is the tightest at 10.
    whoisxml_api_key: str = ""

    # --- FinAGG GSP (GST) ----------------------------------------------
    #: Header is `x-api-key`, obtained from gsp@finagg.in.
    #:
    #: Only the two Common APIs are used — search and returns metadata.
    #: The Taxpayer APIs and File Download endpoints authenticate AS THE
    #: TAXPAYER via an OTP to their registered mobile, which a vendor being
    #: assessed will not supply. They are not implemented, so no auth token
    #: or app_key encryption setting appears here.
    finagg_api_key: str = ""
    #: Sandbox serves LIVE GSTN data, not a fixture set — verified 2026-09-09
    #: against a real vendor. So the sandbox host is a working default, not a
    #: placeholder, and production access is not a prerequisite for testing.
    finagg_base_url: str = "https://sandbox-gsp.finagg.in/basic/gstn"
    #: Path segments FinAGG's docs leave unspecified. These are the values
    #: FinAGG support supplied on 2026-09-09 in a working curl, confirmed
    #: with a 200. They are NOT the ones the portal implies: `v1` / `v1.2`
    #: returns 500 with an empty `status_cd: "0"` body and no error object,
    #: which reads like a server fault rather than a wrong path.
    finagg_version: str = "fin-v1"
    finagg_gsp_version: str = "v1.3"
    #: Endpoint actions. `TP` for search is confirmed working. The returns
    #: action is NOT confirmed — `RETTRACK` is the GSTN contract's value and
    #: a placeholder here, because search turned out to be `TP` rather than
    #: the contract's `SEARCHGSTIN`, so the contract is not a safe guide.
    #: Settings rather than constants so the value can be corrected from the
    #: environment the moment FinAGG answers, without a deploy.
    finagg_search_action: str = "TP"
    finagg_returns_action: str = "RETTRACK"
    #: Per-call price in paisa. Zero until FinAGG quotes one: a call priced
    #: at zero is waved through the spend guard, so leaving these at 0 while
    #: the real contract bills would under-report the cost of a run. Set
    #: them the day pricing is agreed.
    finagg_search_paisa: int = 0
    finagg_returns_paisa: int = 0

    # --- eCourtsIndia (litigation) --------------------------------------
    #: Header is `Authorization: Bearer eci_live_…`.
    #:
    #: Only LegalCheck is used. Case Search is not implemented: its
    #: parameter list was truncated in the published documentation, and an
    #: adapter built on a guessed query shape returns 200 with zero results
    #: and reads as "nothing found".
    ecourts_api_key: str = ""
    ecourts_base_url: str = "https://webapi.ecourtsindia.com/api/partner"
    #: LegalCheck is a queued job — the provider's own example takes ~68s.
    #: VBC runs checks synchronously and nginx cuts at 120s, so the poll
    #: budget must leave room for the other checks in the same request.
    ecourts_poll_budget_seconds: float = 75.0
    ecourts_poll_interval_seconds: float = 3.0
    #: Match-confidence floor passed to the report. Recorded with the
    #: finding, because a score computed against one floor is not
    #: comparable to one computed against another.
    ecourts_min_score: int = 40
    #: Per-call prices in paisa, once eCourts quotes them. At 0 a call
    #: passes the spend guard untouched and a run under-reports its cost.
    ecourts_check_paisa: int = 0
    ecourts_search_paisa: int = 0
    ecourts_case_paisa: int = 0
    #: Refuse a Case Search filter the capability catalog does not list.
    #: On by default: the published parameter list was truncated, and a
    #: filter the server silently ignores produces a WIDER result set than
    #: intended, or an empty one — neither is visible in the response.
    ecourts_strict_search: bool = True
    #: Ceiling on order documents fetched per case. Each one is a paid call
    #: and a case can carry dozens, so an uncapped fetch turns one ticked
    #: box into an unbounded bill.
    ecourts_max_orders: int = 3

    # --- archive.org ---------------------------------------------------
    #: No key, no account. Free.
    archive_base_url: str = "https://archive.org"
    wayback_base_url: str = "https://web.archive.org"

    # --- HTTP behaviour ------------------------------------------------
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3
    http_backoff_base_seconds: float = 0.5

    # --- spend guards --------------------------------------------------
    #: Refuse to start a run whose estimated FileSure spend exceeds this.
    #: A company unlock is 33000 paisa (₹330), so the default allows one
    #: unlock plus a normal set of ₹5 reads and nothing wilder.
    #:
    #: These two defaults were 30000 and 25000, sized against a company
    #: unlock believed to cost ₹220. The real price is ₹330. Left as they
    #: were, every unlock would now be refused — and worse, the cap was
    #: being compared against the wrong constant, so it waved the ₹330
    #: charge through while appearing to guard against it.
    max_run_spend_paisa: int = 50_000
    #: Hard stop. Never trigger a company unlock automatically above this.
    #: Deliberately just above the ₹330 real price: a price RISE should
    #: stop a run and require a human to raise this, not be paid silently.
    company_unlock_paisa_cap: int = 35_000
    #: Set true to permit real paid calls. Left false, paid endpoints are
    #: refused — so a misconfigured staging box cannot spend real money.
    allow_paid_calls: bool = False

    # --- app -----------------------------------------------------------
    cors_origins: str = "http://localhost:5173"

    # --- auth ----------------------------------------------------------
    #: Send the session cookie only over HTTPS. MUST be true in production.
    #: Left false so local http://localhost development works; a deployment
    #: that forgets to flip it transmits session tokens in the clear.
    cookie_secure: bool = False

    @property
    def filesure_configured(self) -> bool:
        return bool(self.filesure_api_key)

    @property
    def whoisxml_configured(self) -> bool:
        return bool(self.whoisxml_api_key)

    @property
    def ecourts_configured(self) -> bool:
        return bool(self.ecourts_api_key)

    @property
    def finagg_configured(self) -> bool:
        return bool(self.finagg_api_key)

    @property
    def finagg_is_sandbox(self) -> bool:
        """A green sandbox run is not evidence the live path works."""
        return "sandbox" in self.finagg_base_url.lower()

    @property
    def filesure_is_sandbox(self) -> bool:
        return self.filesure_api_key.startswith("fsk_test_")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
