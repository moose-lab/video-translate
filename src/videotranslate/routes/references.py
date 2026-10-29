"""Authenticated bounded private audio uploads; CPU validation runs in the worker."""

import hashlib
import secrets
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ..db import get_db
from ..dubbing import references
from ..dubbing.contracts import ID, Revision, SourceGuard, Strict, Text
from ..dubbing.ownership import owner, project_for
from ..errors import APIError
from ..languages.catalog import resolve
from ..models.analysis import ReferenceRequest
from ..models.core import new_id, utcnow
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(prefix="/projects/{project_id}", tags=["references"])
json_router = APIRouter(route_class=BoundedDubbingRoute)


class ReferenceText(Strict):
    text: Text
    language: Annotated[str, Field(min_length=2, max_length=40)]

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Reference text required")
        return value

    @field_validator("language")
    @classmethod
    def explicit_language(cls, value):
        item = resolve(value)
        if item["is_auto"]:
            raise ValueError("Explicit reference language required")
        return item["tag"]


class ExtractBody(SourceGuard, ReferenceText):
    segment_id: ID
    segment_revision: Revision
    speaker_id: ID | None
    media: Literal["source", "vocals"] = "source"


class VersionBody(ReferenceText):
    parent_version_id: ID


class BindingBody(SourceGuard):
    revision: Annotated[int, Field(ge=0)]
    reference_version_id: ID | None
    expected_segment_revision: Revision | None = None
    expected_speaker_revision: Revision | None = None


@json_router.post("/references/extract", status_code=202)
def extract(
    project_id: str,
    body: ExtractBody,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = references.request_extract(db, project, body, identity.user.id)
    db.commit()
    return result


def persist_upload(request, project_id, identity, file, body):
    """CPU-free staging outside DB transactions; retain private orphan lineage."""
    limit = 64 * 1024 * 1024
    digest, size = hashlib.sha256(), 0
    while chunk := file.file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise APIError(413, "UPLOAD_TOO_LARGE", "Reference exceeds upload limit")
        digest.update(chunk)
    if size == 0:
        raise APIError(422, "EMPTY_UPLOAD", "Reference is empty")
    file.file.seek(0)
    record_id, token = new_id(), secrets.token_hex(32)
    key = f"{identity.workspace.id}/{project_id}/reference-uploads/{record_id}"
    with request.app.state.session_factory.begin() as db:
        project = project_for(db, identity, project_id, write=True)
        record = ReferenceRequest(
            id=record_id,
            **owner(project),
            origin="uploaded",
            actor_id=identity.user.id,
            payload=body.model_dump(),
            upload_key=key,
            upload_size=size,
            upload_sha256=digest.hexdigest(),
            upload_state="writing",
            upload_token=token,
            upload_lease_expires_at=utcnow() + timedelta(minutes=5),
        )
        db.add(record)
    failed = False
    try:
        request.app.state.storage.put(key, file.file, "application/octet-stream")
    except Exception:
        failed = True
    from ..execution.uploads import settle_upload

    result, enqueue_error = None, None
    with request.app.state.session_factory.begin() as db:
        project, record, owns = settle_upload(db, identity.workspace.id, record_id, token)
        if not failed and owns and project.deleted_at is None:
            try:
                # Keep the settled input/orphan checkpoint even if queue creation
                # fails, while serializing enqueue against concurrent GC fencing.
                with db.begin_nested():
                    result = references.enqueue(db, project, record)
            except Exception as error:
                enqueue_error = error
    if project.deleted_at is not None:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    if isinstance(enqueue_error, APIError):
        raise enqueue_error
    if result is None:
        raise APIError(503, "STORAGE_UNAVAILABLE", "Reference could not be stored", retryable=True)
    return result


@router.post("/references/upload", status_code=202)
async def upload(project_id: str, request: Request, identity: Identity = Depends(require_csrf)):
    # Authenticate and authorize BEFORE reading/spooling any body, with SQL off-loop.
    def authorize():
        with request.app.state.session_factory() as db:
            project_for(db, identity, project_id)

    await run_in_threadpool(authorize)
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise APIError(422, "INVALID_UPLOAD", "Use one audio file and reference text/language")

    async def bounded():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 64 * 1024 * 1024 + 64 * 1024:
                raise APIError(413, "UPLOAD_TOO_LARGE", "Reference exceeds upload limit")
            yield chunk

    try:
        form = await MultiPartParser(request.headers, bounded(), max_files=1, max_fields=2).parse()
    except MultiPartException:
        raise APIError(
            422, "INVALID_UPLOAD", "Use one audio file and reference text/language"
        ) from None
    try:
        file = form.get("file")
        if (
            not isinstance(file, UploadFile)
            or len(form.multi_items()) != 3
            or set(form) != {"file", "text", "language"}
        ):
            raise APIError(422, "INVALID_UPLOAD", "Use one audio file and reference text/language")
        try:
            body = ReferenceText.model_validate(
                {"text": form["text"], "language": form["language"]}
            )
        except ValueError:
            raise APIError(422, "INVALID_REFERENCE", "Invalid reference text/language") from None
        return await run_in_threadpool(persist_upload, request, project_id, identity, file, body)
    finally:
        await form.close()


@json_router.get("/references")
def list_references(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return references.list_versions(
        db, project_for(db, identity, project_id), limit=limit, offset=offset
    )


@json_router.get("/references/{reference_id}/versions")
def versions(
    project_id: str,
    reference_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return references.list_versions(
        db, project_for(db, identity, project_id), reference_id, limit, offset
    )


@json_router.post("/references/{reference_id}/versions", status_code=201)
def version(
    project_id: str,
    reference_id: str,
    body: VersionBody,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = references.new_version(db, project, reference_id, body, identity.user.id)
    db.commit()
    return result


@json_router.put("/speakers/{speaker_id}/reference")
def role_binding(
    project_id: str,
    speaker_id: str,
    body: BindingBody,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if body.expected_speaker_revision is None:
        raise APIError(422, "INVALID_REFERENCE", "Expected speaker revision required")
    project = project_for(db, identity, project_id, write=True)
    result = references.put_binding(db, project, "role", speaker_id, body, identity.user.id)
    db.commit()
    return result


@json_router.put("/segments/{segment_id}/reference")
def line_binding(
    project_id: str,
    segment_id: str,
    body: BindingBody,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if body.expected_segment_revision is None:
        raise APIError(422, "INVALID_REFERENCE", "Expected segment revision required")
    project = project_for(db, identity, project_id, write=True)
    result = references.put_binding(db, project, "line", segment_id, body, identity.user.id)
    db.commit()
    return result


@json_router.get("/speakers/{speaker_id}/reference")
def get_role_binding(
    project_id: str,
    speaker_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return references.binding_json(
        db,
        project_for(db, identity, project_id),
        "role",
        speaker_id,
        history_limit=limit,
        offset=offset,
    )


@json_router.get("/segments/{segment_id}/reference")
def get_line_binding(
    project_id: str,
    segment_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return references.binding_json(
        db,
        project_for(db, identity, project_id),
        "line",
        segment_id,
        history_limit=limit,
        offset=offset,
    )


router.include_router(json_router)
