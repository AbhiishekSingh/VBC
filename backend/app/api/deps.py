"""Request dependencies: who is calling, and what they may do.

`current_user` is the only way a handler learns who the actor is. Nothing
reads an actor name out of a request body any more — see app/services/auth.py
for why that mattered.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Client, User
from app.db.session import get_session
from app.services import auth


def current_user(
    vbc_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE),
    session: Session = Depends(get_session),
) -> User:
    user = auth.resolve_session(session, vbc_session)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not signed in, or the session has expired.",
        )
    return user


def require_permission(permission: str):
    """Dependency factory: gate an endpoint on one permission."""

    def _guard(user: User = Depends(current_user)) -> User:
        try:
            auth.require(user, permission)
        except auth.Forbidden as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
        return user

    return _guard


def client_or_404(session: Session, client_id: str) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(404, f"No client with id {client_id}")
    return client
