"""Which providers cannot be called right now, and why.

THE PROBLEM THIS SOLVES
-----------------------
We buy data from four outside services on prepaid accounts. When one runs
out of money, every check against it fails the same way — and without a
shared record, every analyst learns that separately. The first discovers
it from a failed run; so does the tenth, each having waited for a call
that could not succeed, on a vendor file in front of a client.

So: the FIRST failure is recorded, and from then on those checks are
marked unavailable before anyone selects them. One person meets the error.
Nobody after them does, and no further calls go out.

WHAT COUNTS, AND WHAT DOES NOT
------------------------------
Only account-level refusals — 401, 402, 403. Those say nothing about the
vendor being checked and everything about the account, so they are true
for every other check against that provider.

Deliberately NOT included:

    404   this company is not there; the others are
    429   rate limited; it passes on its own
    5xx   the provider's bad afternoon, usually brief
    parse gap   the provider answered fine; the fault is ours

Treating any of those as an account failure would let one bad CIN mark
fourteen working checks dead, which is a worse failure than the one being
prevented.

THE MESSAGE IS THE PROVIDER'S, NEVER OURS
-----------------------------------------
An account can be refused for an empty balance, a revoked key, or an IP
that is not allowlisted. WhoisXML returns all three behind one 403:

    Access restricted. Reasons: insufficient credits balance, incorrect
    API key, or your IP address is not added to the IP allowlist

A fixed message of ours — "out of credits" — would send the wrong person
to the wrong place two times in three. Whatever the provider said is
stored and shown verbatim.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, ProviderOutage


#: How long a blocked provider is left alone before one check is allowed
#: through to see whether it is working again.
#:
#: Fifteen minutes is a compromise between two costs. Shorter, and a
#: provider that is down for an afternoon burns a failing call every few
#: minutes and analysts keep meeting the error the block exists to hide.
#: Longer, and somebody who has just topped up the balance sits looking at
#: "unavailable" wondering whether the payment worked.
PROBE_AFTER = timedelta(minutes=15)


def open_outages(session: Session) -> dict[str, ProviderOutage]:
    """Every provider currently blocked, keyed by provider name.

    One query per run and one per page load. Returned as a dict because
    both callers ask "is THIS provider blocked" repeatedly.
    """
    rows = session.scalars(
        select(ProviderOutage).where(ProviderOutage.cleared_at.is_(None))
    ).all()
    return {row.provider: row for row in rows}


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres does not."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def due_for_probe(outage: ProviderOutage, *, now: datetime | None = None) -> bool:
    """Should ONE call be let through to see whether this provider is back?

    Measured from the last attempt rather than from when the outage opened,
    so a provider that stays down is probed once per window rather than
    continuously after the first window passes.
    """
    now = now or datetime.now(timezone.utc)
    last = _aware(outage.last_probe_at) or _aware(outage.started_at)
    return last is None or (now - last) >= PROBE_AFTER


def mark_probed(
    session: Session, outage: ProviderOutage, *, now: datetime | None = None
) -> None:
    """Record that the probe call is going out now.

    Written BEFORE the call, not after, so a probe that hangs or crashes
    the worker still moves the clock. Otherwise a provider that times out
    would be probed by every run instead of one per window.
    """
    outage.last_probe_at = now or datetime.now(timezone.utc)
    session.flush()


def record_outage(
    session: Session,
    provider: str,
    *,
    message: str,
    http_status: int | None = None,
    check_id: str | None = None,
    vendor_id: str | None = None,
    source: str = "run",
) -> ProviderOutage:
    """Mark a provider blocked, or refresh the message on an existing block.

    Idempotent by design: a run with eight checks against one dead provider
    produces one row, not eight. The message is refreshed rather than
    ignored, because a provider that first said "insufficient balance" and
    now says "incorrect API key" is telling you something new.
    """
    existing = session.scalar(
        select(ProviderOutage).where(
            ProviderOutage.provider == provider,
            ProviderOutage.cleared_at.is_(None),
        )
    )
    if existing:
        if existing.provider_message != message:
            existing.provider_message = message
            existing.http_status = http_status
            session.add(
                AuditLog(
                    vendor_id=vendor_id,
                    actor="system",
                    action="PROVIDER_OUTAGE_CHANGED",
                    detail=f"{provider}: {message}",
                )
            )
        return existing

    outage = ProviderOutage(
        provider=provider,
        http_status=http_status,
        provider_message=message,
        detected_on_check=check_id,
        detected_on_vendor=vendor_id,
        source=source,
    )
    session.add(outage)
    session.add(
        AuditLog(
            vendor_id=vendor_id,
            actor="system",
            action="PROVIDER_OUTAGE_OPENED",
            detail=(
                f"{provider} blocked (HTTP {http_status}) — {message}. "
                f"Every {provider} check is unavailable until this clears. "
                f"Detected on {check_id or 'the nightly balance check'}."
            ),
        )
    )
    session.flush()
    return outage


def clear_outage(
    session: Session, provider: str, *, reason: str = "a successful call"
) -> bool:
    """Close an open outage. Returns True if there was one to close.

    Called on every SUCCESSFUL call to a provider, so topping up a balance
    needs no second action from anybody — the next run that gets through
    reopens the provider by itself.

    The row is kept, not deleted. How long a provider was down and what it
    said is the question asked after a client complains, and it cannot be
    answered from a row that was removed.
    """
    outage = session.scalar(
        select(ProviderOutage).where(
            ProviderOutage.provider == provider,
            ProviderOutage.cleared_at.is_(None),
        )
    )
    if outage is None:
        return False

    outage.cleared_at = datetime.now(timezone.utc)
    session.add(
        AuditLog(
            vendor_id=None,
            actor="system",
            action="PROVIDER_OUTAGE_CLEARED",
            detail=(
                f"{provider} is answering again, cleared by {reason}. "
                f"It was blocked from {outage.started_at:%Y-%m-%d %H:%M} — "
                f"{outage.provider_message}"
            ),
        )
    )
    session.flush()
    return True
