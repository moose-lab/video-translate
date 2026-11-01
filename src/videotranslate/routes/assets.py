"""Bounded source upload and authorized streaming downloads. Upload is not media analysis."""

import hashlib
import re
from contextlib import closing
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ..db import get_db
from ..errors import APIError
from ..models.core import Asset, Project, new_id
from ..security import Identity, require_csrf, require_identity
from ..storage import Storage
from .projects import owned_project, project_json, update_project

router = APIRouter(tags=["assets"])
ALLOWED_MEDIA = {
    ".mp4": {"video/mp4"},
    ".m4v": {"video/mp4", "video/x-m4v"},
    ".mov": {"video/quicktime"},
    ".webm": {"video/webm"},
    ".mkv": {"video/x-matroska"},
    ".avi": {"video/x-msvideo", "video/avi"},
}
CHUNK_SIZE = 1024 * 1024


def asset_json(asset: Asset) -> dict:
    return {
        name: getattr(asset, name)
        for name in (
            "id",
            "project_id",
            "filename",
            "content_type",
            "byte_size",
            "sha256",
            "kind",
            "created_at",
        )
    }


def safe_filename(filename: str) -> str:
    filename = PurePosixPath(filename.replace("\\", "/")).name
    filename = "".join(char for char in filename if ord(char) >= 32 and ord(char) != 127)
    return filename[:255]


def persist_source(
    db: Session, storage: Storage, project: Project, file: UploadFile, max_bytes: int
) -> dict:
    filename = safe_filename(file.filename or "")
    extension = PurePosixPath(filename).suffix.lower()
    declared = (file.content_type or "").lower().strip()
    if extension not in ALLOWED_MEDIA or declared not in ALLOWED_MEDIA[extension]:
        raise APIError(415, "UNSUPPORTED_MEDIA", "Upload an allowed video extension and media type")
    digest, size = hashlib.sha256(), 0
    while chunk := file.file.read(CHUNK_SIZE):
        size += len(chunk)
        if size > max_bytes:
            raise APIError(413, "UPLOAD_TOO_LARGE", "Source exceeds upload size limit")
        digest.update(chunk)
    if size == 0:
        raise APIError(422, "EMPTY_UPLOAD", "Source file is empty")
    file.file.seek(0)
    # No component comes from the supplied filename, MIME, or a remote URL.
    key = f"{project.workspace_id}/{project.id}/{uuid4().hex}"
    try:
        storage.put(key, file.file, declared)
    except Exception:
        storage.delete(key)
        raise APIError(
            503, "STORAGE_UNAVAILABLE", "Source could not be stored", retryable=True
        ) from None
    try:
        asset = Asset(
            id=new_id(),
            workspace_id=project.workspace_id,
            project_id=project.id,
            filename=filename,
            content_type=declared,
            byte_size=size,
            sha256=digest.hexdigest(),
            kind="source_video",
            storage_key=key,
        )
        db.add(asset)
        db.flush()
        update_project(db, project, {"source_asset_id": asset.id, "status": "uploaded"})
        from ..execution.events import append_event
        from ..execution.inputs import set_inputs

        set_inputs(db, project, {"source.video": {"asset_id": asset.id, "sha256": asset.sha256}})
        append_event(
            db, project, "source.upload_completed", facts={"asset_id": asset.id, "byte_size": size}
        )
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return {"project": project_json(project), "asset": asset_json(asset)}


@router.post(
    "/projects/{project_id}/source",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_source(
    project_id: str,
    request: Request,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    # Await synchronous SQL off the ASGI loop before consuming or spooling the body.
    project = await run_in_threadpool(owned_project, db, identity.workspace.id, project_id)
    limit = request.app.state.settings.upload_max_bytes
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise APIError(422, "INVALID_UPLOAD", "Use a multipart upload with one file field")

    async def bounded_body():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            # Bound multipart spooling before parsing, with a fixed allowance for form headers.
            if total > limit + 64 * 1024:
                raise APIError(413, "UPLOAD_TOO_LARGE", "Source exceeds upload size limit")
            yield chunk

    try:
        parser = MultiPartParser(request.headers, bounded_body(), max_files=1, max_fields=0)
        form = await parser.parse()
    except MultiPartException:
        raise APIError(
            422, "INVALID_UPLOAD", "Use a multipart upload with one file field"
        ) from None
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile) or len(form.multi_items()) != 1:
            raise APIError(422, "INVALID_UPLOAD", "Use a multipart upload with one file field")
        return await run_in_threadpool(
            persist_source, db, request.app.state.storage, project, file, limit
        )
    finally:
        await form.close()


@router.get("/projects/{project_id}/assets")
def list_assets(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    owned_project(db, identity.workspace.id, project_id)
    query = (
        select(Asset)
        .join(Project, Project.id == Asset.project_id)
        .where(
            Asset.project_id == project_id,
            Asset.workspace_id == identity.workspace.id,
            Project.workspace_id == identity.workspace.id,
            Project.deleted_at.is_(None),
        )
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    assets = db.scalars(
        query.order_by(Asset.created_at.desc(), Asset.id.asc()).limit(limit).offset(offset)
    ).all()
    return {"items": [asset_json(asset) for asset in assets], "total": total}


def byte_range(value: str | None, size: int) -> tuple[int, int]:
    if value is None:
        return 0, size - 1
    try:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value) if len(value) <= 128 else None
        if match is None or not any(match.groups()):
            raise ValueError
        first, last = match.groups()
        if first:
            start, end = int(first), min(int(last), size - 1) if last else size - 1
        else:
            suffix = int(last)
            if suffix <= 0:
                raise ValueError
            start, end = max(size - suffix, 0), size - 1
        if start >= size or end < start:
            raise ValueError
        return start, end
    except ValueError:
        raise APIError(
            416,
            "INVALID_RANGE",
            "Requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        ) from None


@router.get("/assets/{asset_id}/content")
def asset_content(
    asset_id: str,
    request: Request,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    asset = db.scalar(
        select(Asset)
        .join(Project, Project.id == Asset.project_id)
        .where(
            Asset.id == asset_id,
            Asset.workspace_id == identity.workspace.id,
            Project.workspace_id == identity.workspace.id,
            Project.deleted_at.is_(None),
        )
    )
    if asset is None:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    if asset.kind == "waveform" or asset.filename == "waveform.json":
        from fastapi.responses import Response

        from ..dubbing.waveforms_execution import content_for_asset

        return Response(
            content_for_asset(db, asset, request.app.state.storage),
            media_type="application/json",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    # Copy the authorized immutable read facts before ending the SQL scope.
    # A browser can keep a range body open for minutes; it must not reserve a
    # pooled connection while storage opens or the receiver applies backpressure.
    filename, size, content_type, storage_key = (
        asset.filename,
        asset.byte_size,
        asset.content_type,
        asset.storage_key,
    )
    value = request.headers.get("range")
    start, end = byte_range(value, size)
    db.rollback()
    try:
        stream = request.app.state.storage.open(storage_key, start=start, end=end)
    except Exception:
        raise APIError(
            503, "STORAGE_UNAVAILABLE", "Source is temporarily unavailable", retryable=True
        ) from None

    def chunks():
        try:
            with closing(stream):
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise OSError("Incomplete media stream")
                    remaining -= len(chunk)
                    yield chunk
        except Exception:
            # Headers may already be sent. Abort, but never propagate a private path or signed URL.
            raise RuntimeError("Media stream interrupted") from None

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f'attachment; filename="source{PurePosixPath(filename).suffix}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if value is not None:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        chunks(), status_code=206 if value else 200, media_type=content_type, headers=headers
    )
