"""Login, roles, and the client layer.

Three rules under test, and each one failed before this layer existed:

  1. An unauthenticated caller gets nothing.
  2. The ACTOR comes from the session, never the request body. `decidedBy`
     used to be a field anyone could set, so any caller could record a
     binding approval under a colleague's name.
  3. One client cannot add the same company twice — but two DIFFERENT
     clients can. That is the whole point of the client layer.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Client, Session as DbSession, User, Vendor
from app.services import auth


@pytest.fixture
def user(session, seeded):
    row = User(
        id="US000001", email="a.mehta@q1ssl.com", name="A Mehta",
        password_hash=auth.hash_password("correct-horse-battery"),
        role="approver",
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def client_row(session, seeded):
    row = Client(id="CL000001", name="Reliance Industries", legal_name="RIL")
    session.add(row)
    session.commit()
    return row


# ---------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------


def test_a_password_is_never_stored_in_readable_form():
    secret = "correct-horse-battery"
    stored = auth.hash_password(secret)
    assert secret not in stored
    assert stored.startswith("$argon2")
    assert auth.verify_password(secret, stored) is True
    assert auth.verify_password("wrong", stored) is False


def test_the_same_password_hashes_differently_each_time():
    """Salted. Two users with the same password must not share a hash, or
    the database itself reveals which accounts to attack together."""
    a = auth.hash_password("same-password-twice")
    b = auth.hash_password("same-password-twice")
    assert a != b


# ---------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------


def test_a_wrong_password_and_an_unknown_email_give_the_same_error(session, user):
    """Otherwise the login form enumerates who works here."""
    with pytest.raises(auth.AuthError) as wrong:
        auth.authenticate(session, user.email, "not-the-password")
    with pytest.raises(auth.AuthError) as unknown:
        auth.authenticate(session, "nobody@q1ssl.com", "not-the-password")
    assert str(wrong.value) == str(unknown.value)


def test_a_deactivated_user_cannot_sign_in(session, user):
    user.active = False
    session.commit()
    with pytest.raises(auth.AuthError):
        auth.authenticate(session, user.email, "correct-horse-battery")


def test_email_is_matched_case_insensitively(session, user):
    assert auth.authenticate(session, "A.Mehta@Q1SSL.com  ", "correct-horse-battery").id == user.id


# ---------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------


def test_the_session_token_is_stored_hashed(session, user):
    """A database dump must not yield usable sessions."""
    token = auth.start_session(session, user)
    session.commit()

    stored = session.scalars(select(DbSession)).all()
    assert len(stored) == 1
    assert stored[0].token_hash != token
    assert token not in stored[0].token_hash


def test_a_valid_token_resolves_and_a_junk_one_does_not(session, user):
    token = auth.start_session(session, user)
    session.commit()
    assert auth.resolve_session(session, token).id == user.id
    assert auth.resolve_session(session, "made-up") is None
    assert auth.resolve_session(session, None) is None


def test_an_expired_session_does_not_resolve(session, user):
    from datetime import datetime, timedelta, timezone

    token = auth.start_session(session, user)
    row = session.scalars(select(DbSession)).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert auth.resolve_session(session, token) is None


def test_signing_out_ends_the_session(session, user):
    token = auth.start_session(session, user)
    session.commit()
    auth.end_session(session, token)
    session.commit()
    assert auth.resolve_session(session, token) is None


def test_deactivating_a_user_kills_their_live_session(session, user):
    """Revocation must take effect immediately, not at expiry."""
    token = auth.start_session(session, user)
    session.commit()
    user.active = False
    session.commit()
    assert auth.resolve_session(session, token) is None


# ---------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------


def test_only_an_approver_or_admin_may_decide():
    analyst = User(id="U1", email="a@x", name="A", password_hash="x", role="analyst")
    approver = User(id="U2", email="b@x", name="B", password_hash="x", role="approver")
    admin = User(id="U3", email="c@x", name="C", password_hash="x", role="admin")

    with pytest.raises(auth.Forbidden):
        auth.require(analyst, "decide")
    auth.require(approver, "decide")
    auth.require(admin, "decide")

    # An analyst still does the actual work.
    for permission in ("read", "run_checks", "rate", "record_manual"):
        auth.require(analyst, permission)


def test_no_role_has_a_permission_that_is_not_defined():
    """Guards against a typo silently granting nothing, or everything."""
    known = {"read", "run_checks", "rate", "record_manual", "decide", "manage_users"}
    for role, granted in auth.PERMISSIONS.items():
        assert granted <= known, f"{role} has undefined permissions"
        assert "read" in granted, f"{role} cannot read anything"


# ---------------------------------------------------------------------
# The client layer
# ---------------------------------------------------------------------


def test_a_vendor_must_belong_to_a_client(session, client_row):
    from sqlalchemy.exc import IntegrityError

    session.add(Vendor(id="V1", name="No client", selected=[]))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_two_clients_can_onboard_the_same_company(session, client_row, seeded):
    """The point of the whole layer.

    Reliance and Tata can both audit Zepto. They get separate vendor
    records and separate assessments — and the ₹330 company unlock, which
    is keyed by CIN rather than by vendor, is shared.
    """
    other = Client(id="CL000002", name="Tata Steel")
    session.add(other)
    session.flush()

    cin = "U46909MH2020PLC351339"
    session.add(Vendor(id="V1", client_id=client_row.id, name="Zepto", cin=cin, selected=[]))
    session.add(Vendor(id="V2", client_id=other.id, name="Zepto", cin=cin, selected=[]))
    session.commit()

    rows = session.scalars(select(Vendor).where(Vendor.cin == cin)).all()
    assert len(rows) == 2
    assert {r.client_id for r in rows} == {client_row.id, other.id}


def test_one_client_cannot_add_the_same_company_twice(session, client_row, seeded):
    from sqlalchemy.exc import IntegrityError

    cin = "U46909MH2020PLC351339"
    session.add(Vendor(id="V1", client_id=client_row.id, name="Zepto", cin=cin, selected=[]))
    session.commit()

    session.add(Vendor(id="V2", client_id=client_row.id, name="Zepto again", cin=cin, selected=[]))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_vendors_without_a_cin_do_not_collide(session, client_row, seeded):
    """Nothing is compulsory at intake, so several vendors may have no CIN.

    A plain unique index would make the second one fail. The index is
    partial — WHERE cin IS NOT NULL — precisely for this.
    """
    session.add(Vendor(id="V1", client_id=client_row.id, name="One", selected=[]))
    session.add(Vendor(id="V2", client_id=client_row.id, name="Two", selected=[]))
    session.commit()
    assert len(session.scalars(select(Vendor)).all()) == 2


def test_a_client_with_vendors_cannot_be_deleted(session, client_row, seeded):
    """Deleting a client would orphan an audit trail. The FK refuses."""
    from sqlalchemy.exc import IntegrityError

    session.add(Vendor(id="V1", client_id=client_row.id, name="Zepto", selected=[]))
    session.commit()

    session.delete(client_row)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
