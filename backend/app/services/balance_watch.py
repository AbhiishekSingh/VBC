"""Find an empty prepaid wallet before an analyst does.

WHY A NIGHTLY JOB AND NOT JUST THE REACTIVE BLOCK
-------------------------------------------------
``provider_state`` already blocks a provider the first time somebody is
refused. That works, but somebody still had to be refused — on a vendor
file, usually with a client waiting, at whatever hour the balance happened
to run out.

FileSure publishes the wallet balance on a FREE endpoint. So for FileSure
there is no reason to learn this from a failure: the balance is read once
a night, and if it is spent, the checks are marked unavailable before the
office opens and an invoice gets paid instead of an apology.

The other three providers have no equivalent free endpoint, so they stay
reactive: one analyst meets the error, and the block spares everyone else.

WHAT THIS DELIBERATELY WILL NOT DO
----------------------------------
It will not block a provider on a payload it could not read. If FileSure
renames the balance field, this job finds no number — and a missing number
is not a zero. Treating it as one would take a working provider offline
for every user, nightly, over a schema change. It logs loudly and leaves
the state alone, which fails in the direction that costs a call rather
than a day.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AuditLog
from app.providers import filesure as fs_mod
from app.providers.base import (
    NotConfigured,
    ProviderAccountBlocked,
    ProviderError,
    ProviderOutOfCredits,
    Spend,
)
from app.services import provider_state

logger = logging.getLogger(__name__)


#: Where the wallet balance might be, in order of preference.
#:
#: Several spellings because the field is documented in one place and
#: returned in another, and this project has already been bitten once by
#: exactly that (``createdDateNormalized`` in WhoisXML's documentation,
#: ``createdDateISO8601`` in its responses). Reading only the documented
#: name produced a silent None that flowed into a score.
_BALANCE_PATHS: tuple[tuple[str, ...], ...] = (
    ("walletBalancePaisa",),
    ("balancePaisa",),
    ("wallet", "balancePaisa"),
    ("wallet", "paisa"),
    ("account", "walletBalancePaisa"),
    ("meta", "walletBalanceAfterPaisa"),
)


def _dig(payload: Any, path: tuple[str, ...]) -> Any:
    node = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def read_balance_paisa(payload: dict) -> int | None:
    """The wallet balance in paisa, or None if the payload does not say.

    None means "could not tell", never "zero". The caller must not block a
    provider on it — see the module docstring.
    """
    for path in _BALANCE_PATHS:
        value = _dig(payload, path)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            if text.lstrip("-").isdigit():
                return int(text)
    return None


def check_filesure(
    session: Session, settings: Settings | None = None
) -> dict[str, Any]:
    """Read FileSure's wallet and open, refresh or close its outage.

    Returns a small report so the script that runs this can print
    something and exit non-zero when the account is down.
    """
    settings = settings or get_settings()
    report: dict[str, Any] = {"provider": "filesure", "action": "none"}

    if not settings.filesure_configured:
        report["action"] = "skipped"
        report["reason"] = "no key set"
        return report

    client = fs_mod.FileSureProvider(settings, spend=Spend())
    try:
        payload = client.account_usage()
    except (ProviderOutOfCredits, ProviderAccountBlocked) as exc:
        # The usage endpoint itself refused the account. That IS the
        # answer, and the provider's own words are the right thing to
        # store — not a sentence of ours about what we think it meant.
        provider_state.record_outage(
            session,
            "filesure",
            message=str(exc),
            http_status=getattr(exc, "status", None),
            source="balance_check",
        )
        report.update(action="blocked", reason=str(exc))
        return report
    except NotConfigured as exc:
        report.update(action="skipped", reason=str(exc))
        return report
    except ProviderError as exc:
        # A timeout or a 502 says nothing about the balance. Changing the
        # state on it would take a working provider down over a bad
        # minute on somebody else's network.
        logger.warning("balance check could not reach FileSure: %s", exc)
        report.update(action="unknown", reason=str(exc))
        return report
    finally:
        client.close()

    balance = read_balance_paisa(payload)
    report["balancePaisa"] = balance

    if balance is None:
        logger.error(
            "FileSure usage payload carried no recognisable balance field; "
            "keys were %s. Provider state left unchanged.",
            sorted(payload)[:20] if isinstance(payload, dict) else type(payload),
        )
        session.add(
            AuditLog(
                vendor_id=None,
                actor="system",
                action="PROVIDER_BALANCE_UNREADABLE",
                detail=(
                    "The nightly balance check reached FileSure but could not "
                    "find a balance in the response. Nothing was changed — an "
                    "unreadable payload is not an empty wallet. The adapter "
                    "needs updating."
                ),
            )
        )
        report.update(action="unreadable")
        return report

    rupees = balance / 100

    if balance < settings.filesure_balance_floor_paisa:
        provider_state.record_outage(
            session,
            "filesure",
            message=(
                f"Wallet balance ₹{rupees:,.2f}, which is below the ₹"
                f"{settings.filesure_balance_floor_paisa / 100:,.2f} an "
                f"ordinary read costs. Reported by the provider's own usage "
                f"endpoint; top the account up to restore these checks."
            ),
            source="balance_check",
        )
        report.update(action="blocked", reason="balance below floor")
        return report

    if provider_state.clear_outage(
        session, "filesure", reason=f"the nightly balance check (₹{rupees:,.2f})"
    ):
        report.update(action="cleared")

    if balance < settings.filesure_balance_low_paisa:
        session.add(
            AuditLog(
                vendor_id=None,
                actor="system",
                action="PROVIDER_BALANCE_LOW",
                detail=(
                    f"FileSure wallet is ₹{rupees:,.2f}. Still working, but "
                    f"below the ₹{settings.filesure_balance_low_paisa / 100:,.2f} "
                    f"warning level — top it up before it stops mid-run."
                ),
            )
        )
        if report["action"] == "none":
            report["action"] = "low"

    return report
