#!/usr/bin/env python3
"""Nightly prepaid-balance check. Run from cron.

    cd /opt/vbc/backend && .venv/bin/python -m scripts.check_balances

Crontab on the server — 02:40, after the day's runs and before anyone
arrives, so an empty wallet is a note in the audit log at breakfast
instead of a failed run in front of a client:

    40 2 * * *  cd /opt/vbc/backend && .venv/bin/python -m scripts.check_balances \
                 >> /var/log/vbc/balances.log 2>&1

EXIT CODES, so cron's mail or a monitor can act on them:

    0   every provider checked is fine
    1   a provider is blocked — it needs topping up
    2   the check could not be completed (network, or a payload this
        adapter could not read). State was left alone on purpose.

Only FileSure is checked. It is the one provider that publishes a balance
on a free endpoint; the other three are blocked reactively the first time
a real call is refused, which is the best that can be done without
spending money to ask.

READ-ONLY AGAINST THE PROVIDER. The usage endpoint costs nothing, so this
can run every night forever without a line on the invoice.
"""

from __future__ import annotations

import logging
import sys

from app.config import get_settings
from app.db.session import session_scope
from app.services import balance_watch


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    with session_scope() as session:
        report = balance_watch.check_filesure(session, settings)

    action = report.get("action")
    balance = report.get("balancePaisa")
    shown = f"₹{balance / 100:,.2f}" if isinstance(balance, int) else "unknown"

    print(f"filesure: {action} (balance {shown})")
    if report.get("reason"):
        print(f"  {report['reason']}")

    if action == "blocked":
        print("  FileSure checks are now unavailable for all users.")
        return 1
    if action in ("unknown", "unreadable"):
        print("  Provider state was NOT changed — this is not evidence of an "
              "empty wallet.")
        return 2
    if action == "cleared":
        print("  FileSure checks are available again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
