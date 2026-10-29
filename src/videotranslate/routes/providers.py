"""Owner-controlled nonsecret provider settings and encrypted credentials."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import APIError
from ..execution.inputs import set_inputs
from ..models.core import Project, utcnow
from ..models.providers import ProviderConnection, ProviderConnectionRevision, WorkspaceCredential
from ..providers.network import validate_url
from ..providers.settings import SLOTS
from ..providers.vault import encrypt_credential
from ..security import Identity, require_csrf, require_identity

router = APIRouter(tags=["providers"])


class CredentialBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    token: SecretStr | None = None
    clear: bool = False

    @model_validator(mode="after")
    def validate_token(self):
        if self.token is not None and (self.clear or not self.token.get_secret_value().strip()):
            raise ValueError("Invalid credential operation")
        return self


class ProviderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    adapter: Literal["hf_router", "openai_compatible", "omnivoice", "demucs", "nvidia_stream"]
    endpoint: str | None = Field(default=None, max_length=300)
    space_id: str | None = Field(default=None, max_length=150)
    model: str | None = Field(default=None, max_length=200)
    controls: dict = Field(default_factory=dict)
    credential_ref: Literal["huggingface", "translation"] | None = None


def owner(identity):
    if identity.membership.role != "owner":
        raise APIError(403, "FORBIDDEN", "Owner access required")


def conflict():
    raise APIError(409, "REVISION_CONFLICT", "Settings changed; reload and try again")


def safe_credential(row):
    return {
        "configured": bool(row and row.ciphertext),
        "revision": row.revision if row else 0,
        "updated_at": row.updated_at if row else None,
    }


@router.get("/provider-settings")
def get_settings(identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    creds = db.scalars(
        select(WorkspaceCredential).where(WorkspaceCredential.workspace_id == identity.workspace.id)
    ).all()
    connections = db.scalars(
        select(ProviderConnection).where(ProviderConnection.workspace_id == identity.workspace.id)
    ).all()
    return {
        "credentials": {
            kind: safe_credential(next((c for c in creds if c.kind == kind), None))
            for kind in ("huggingface", "translation")
        },
        "providers": {
            slot: next(
                (
                    {"revision": c.revision, **c.settings, "check_state": c.check_state}
                    for c in connections
                    if c.slot == slot
                ),
                {"revision": 0},
            )
            for slot in SLOTS
        },
    }


@router.put("/credentials/{kind}")
def put_credential(
    kind: Literal["huggingface", "translation"],
    body: CredentialBody,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    owner(identity)
    row = db.scalar(
        select(WorkspaceCredential).where(
            WorkspaceCredential.workspace_id == identity.workspace.id,
            WorkspaceCredential.kind == kind,
        )
    )
    if (row.revision if row else 0) != body.revision:
        conflict()
    ciphertext = (
        None
        if body.clear
        else (
            encrypt_credential(
                request.app.state.settings, identity.workspace.id, body.token.get_secret_value()
            )
            if body.token is not None
            else (row.ciphertext if row else None)
        )
    )
    if row is None:
        row = WorkspaceCredential(
            workspace_id=identity.workspace.id, kind=kind, revision=1, ciphertext=ciphertext
        )
        db.add(row)
    else:
        changed = db.execute(
            update(WorkspaceCredential)
            .where(WorkspaceCredential.id == row.id, WorkspaceCredential.revision == body.revision)
            .values(revision=body.revision + 1, ciphertext=ciphertext, updated_at=utcnow())
        )
        if changed.rowcount != 1:
            conflict()
        db.refresh(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict()
    return safe_credential(row)


@router.put("/providers/{slot}")
def put_provider(
    slot: str,
    body: ProviderBody,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    owner(identity)
    if slot not in SLOTS:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    allowed_adapters = {
        "separation": {"demucs"},
        "transcription": {"nvidia_stream"},
        "translation": {"hf_router", "openai_compatible"},
        "synthesis": {"omnivoice"},
        "verification": {"hf_router"},
    }
    valid_refs = {
        "hf_router": {"huggingface"},
        "openai_compatible": {"translation", None},
        "omnivoice": {"huggingface", None},
        "demucs": {None},
        "nvidia_stream": {None},
    }
    controls = {
        "omnivoice": {"ns", "gs", "dn", "sp", "du", "pp", "pot"},
        "demucs": set(),
        "nvidia_stream": {"max_speakers"},
        "hf_router": set(),
        "openai_compatible": set(),
    }
    if (
        body.adapter not in allowed_adapters[slot]
        or body.credential_ref not in valid_refs[body.adapter]
        or set(body.controls) - controls[body.adapter]
    ):
        raise APIError(422, "VALIDATION_ERROR", "Invalid provider configuration")
    if any(not isinstance(v, (int, float, bool, type(None))) for v in body.controls.values()):
        raise APIError(422, "VALIDATION_ERROR", "Invalid provider controls")
    if body.space_id and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", body.space_id
    ):
        raise APIError(422, "VALIDATION_ERROR", "Invalid provider configuration")
    if body.endpoint:
        try:
            hosts = {
                h.strip().lower()
                for h in request.app.state.settings.provider_allowed_hosts.split(",")
                if h.strip()
            }
            validate_url(body.endpoint, allowed_hosts=hosts)
        except ValueError:
            raise APIError(422, "VALIDATION_ERROR", "Invalid provider endpoint") from None
    row = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == identity.workspace.id,
            ProviderConnection.slot == slot,
        )
    )
    if (row.revision if row else 0) != body.revision:
        conflict()
    values = body.model_dump(exclude={"revision"})
    if row is None:
        row = ProviderConnection(
            workspace_id=identity.workspace.id, slot=slot, revision=1, settings=values
        )
        db.add(row)
    else:
        result = db.execute(
            update(ProviderConnection)
            .where(ProviderConnection.id == row.id, ProviderConnection.revision == body.revision)
            .values(
                revision=body.revision + 1, settings=values, check_state=None, updated_at=utcnow()
            )
        )
        if result.rowcount != 1:
            conflict()
    db.add(
        ProviderConnectionRevision(
            workspace_id=identity.workspace.id,
            slot=slot,
            revision=body.revision + 1,
            settings=values,
        )
    )
    projects = db.scalars(
        select(Project)
        .where(Project.workspace_id == identity.workspace.id, Project.deleted_at.is_(None))
        .order_by(Project.id)
    ).all()
    for project in projects:
        set_inputs(db, project, {"provider." + slot: values})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        conflict()
    return {"revision": body.revision + 1, **values, "check_state": None}
