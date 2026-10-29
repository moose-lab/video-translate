"""Transactional execution mutations. Lock project before run/input/event state."""

import json
import secrets
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ..errors import APIError
from ..models.core import Project, utcnow
from ..models.execution import RunAttempt, StageRun
from ..routes.projects import owned_project
from .contracts import RunCreate, StageResult
from .events import append_event
from .inputs import fingerprint, initialize_inputs, is_current, lock_project, set_inputs
from .registry import STAGES, get_stage


def create_run(
    db: Session,
    workspace_id: str,
    project_id: str,
    request: RunCreate,
    idempotency_key: str | None = None,
    *,
    registry=None,
):
    project = lock_project(db, owned_project(db, workspace_id, project_id))
    if idempotency_key is not None and (
        not idempotency_key
        or len(idempotency_key) > 128
        or not idempotency_key.isascii()
        or not all(33 <= ord(c) < 127 for c in idempotency_key)
    ):
        raise APIError(422, "INVALID_IDEMPOTENCY_KEY", "Invalid idempotency key")
    definition = get_stage(request.stage, registry)
    options = definition.validate_options(request.options)
    initialize_inputs(db, project)
    snapshot = definition.resolve_inputs(db, project, request)
    dependency_fingerprint = fingerprint(snapshot)
    request_fingerprint = fingerprint(
        request.model_dump() | {"options": options, "dependencies": snapshot}
    )
    if idempotency_key:
        prior = db.scalar(
            select(StageRun).where(
                StageRun.project_id == project.id, StageRun.idempotency_key == idempotency_key
            )
        )
        if prior:
            if prior.request_fingerprint != request_fingerprint:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "Key was used with different inputs")
            return prior
    scope = ":".join(filter(None, [request.stage, request.target_language, request.segment_id]))
    prior = db.scalar(
        select(StageRun)
        .where(
            StageRun.project_id == project.id,
            StageRun.scope_key == scope,
            StageRun.request_fingerprint == request_fingerprint,
            StageRun.status == "succeeded",
            StageRun.is_stale.is_(False),
        )
        .order_by(StageRun.created_at.desc())
    )
    if prior and idempotency_key is None:
        return prior
    run = StageRun(
        workspace_id=workspace_id,
        project_id=project.id,
        stage=request.stage,
        scope_key=scope,
        options=options,
        target_language=request.target_language,
        segment_id=request.segment_id,
        input_project_revision=project.revision,
        dependency_snapshot=snapshot,
        dependency_fingerprint=dependency_fingerprint,
        request_fingerprint=request_fingerprint,
        output_key=f"output.{scope}",
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()
    append_event(db, project, "run.queued", run=run, facts={"revision": project.revision})
    return run


def owned_run(db: Session, workspace_id: str, run_id: str) -> StageRun:
    run = db.scalar(
        select(StageRun)
        .join(Project, Project.id == StageRun.project_id)
        .where(
            StageRun.id == run_id,
            StageRun.workspace_id == workspace_id,
            Project.workspace_id == workspace_id,
            Project.deleted_at.is_(None),
        )
    )
    if run is None:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    return run


def run_json(db: Session, run: StageRun, *, attempts=False) -> dict:
    fields = (
        "id",
        "project_id",
        "stage",
        "target_language",
        "segment_id",
        "options",
        "input_project_revision",
        "dependency_fingerprint",
        "status",
        "is_stale",
        "attempt_count",
        "auto_failures",
        "due_at",
        "cancel_requested_at",
        "result",
        "safe_error",
        "provider",
        "model",
        "remote_id",
        "remote_state",
        "created_at",
        "updated_at",
        "finished_at",
    )
    result = {key: getattr(run, key) for key in fields}
    if attempts:
        result["attempts"] = [
            {
                key: getattr(a, key)
                for key in ("number", "started_at", "finished_at", "outcome", "safe_error")
            }
            for a in db.scalars(
                select(RunAttempt).where(RunAttempt.run_id == run.id).order_by(RunAttempt.number)
            )
        ]
    return result


# Worker operations join their caller's short transaction. No handler runs here.
def _lock_run_project(db: Session, run_id: str):
    candidate = db.scalar(select(StageRun.project_id).where(StageRun.id == run_id))
    if candidate is None:
        return None, None
    project = db.get(Project, candidate)
    if project is None:
        return None, None
    # Also lock deleted rows so active leases can be retired safely after deletion.
    db.execute(
        update(Project)
        .where(Project.id == project.id)
        .values(event_sequence=Project.event_sequence)
    )
    db.refresh(project)
    run = db.scalar(
        select(StageRun).where(StageRun.id == run_id).execution_options(populate_existing=True)
    )
    return project, run


def _valid_lease(run, token, now):
    return bool(
        run
        and run.lease_token == token
        and run.status in {"running", "cancelling"}
        and run.lease_expires_at
        and run.lease_expires_at > now
    )


def _end_attempt(db, run, outcome, error=None):
    attempt = db.scalar(
        select(RunAttempt).where(
            RunAttempt.run_id == run.id, RunAttempt.number == run.attempt_count
        )
    )
    if attempt and attempt.finished_at is None:
        attempt.finished_at, attempt.outcome, attempt.safe_error = utcnow(), outcome, error


def _clear_lease(run):
    run.lease_token = run.lease_owner = run.lease_expires_at = None
    run.updated_at = utcnow()


def claim_run(db: Session, owner: str, *, lease_seconds: int = 60, registry=None):
    if not 1 <= lease_seconds <= 3600 or not owner or len(owner) > 120:
        raise ValueError("Invalid worker lease settings")
    now = utcnow()
    ready = or_(
        and_(StageRun.status.in_(["queued", "retry_wait"]), StageRun.due_at <= now),
        and_(StageRun.status.in_(["running", "cancelling"]), StageRun.lease_expires_at <= now),
    )
    candidates = db.scalars(
        select(StageRun.id)
        .join(Project, Project.id == StageRun.project_id)
        .where(ready, Project.deleted_at.is_(None))
        .order_by(StageRun.due_at, StageRun.created_at, StageRun.id)
        .limit(100)
    ).all()
    for run_id in candidates:
        # Skip a project another PostgreSQL transaction owns; never lock run first.
        project_id = db.scalar(select(StageRun.project_id).where(StageRun.id == run_id))
        if db.bind.dialect.name == "postgresql":
            project = db.scalar(
                select(Project).where(Project.id == project_id).with_for_update(skip_locked=True)
            )
            if project is None:
                continue
        project, run = _lock_run_project(db, run_id)
        if project.deleted_at is not None or run.stage not in (
            STAGES if registry is None else registry
        ):
            continue
        if (
            run.status in {"running", "cancelling"}
            and run.lease_expires_at
            and run.lease_expires_at <= now
        ):
            _end_attempt(db, run, "lease_expired", {"code": "LEASE_EXPIRED", "retryable": True})
            if run.remote_state == "submitting" and run.remote_id is None:
                run.status = "needs_review"
                run.safe_error = {"code": "SUBMISSION_UNCERTAIN", "retryable": False}
                _clear_lease(run)
                append_event(
                    db, project, "run.recovery", run=run, facts={"recovery": "submission_uncertain"}
                )
                continue
            if run.cancel_requested_at and run.remote_id is None:
                run.status, run.finished_at = "cancelled", now
                _clear_lease(run)
                append_event(db, project, "run.cancelled", run=run)
                continue
            if run.is_stale and run.remote_id is None:
                run.status, run.finished_at = "stale", now
                _clear_lease(run)
                append_event(db, project, "run.stale", run=run)
                continue
            run.status = "queued"
            append_event(
                db,
                project,
                "run.recovery",
                run=run,
                facts={"recovery": "resume_remote" if run.remote_id else "rerun_local"},
            )
            db.flush()
        if run.status not in {"queued", "retry_wait"} or run.due_at > now:
            continue
        token = secrets.token_hex(32)
        claimed = db.scalar(
            update(StageRun)
            .where(
                StageRun.id == run_id,
                StageRun.status == run.status,
                StageRun.attempt_count == run.attempt_count,
            )
            .values(
                status="cancelling" if run.cancel_requested_at else "running",
                lease_token=token,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now,
                attempt_count=StageRun.attempt_count + 1,
                updated_at=now,
            )
            .returning(StageRun.id)
        )
        if claimed is None:
            continue
        db.refresh(run)
        db.add(RunAttempt(run_id=run.id, number=run.attempt_count, started_at=now))
        append_event(db, project, "run.started", run=run)
        db.flush()
        return run
    return None


def heartbeat(db: Session, run_id: str, token: str, lease_seconds: int = 60) -> bool:
    project, run = _lock_run_project(db, run_id)
    now = utcnow()
    if not _valid_lease(run, token, now):
        return False
    run.heartbeat_at, run.lease_expires_at = now, now + timedelta(seconds=lease_seconds)
    return True


def finish_run(db: Session, run_id: str, token: str, result: StageResult, *, registry=None) -> bool:
    project, run = _lock_run_project(db, run_id)
    if not _valid_lease(run, token, utcnow()):
        return False
    if not isinstance(result, StageResult):
        raise ValueError("Expected stage result")
    # Bounded JSON only. Stage adapters own typed result normalization; raw provider
    # responses must never be passed to this interface.
    if len(json.dumps(result.facts, allow_nan=False)) > 65536:
        raise ValueError("Stage result exceeds limit")
    run.result = result.facts
    if run.remote_id:
        run.remote_state = "completed"
    if run.cancel_requested_at or project.deleted_at is not None:
        run.status = "cancelled"
        run.result = None
    elif run.is_stale or not is_current(db, project, run.dependency_snapshot):
        run.status, run.is_stale = "stale", True
    else:
        definition = get_stage(run.stage, registry)
        if definition.publish:
            definition.publish(db, run, result)
        set_inputs(
            db,
            project,
            {
                run.output_key: {
                    "run_id": run.id,
                    "dependencies": run.dependency_fingerprint,
                    "result": result.facts,
                }
            },
        )
        run.status = "succeeded"
    run.finished_at = utcnow()
    run.safe_error = None
    _end_attempt(db, run, run.status)
    _clear_lease(run)
    append_event(db, project, f"run.{run.status}", run=run)
    return True
