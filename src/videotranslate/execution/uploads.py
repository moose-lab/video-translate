"""Fenced raw-reference input cleanup. Storage operations never hold SQL locks."""

from sqlalchemy import func, or_, select, update

from ..models.analysis import ReferenceRequest, ReferenceVersion
from ..models.core import Asset, Project, utcnow
from ..models.execution import StageRun
from .prepared import has_prepared


def lock_upload(db, workspace_id, request_id):
    candidate = db.scalar(
        select(ReferenceRequest).where(
            ReferenceRequest.id == request_id, ReferenceRequest.workspace_id == workspace_id
        )
    )
    if candidate is None:
        return None, None
    project = db.scalar(
        select(Project).where(
            Project.id == candidate.project_id, Project.workspace_id == workspace_id
        )
    )
    if project is None:
        return None, None
    # GC also owns deleted projects, but can never cross their workspace boundary.
    db.execute(
        update(Project)
        .where(Project.id == project.id, Project.workspace_id == workspace_id)
        .values(event_sequence=Project.event_sequence)
    )
    db.refresh(project)
    record = db.scalar(
        select(ReferenceRequest)
        .where(
            ReferenceRequest.id == request_id,
            ReferenceRequest.project_id == project.id,
            ReferenceRequest.workspace_id == workspace_id,
        )
        .execution_options(populate_existing=True)
    )
    return project, record


def settle_upload(db, workspace_id, request_id, token):
    project, record = lock_upload(db, workspace_id, request_id)
    if record is None:
        raise ValueError("Upload reservation unavailable")
    owns = (
        record.upload_state == "writing" and record.upload_token == token and record.run_id is None
    )
    record.upload_write_settled = True
    if record.run_id is None:
        # A fenced writer may have recreated bytes after deletion. Re-orphan them
        # even when the GC tombstone has already committed; never enqueue it.
        record.upload_state = "orphan"
        record.upload_gc_checked_at = None
        record.upload_token = None
        record.upload_lease_expires_at = None
    return project, record, owns


def _protected(db, project, record):
    key = f"{record.workspace_id}/{record.project_id}/reference-uploads/{record.id}"
    if record.origin != "uploaded" or record.upload_key != key:
        return True
    if record.upload_lease_expires_at and record.upload_lease_expires_at > utcnow():
        return True
    # Protect the actual object and historical domain use, not only a mutable flag.
    if db.scalar(select(Asset.id).where(Asset.storage_key == key)):
        return True
    if record.run_id is None:
        return False
    run = db.scalar(
        select(StageRun).where(
            StageRun.id == record.run_id,
            StageRun.project_id == project.id,
            StageRun.workspace_id == project.workspace_id,
        )
    )
    if run is None:
        return True
    if db.scalar(select(ReferenceVersion.id).where(ReferenceVersion.run_id == run.id).limit(1)):
        return True
    if run.remote_state == "submitting" or (run.remote_id and run.remote_state != "completed"):
        return True
    if has_prepared(db, run) or (
        run.lease_token and run.lease_expires_at and run.lease_expires_at > utcnow()
    ):
        return True
    if run.status in {"queued", "running", "retry_wait", "cancelling", "needs_review"}:
        return True
    # Configuration/transient/internal failures may still recover from the same
    # original input. Invalid input and abandoned terminal jobs can be collected.
    return (
        run.status == "failed"
        and project.deleted_at is None
        and (run.safe_error or {}).get("code") not in {"INVALID_MEDIA", "MEDIA_LIMIT"}
    )


def cleanup_raw_uploads(session_factory, storage, *, workspace_id, before, limit):
    if not workspace_id or not 1 <= limit <= 1000:
        raise ValueError("Explicit cleanup scope required")
    with session_factory() as db:
        candidates = db.scalars(
            select(ReferenceRequest.id)
            .where(
                ReferenceRequest.workspace_id == workspace_id,
                ReferenceRequest.origin == "uploaded",
                ReferenceRequest.upload_key.is_not(None),
                ReferenceRequest.created_at < before,
                or_(
                    ReferenceRequest.upload_state.in_(["writing", "orphan", "deleting"]),
                    (ReferenceRequest.upload_state == "deleted")
                    & ReferenceRequest.upload_write_settled.is_(False),
                ),
            )
            # One oldest-considered queue for regular inputs and tombstones.
            # New arrivals start at creation time rather than jumping ahead of
            # every previously checked candidate; protected rows rotate too.
            .order_by(
                func.coalesce(ReferenceRequest.upload_gc_checked_at, ReferenceRequest.created_at),
                ReferenceRequest.created_at,
                ReferenceRequest.id,
            )
            .limit(limit)
        ).all()
    count = 0
    for request_id in candidates:
        with session_factory.begin() as db:
            project, record = lock_upload(db, workspace_id, request_id)
            if record is None:
                continue
            record.upload_gc_checked_at = utcnow()
            if record.upload_state not in {
                "writing",
                "orphan",
                "deleting",
                "deleted",
            } or _protected(db, project, record):
                continue
            recheck = record.upload_state == "deleted"
            key = record.upload_key
            record.upload_state, record.upload_token = "deleting", None
            record.upload_lease_expires_at = None
            record.upload_gc_checked_at = utcnow()
        try:
            storage.delete(key)
        except Exception:
            continue
        with session_factory.begin() as db:
            _, record = lock_upload(db, workspace_id, request_id)
            if record and record.upload_state == "deleting":
                record.upload_state = "deleted"
                count += not recheck
    return count
