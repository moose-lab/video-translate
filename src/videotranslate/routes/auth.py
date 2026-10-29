from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import APIError
from ..models.core import AuthSession, LoginAttempt, Membership, User, Workspace, utcnow
from ..security import (
    CSRF_COOKIE,
    DUMMY_HASH,
    SESSION_COOKIE,
    Identity,
    auth_response,
    csrf_cookie,
    issue_session,
    password_hasher,
    require_csrf,
    require_identity,
    reserve_login_attempt,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128, repr=False)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or not all(value.split("@")) or any(c.isspace() for c in value):
            raise ValueError("Invalid email")
        return value


class RegisterInput(LoginInput):
    name: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("Name required")
        return value.strip()


@router.post("/register", status_code=201)
def register(
    body: RegisterInput, request: Request, response: Response, db: Session = Depends(get_db)
):
    user = User(email=body.email, name=body.name, password_hash=password_hasher.hash(body.password))
    workspace = Workspace(name=f"{body.name} workspace")
    try:
        db.add_all([user, workspace])
        db.flush()
        membership = Membership(user_id=user.id, workspace_id=workspace.id, role="owner")
        db.add(membership)
        db.flush()
        # The session commit includes all three identity records in the same transaction.
        return issue_session(db, request.app.state.settings, user, workspace, membership, response)
    except IntegrityError:
        db.rollback()
        raise APIError(409, "EMAIL_EXISTS", "Email already registered") from None


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    key, window_started = reserve_login_attempt(db, request)
    user = db.scalar(select(User).where(User.email == body.email))
    if (
        not verify_password(user.password_hash if user else DUMMY_HASH, body.password)
        or user is None
    ):
        raise APIError(401, "INVALID_CREDENTIALS", "Invalid email or password")
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)
    )
    if membership is None:
        raise APIError(401, "INVALID_CREDENTIALS", "Invalid email or password")
    workspace = db.get(Workspace, membership.workspace_id)
    db.execute(
        update(LoginAttempt)
        .where(LoginAttempt.key == key, LoginAttempt.window_started == window_started)
        .values(failures=case((LoginAttempt.failures > 0, LoginAttempt.failures - 1), else_=0))
    )
    return issue_session(db, request.app.state.settings, user, workspace, membership, response)


@router.get("/me")
def me(request: Request, identity: Identity = Depends(require_identity)):
    return auth_response(identity, csrf_cookie(request, identity))


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    db.execute(
        update(AuthSession).where(AuthSession.id == identity.session.id).values(revoked_at=utcnow())
    )
    db.commit()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            secure=request.app.state.settings.is_production,
            httponly=name == SESSION_COOKIE,
            samesite="lax",
        )
