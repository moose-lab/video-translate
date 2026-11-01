"""Guarded source-link admission and pure owned discovery."""

import hashlib
import hmac

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func

from ..errors import APIError
from ..execution.contracts import RunCreate
from ..execution.inputs import fingerprint
from ..media.source_download import ImportRejected, canonical_input
from ..models.core import new_id
from ..models.execution import StageRun
from ..models.source_import import SourceImport
from ..providers.vault import encrypt_credential
from .ownership import conflict, owner, scope


class SourceImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=8192, repr=False)
    revision: int = Field(ge=1)


def start(db, project, body, actor, settings):
    if body.revision != project.revision:
        conflict()
    try:
        adapter, url = canonical_input(body.url)
    except ImportRejected:
        raise APIError(
            422, "INVALID_SOURCE_URL", "Use a public HTTPS video link or YouTube video URL"
        ) from None
    signature = hmac.new(
        settings.server_secret.get_secret_value().encode(),
        fingerprint([project.id, project.revision, url]).encode(),
        hashlib.sha256,
    ).hexdigest()
    record = db.scalar(scope(SourceImport, project).where(SourceImport.signature == signature))
    if record:
        return detail(db, project, record)
    record = SourceImport(
        id=new_id(),
        **owner(project),
        actor_id=actor,
        encrypted_url=encrypt_credential(settings, project.workspace_id, url),
        adapter=adapter,
        signature=signature,
        expected_revision=project.revision,
    )
    db.add(record)
    db.flush()
    from ..execution.service import create_run

    run = create_run(
        db,
        project.workspace_id,
        project.id,
        RunCreate(stage="source_import", options={"command_id": record.id}),
        guarded_command=True,
    )
    record.run_id = run.id
    db.flush()
    return detail(db, project, record)


def detail(db, project, record):
    run = db.get(StageRun, record.run_id)
    return dict(
        id=record.id,
        run_id=run.id,
        adapter=record.adapter,
        status=run.status,
        stale=run.is_stale,
        source_asset_id=record.source_asset_id,
        probe_run_id=record.probe_run_id,
        error=run.safe_error,
        next_action="upload_source"
        if run.status in {"failed", "needs_review"}
        else "review_source"
        if run.status == "succeeded"
        else "reload_source"
        if run.status == "stale"
        else None,
        created_at=record.created_at,
    )


def listing(db, project, limit=20, offset=0):
    query = scope(SourceImport, project)
    return dict(
        items=[
            detail(db, project, row)
            for row in db.scalars(
                query.order_by(SourceImport.created_at.desc(), SourceImport.id)
                .limit(limit)
                .offset(offset)
            )
        ],
        total=db.scalar(query.with_only_columns(func.count()).order_by(None)),
    )
