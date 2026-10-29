"""Fenced output settlement and exact-manifest GC. Never publish from this module."""

import secrets

from sqlalchemy import func, or_, select

from ..models.analysis import PreparedObject, PrivateOperation
from ..models.core import Asset, utcnow
from .inputs import is_current
from .prepared import current_operation
from .service import _lock_run_project, _valid_lease


def lock_prepared(db, workspace_id, object_id):
    record = db.scalar(
        select(PreparedObject).where(
            PreparedObject.id == object_id, PreparedObject.workspace_id == workspace_id
        )
    )
    if record is None:
        return None, None, None, None
    operation = db.get(PrivateOperation, record.operation_id)
    project, run = _lock_run_project(db, operation.run_id)
    # A writer can commit its manifest while GC waits for this lock. Refresh
    # both rows before deciding which exact output bytes remain recoverable.
    db.refresh(operation)
    db.refresh(record)
    if (
        project is None
        or record.project_id != project.id
        or project.workspace_id != workspace_id
        or operation.project_id != project.id
        or operation.workspace_id != workspace_id
    ):
        return None, None, None, None
    return project, run, operation, record


def settle_prepared(db, context, object_id, token):
    # Settlement must outlive the worker lease; _locked would lose late-byte lineage.
    from ..models.execution import StageRun

    workspace_id = db.get(StageRun, context.run_id).workspace_id
    _, run, _, record = lock_prepared(db, workspace_id, object_id)
    if record is None:
        return False
    active = (
        record.state == "writing"
        and record.reservation_token == token
        and _valid_lease(run, context.lease_token, utcnow())
    )
    record.write_settled = True
    if record.state == "writing":
        record.state, record.reservation_token = "orphan", None
    elif record.state in {"deleting", "deleted"}:
        # Invalidate an in-flight delete's receipt too: even put-after-delete but
        # before its DB checkpoint must force a subsequent idempotent delete.
        record.delete_pending, record.reservation_token = True, None
    return active


def _manifest_contains(operation, object_id):
    payload = operation.prepared_payload or {}
    objects = payload.get("objects", [])
    return isinstance(objects, list) and object_id in objects


def _protected(db, project, run, operation, record):
    expected = f"{record.workspace_id}/{record.project_id}/prepared/{record.id}"
    if record.storage_key != expected or record.asset_id or record.state == "published":
        return True
    if db.scalar(select(Asset.id).where(Asset.storage_key == record.storage_key)):
        return True
    if _valid_lease(run, run.lease_token, utcnow()):
        return True
    current = current_operation(db, run)
    same = current is not None and current.id == operation.id
    if same and (
        run.remote_state == "submitting" or (run.remote_id and run.remote_state != "completed")
    ):
        return True  # retain unresolved paid-job inputs and their reconciliation handles
    referenced = operation.phase == "prepared" and _manifest_contains(operation, record.id)
    fresh = (
        same
        and project.deleted_at is None
        and not run.is_stale
        and is_current(db, project, run.dependency_snapshot)
    )
    if referenced and fresh:
        return True
    if referenced:
        # Retiring stale artifact bytes does not discard known terminal FileData.
        # An explicit retry can redownload it without a new named model call.
        operation.phase = "terminal" if operation.terminal_payload is not None else "ready"
    return False


def cleanup_prepared(session_factory, storage, *, workspace_id, before, limit):
    if not workspace_id or not 1 <= limit <= 1000:
        raise ValueError("Explicit cleanup scope required")
    with session_factory() as db:
        candidates = db.scalars(
            select(PreparedObject.id)
            .where(
                PreparedObject.workspace_id == workspace_id,
                PreparedObject.created_at < before,
                or_(
                    PreparedObject.state.in_(["writing", "orphan", "deleting"]),
                    (PreparedObject.state == "deleted")
                    & (
                        PreparedObject.write_settled.is_(False)
                        | PreparedObject.delete_pending.is_(True)
                    ),
                ),
            )
            .order_by(
                func.coalesce(PreparedObject.gc_checked_at, PreparedObject.created_at),
                PreparedObject.created_at,
                PreparedObject.id,
            )
            .limit(limit)
        ).all()
    count = 0
    for object_id in candidates:
        with session_factory.begin() as db:
            project, run, operation, record = lock_prepared(db, workspace_id, object_id)
            if record is None:
                continue
            record.gc_checked_at = utcnow()
            if record.state not in {"writing", "orphan", "deleting", "deleted"} or _protected(
                db, project, run, operation, record
            ):
                continue
            recheck = record.state == "deleted"
            token = secrets.token_hex(32)
            record.state = "deleted" if recheck else "deleting"
            record.reservation_token = token
            key = record.storage_key
        try:
            storage.delete(key)
        except Exception:
            continue
        with session_factory.begin() as db:
            _, _, _, record = lock_prepared(db, workspace_id, object_id)
            if record and record.state in {"deleting", "deleted"}:
                record.state = "deleted"
                # A writer that settled during I/O invalidated this receipt.
                if record.reservation_token == token:
                    record.reservation_token, record.delete_pending = None, False
                count += not recheck
    return count
