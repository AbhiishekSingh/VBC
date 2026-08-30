"""Create a login. The ONLY way a user gets into this system.

    python -m app.db.create_user --email you@q1ssl.com --name "A Mehta" --role admin

No default account ships in a migration or a seed. A known email and
password baked into the codebase is a backdoor that reaches production and
is never removed — every deployment would share it, and nobody would know
who "admin@example.com" was in the audit trail.

The password is prompted for, never passed as an argument: a command-line
argument lands in shell history and in the process list, where any other
user on the box can read it.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from sqlalchemy import select

from app.db.models import User
from app.db.session import get_session_factory
from app.services.auth import PERMISSIONS, hash_password

MIN_PASSWORD_LENGTH = 12


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update a VBC login.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--role", default="analyst", choices=sorted(PERMISSIONS))
    parser.add_argument(
        "--generate-password", action="store_true",
        help="Generate a strong password and print it once.",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Set a new password for an existing user.",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()

    if args.generate_password:
        password = secrets.token_urlsafe(18)
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1

    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return 1

    session = get_session_factory()()
    try:
        existing = session.scalar(select(User).where(User.email == email))
        if existing and not args.reset:
            print(
                f"{email} already exists. Use --reset to set a new password.",
                file=sys.stderr,
            )
            return 1

        if existing:
            existing.password_hash = hash_password(password)
            existing.role = args.role
            if args.name:
                existing.name = args.name
            existing.active = True
            action = "updated"
        else:
            count = len(session.scalars(select(User.id)).all())
            session.add(
                User(
                    id=f"US{count + 1:06d}",
                    email=email,
                    name=args.name or email.split("@")[0],
                    password_hash=hash_password(password),
                    role=args.role,
                )
            )
            action = "created"
        session.commit()
    finally:
        session.close()

    print(f"OK   {email} {action} · role {args.role}")
    if args.generate_password:
        print(f"     password: {password}")
        print("     Shown once. Store it in a password manager now.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
