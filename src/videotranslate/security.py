"""Opaque session authentication, double-submit CSRF and persistent login throttling."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request, Response
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import Settings
from .db import get_db
from .errors import APIError
from .models.core import AuthSession, LoginAttempt, Membership, User, Workspace, utcnow

SESSION_COOKIE = "vt_session"
CSRF_COOKIE = "vt_csrf"
password_hasher = PasswordHasher()
# Missing users still incur the same password verification work.
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def secret_hash(value: str, settings: Settings) -> str:
    return hmac.new(
        settings.server_secret.get_secret_value().encode(), value.encode(), hashlib.sha256
    ).hexdigest()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except VerificationError:
        return False


@dataclass(frozen=True)
class Identity:
    user: User
    workspace: Workspace
    membership: Membership
    session: AuthSession


def require_identity(request: Request, db: Session = Depends(get_db)) -> Identity:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 256:
        raise APIError(401, "UNAUTHENTICATED", "Authentication required")
    row = db.execute(
        select(AuthSession, User, Workspace, Membership)
        .join(User, User.id == AuthSession.user_id)
        .join(Workspace, Workspace.id == AuthSession.workspace_id)
        .join(
            Membership, (Membership.workspace_id == Workspace.id) & (Membership.user_id == User.id)
        )
        .where(
            AuthSession.token_hash == secret_hash(token, request.app.state.settings),
            AuthSession.expires_at > utcnow(),
            AuthSession.revoked_at.is_(None),
        )
    ).first()
    if row is None:
        raise APIError(401, "UNAUTHENTICATED", "Authentication required")
    auth_session, user, workspace, membership = row
    return Identity(user, workspace, membership, auth_session)


def csrf_cookie(request: Request, identity: Identity) -> str:
    token = request.cookies.get(CSRF_COOKIE, "")
    if (
        not token
        or len(token) > 256
        or not hmac.compare_digest(
            secret_hash(token, request.app.state.settings), identity.session.csrf_hash
        )
    ):
        raise APIError(403, "CSRF_FAILED", "CSRF verification failed")
    return token


def require_csrf(request: Request, identity: Identity = Depends(require_identity)) -> Identity:
    token = csrf_cookie(request, identity)
    header = request.headers.get("X-CSRF-Token", "")
    if len(header) > 256 or not hmac.compare_digest(header.encode(), token.encode()):
        raise APIError(403, "CSRF_FAILED", "CSRF verification failed")
    return identity


def auth_response(identity: Identity, csrf: str) -> dict:
    return {
        "user": {"id": identity.user.id, "email": identity.user.email, "name": identity.user.name},
        "workspace": {
            "id": identity.workspace.id,
            "name": identity.workspace.name,
            "role": identity.membership.role,
        },
        "csrf_token": csrf,
    }


def issue_session(
    db: Session,
    settings: Settings,
    user: User,
    workspace: Workspace,
    membership: Membership,
    response: Response,
) -> dict:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    auth_session = AuthSession(
        user_id=user.id,
        workspace_id=workspace.id,
        token_hash=secret_hash(token, settings),
        csrf_hash=secret_hash(csrf, settings),
        expires_at=utcnow() + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(auth_session)
    db.commit()
    for name, value, http_only in [(SESSION_COOKIE, token, True), (CSRF_COOKIE, csrf, False)]:
        response.set_cookie(
            name,
            value,
            max_age=settings.session_ttl_seconds,
            httponly=http_only,
            secure=settings.is_production,
            samesite="lax",
            path="/",
        )
    return auth_response(Identity(user, workspace, membership, auth_session), csrf)


def reserve_login_attempt(db: Session, request: Request) -> tuple[str, datetime]:
    """Atomic reservation caps concurrent attempts and avoids unbounded per-email rows."""
    settings = request.app.state.settings
    peer = request.client.host if request.client else "unknown"
    key = secret_hash("login-peer:" + peer, settings)
    now = utcnow()
    cutoff = now - timedelta(seconds=settings.login_window_seconds)
    db.execute(delete(LoginAttempt).where(LoginAttempt.window_started < cutoff))
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    statement = insert(LoginAttempt).values(key=key, failures=1, window_started=now)
    statement = statement.on_conflict_do_update(
        index_elements=[LoginAttempt.key],
        set_={
            "failures": case(
                (LoginAttempt.failures <= settings.login_max_attempts, LoginAttempt.failures + 1),
                else_=settings.login_max_attempts + 1,
            )
        },
    )
    attempts, window_started = db.execute(
        statement.returning(LoginAttempt.failures, LoginAttempt.window_started)
    ).one()
    db.commit()
    if attempts > settings.login_max_attempts:
        raise APIError(
            429,
            "LOGIN_RATE_LIMITED",
            "Too many login attempts; try again later",
            retryable=True,
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    return key, window_started
