"""Typed multi-format adapter using the existing fenced prepared-object lifecycle."""

import secrets

from ..models.analysis import PreparedObject
from ..models.core import Asset, new_id
from .contracts import LeaseLost
from .prepared import bounded, current_operation

FORMATS = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "ass": "text/x-ssa",
}


def store(context, operation_id, path, metadata, *, kind, format):
    if format not in FORMATS:
        raise ValueError("Unsupported prepared media format")
    data = dict(metadata, kind=kind, format=format, content_type=FORMATS[format])
    bounded(data, 65536)
    with context.session_factory.begin() as db:
        project, run = context._locked(db)
        operation = current_operation(db, run)
        if not operation or operation.id != operation_id:
            raise ValueError("Operation mismatch")
        object_id, token = new_id(), secrets.token_hex(32)
        key = f"{project.workspace_id}/{project.id}/prepared/{object_id}"
        db.add(
            PreparedObject(
                id=object_id,
                project_id=project.id,
                workspace_id=project.workspace_id,
                operation_id=operation_id,
                storage_key=key,
                metadata_json=data,
                reservation_token=token,
            )
        )
    try:
        with path.open("rb") as stream:
            context.storage.put(key, stream, FORMATS[format])
    finally:
        from .prepared_objects import settle_prepared

        with context.session_factory.begin() as db:
            active = settle_prepared(db, context, object_id, token)
        if not active:
            raise LeaseLost()
    return object_id


def publish(db, run, entries):
    operation = current_operation(db, run)
    if not operation or operation.phase != "prepared":
        raise ValueError("No prepared delivery")
    result = {}
    for entry in entries:
        object_id = entry["object_id"]
        item = db.get(PreparedObject, object_id)
        if (
            not item
            or item.operation_id != operation.id
            or item.project_id != run.project_id
            or item.workspace_id != run.workspace_id
            or item.state != "orphan"
            or not item.write_settled
            or item.delete_pending
        ):
            raise ValueError("Invalid prepared media lineage")
        data = item.metadata_json
        expected = dict(
            entry["metadata"],
            kind=entry["kind"],
            format=entry["format"],
            content_type=FORMATS[entry["format"]],
        )
        if (
            data != expected
            or item.storage_key != f"{run.workspace_id}/{run.project_id}/prepared/{object_id}"
        ):
            raise ValueError("Prepared bytes differ from validated delivery manifest")
        if data.get("format") not in FORMATS or data.get("content_type") != FORMATS[data["format"]]:
            raise ValueError("Invalid media manifest")
        asset = Asset(
            id=new_id(),
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            filename=f"{data['kind']}.{data['format']}",
            content_type=data["content_type"],
            storage_key=item.storage_key,
            kind=data["kind"],
            sha256=data["sha256"],
            byte_size=data["byte_size"],
        )
        db.add(asset)
        db.flush()
        item.state, item.asset_id = "published", asset.id
        result[object_id] = asset.id
    return result
