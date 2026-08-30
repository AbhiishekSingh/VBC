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

    # --- WhoisXML ------------------------------------------------------
    #: One key across all products, but credits are per-product POOLS, not
    #: one balance. The screenshot pool is the tightest at 10.
    whoisxml_api_key: str = ""

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
    def filesure_is_sandbox(self) -> bool:
        return self.filesure_api_key.startswith("fsk_test_")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
