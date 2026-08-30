"""Authentication: passwords, sessions, and who is allowed to do what.

TWO RULES THIS MODULE EXISTS TO ENFORCE

1. THE ACTOR COMES FROM THE SESSION, NEVER FROM THE REQUEST BODY.
   Before this existed, `/decision` accepted whatever `decidedBy` name the
   caller supplied. Anyone could record a binding approval under a
   colleague's name and the audit trail would carry it as fact. In a
   product whose output is a signed decision, that is the whole product
   failing.

2. ONLY AN APPROVER RECORDS A DECISION.
   The system gathers, an analyst assesses, and a named human with the
   authority commits the outcome. That separation is the handoff's product
   principle expressed in the access layer.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import Session, User

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()

SESSION_COOKIE = "vbc_session"
SESSION_TTL = timedelta(hours=12)

#: What each role may do. Checked in one place so a new endpoint cannot
#: quietly acquire wider powers than intended.
PERMISSIONS: dict[str, set[str]] = {
    "analyst": {"read", "run_checks", "rate", "record_manual"},
    "approver": {"read", "run_checks", "rate", "record_manual", "decide"},
    "admin": {"read", "run_checks", "rate", "record_manual", "decide", "manage_users"},
}


class AuthError(Exception):
    """Bad credentials, or an expired session."""


class Forbidden(Exception):
    """Authenticated, but not permitted to do this."""


# ---------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verify. Never leaks whether the email or the password
    was the wrong half — the caller reports one message for both."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ---------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------


def _hash_token(token: str) -> str:
    """Sessions are stored hashed, like passwords.

    A database dump then yields no usable sessions. SHA-256 is right here
    and argon2 is not: the token is 256 bits of CSPRNG output, so there is
    no dictionary to attack and no need to be slow.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: DbSession, user: User) -> str:
    """Issue a session token. Returns the RAW token — stored only hashed."""
    token = secrets.token_urlsafe(32)
    db.add(
        Session(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
    return token


def resolve_session(db: DbSession, token: str | None) -> User | None:
    """The user behind a token, or None. Expired sessions never resolve."""
    if not token:
        return None
    row = db.scalar(
        select(Session).where(
            Session.token_hash == _hash_token(token),
            Session.expires_at > datetime.now(timezone.utc),
        )
    )
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        return None
    return user


def end_session(db: DbSession, token: str | None) -> None:
    if not token:
        return
    row = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
    if row is not None:
        db.delete(row)


def purge_expired(db: DbSession) -> int:
    rows = db.scalars(
        select(Session).where(Session.expires_at <= datetime.now(timezone.utc))
    ).all()
    for row in rows:
        db.delete(row)
    return len(rows)


# ---------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------


def authenticate(db: DbSession, email: str, password: str) -> User:
    """Verify credentials. One error message for every failure mode.

    "No such user" and "wrong password" must be indistinguishable, or the
    login form becomes a way to enumerate who works here.
    """
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.active:
        # Spend the time anyway, so a missing user is not measurably faster
        # than a wrong password.
        _hasher.hash("timing-equalisation")
        raise AuthError("Email or password is incorrect.")
    if not verify_password(password, user.password_hash):
        raise AuthError("Email or password is incorrect.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def require(user: User, permission: str) -> None:
    """Raise unless the user's role carries this permission."""
    if permission not in PERMISSIONS.get(user.role, set()):
        raise Forbidden(
            f"Your role ({user.role}) cannot {permission.replace('_', ' ')}. "
            f"A decision must be recorded by an approver."
        )
