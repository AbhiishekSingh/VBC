"""Login, logout, and "who am I".

The session cookie is HttpOnly, so page JavaScript cannot read it and an
XSS bug cannot exfiltrate a session. SameSite=Lax stops another site
submitting authenticated requests on the user's behalf.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.api.deps import current_user
from app.config import get_settings
from app.db.models import AuditLog, User
from app.db.session import get_session
from app.services import auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


def _out(user: User) -> s.UserOut:
    return s.UserOut(
        id=user.id, email=user.email, name=user.name, role=user.role,
        permissions=sorted(auth.PERMISSIONS.get(user.role, set())),
    )


@router.post("/auth/login", response_model=s.UserOut)
def login(
    body: s.LoginIn,
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        user = auth.authenticate(session, body.email, body.password)
    except auth.AuthError as exc:
        # One message for every failure mode. Distinguishing "no such user"
        # from "wrong password" turns the login form into a way to
        # enumerate who works here.
        logger.info("failed login for %r from %s", body.email,
                    request.client.host if request.client else "?")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None

    token = auth.start_session(session, user)
    session.add(
        AuditLog(vendor_id=None, actor=user.email, action="LOGIN",
                 detail=f"{user.name} signed in as {user.role}")
    )
    session.commit()

    settings = get_settings()
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        httponly=True,                    # page JS cannot read it
        samesite="lax",                   # blocks cross-site use
        secure=settings.cookie_secure,    # HTTPS only in production
        max_age=int(auth.SESSION_TTL.total_seconds()),
        path="/",
    )
    return _out(user)


@router.post("/auth/logout", status_code=204)
def logout(
    response: Response,
    request: Request,
    session: Session = Depends(get_session),
):
    token = request.cookies.get(auth.SESSION_COOKIE)
    user = auth.resolve_session(session, token)
    auth.end_session(session, token)
    if user is not None:
        session.add(
            AuditLog(vendor_id=None, actor=user.email, action="LOGOUT", detail="")
        )
    session.commit()
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return Response(status_code=204)


@router.get("/auth/me", response_model=s.UserOut)
def me(user: User = Depends(current_user)):
    """Who the session belongs to. The frontend calls this on load to decide
    whether to show the app or the login screen."""
    return _out(user)
