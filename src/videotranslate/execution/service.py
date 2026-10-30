"""Transactional execution mutations. Lock project before run/input/event state."""

import json
import secrets
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ..errors import APIError
from ..models.core import Project, utcnow
from ..models.execution import RunAttempt, RunRequestKey, StageRun
from ..routes.projects import owned_project
from .contracts import FailureCode, RunCreate, StageFailure, StageResult, safe_identifier
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
    reuse_active=False,
    guarded_command=False,
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
    if definition.command_only and not guarded_command:
        raise APIError(422, "COMMAND_REQUIRED", "This stage requires a guarded command")
    options = definition.validate_options(request.options)
    initialize_inputs(db, project)
    snapshot = definition.resolve_inputs(db, project, request)
    dependency_fingerprint = fingerprint(snapshot)
    request_fingerprint = fingerprint(
        request.model_dump() | {"options": options, "dependencies": snapshot}
    )
    if idempotency_key:
        alias = db.scalar(
            select(RunRequestKey).where(
                RunRequestKey.project_id == project.id,
                RunRequestKey.workspace_id == workspace_id,
                RunRequestKey.key == idempotency_key,
            )
        )
        if alias:
            if alias.request_fingerprint != request_fingerprint:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "Key was used with different inputs")
            return owned_run(db, workspace_id, alias.run_id)
        prior = db.scalar(
            select(StageRun).where(
                StageRun.project_id == project.id, StageRun.idempotency_key == idempotency_key
            )
        )
        if prior:
            if prior.request_fingerprint != request_fingerprint:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "Key was used with different inputs")
            return prior
    suffix = (
        safe_identifier(definition.scope_suffix(request), 60) if definition.scope_suffix else None
    )
    scope = ":".join(
        filter(None, [request.stage, request.target_language, request.segment_id, suffix])
    )
    if idempotency_key is None or request.stage in {"extract", "separate"}:
        # The creation signature above remains immutable for keyed requests.
        # Cache matching instead uses the run's current retried dependencies and
        # normalized options; canonical hashes ignore dictionary key order.
        candidates = db.scalars(
            select(StageRun)
            .where(
                StageRun.workspace_id == workspace_id,
                StageRun.project_id == project.id,
                StageRun.stage == request.stage,
                StageRun.scope_key == scope,
                StageRun.target_language == request.target_language,
                StageRun.segment_id == request.segment_id,
                StageRun.dependency_fingerprint == dependency_fingerprint,
                StageRun.status.in_(
                    [
                        "succeeded",
                        "queued",
                        "running",
                        "retry_wait",
                        "failed",
                        "needs_review",
                        "cancelling",
                        "cancelled",
                    ]
                    if reuse_active or request.stage in {"extract", "separate"}
                    else ["succeeded"]
                ),
                StageRun.is_stale.is_(False),
            )
            .order_by(StageRun.created_at.desc(), StageRun.id)
        )
        options_fingerprint = fingerprint(options)
        for prior in candidates:
            from .prepared import has_prepared

            recoverable = (
                bool(prior.remote_id and prior.remote_state != "completed")
                or prior.remote_state == "submitting"
            ) or has_prepared(db, prior)
            if (
                prior.status != "succeeded"
                and not recoverable
                and (
                    prior.cancel_requested_at
                    or prior.status not in {"queued", "running", "retry_wait"}
                )
            ):
                continue
            if (
                prior.dependency_snapshot == snapshot
                and fingerprint(prior.options) == options_fingerprint
            ):
                if idempotency_key:
                    _bind_request_key(db, project, idempotency_key, request_fingerprint, prior)
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
    if idempotency_key:
        _bind_request_key(db, project, idempotency_key, request_fingerprint, run)
    append_event(db, project, "run.queued", run=run, facts={"revision": project.revision})
    return run


def _bind_request_key(db, project, key, request_fingerprint, run):
    # The project lock serializes aliases with generic and workflow enqueue paths.
    db.add(
        RunRequestKey(
            project_id=project.id,
            workspace_id=project.workspace_id,
            run_id=run.id,
            key=key,
            request_fingerprint=request_fingerprint,
        )
    )
    db.flush()


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


def _recovery_kind(db, run):
    from .prepared import current_operation

    operation = current_operation(db, run)
    if operation and operation.phase == "prepared":
        return "reuse_prepared"
    if operation and operation.phase == "terminal":
        return "resume_download"
    return "resume_remote" if run.remote_id else "rerun_local"


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
        .where(ready)
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
        if project.deleted_at is not None:
            if run.lease_token:
                _end_attempt(
                    db, run, "lease_expired", {"code": "LEASE_EXPIRED", "retryable": False}
                )
            if run.remote_id or run.remote_state == "submitting":
                run.status = "needs_review"
                run.safe_error = {"code": "SUBMISSION_UNCERTAIN", "retryable": False}
            else:
                run.status = "cancelled"
            run.finished_at = now
            _clear_lease(run)
            append_event(db, project, f"run.{run.status}", run=run)
            continue
        if run.stage not in (STAGES if registry is None else registry):
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
                facts={"recovery": _recovery_kind(db, run)},
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
    definition = get_stage(run.stage, registry)
    guard_current = definition.publication_guard(db, run) if definition.publication_guard else True
    run.result = result.facts
    if run.remote_id:
        run.remote_state = "completed"
    if run.cancel_requested_at or project.deleted_at is not None:
        run.status = "cancelled"
        run.result = None
    elif run.is_stale or not is_current(db, project, run.dependency_snapshot) or not guard_current:
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
    from ..dubbing.workflow import advance_for_run

    advance_for_run(db, run)
    run.finished_at = utcnow()
    run.safe_error = None
    _end_attempt(db, run, run.status)
    _clear_lease(run)
    append_event(db, project, f"run.{run.status}", run=run)
    return True


def fail_run(db: Session, run_id: str, token: str, failure: StageFailure) -> bool:
    project, run = _lock_run_project(db, run_id)
    if not _valid_lease(run, token, utcnow()):
        return False
    if run.remote_state == "submitting" and run.remote_id is None:
        failure = StageFailure(FailureCode.SUBMISSION_UNCERTAIN, review=True)
    run.safe_error = failure.public()
    run.auto_failures += 1
    if failure.review:
        run.status = "needs_review"
    elif run.cancel_requested_at and run.remote_id is None:
        run.status = "cancelled"
    elif run.is_stale and run.remote_id is None:
        run.status = "stale"
    elif failure.retryable and run.auto_failures < 3:
        run.status = "retry_wait"
        run.due_at = utcnow() + timedelta(seconds=min(60, 2**run.auto_failures))
    else:
        run.status = "failed"
    if run.status != "retry_wait":
        run.finished_at = utcnow()
    _end_attempt(db, run, run.status, run.safe_error)
    _clear_lease(run)
    append_event(db, project, f"run.{run.status}", run=run, facts={"code": failure.code.value})
    return True


def retry_run(
    db: Session,
    workspace_id: str,
    run_id: str,
    *,
    acknowledge_uncertain_submission=False,
    registry=None,
):
    owned = owned_run(db, workspace_id, run_id)
    project = lock_project(db, db.get(Project, owned.project_id))
    db.refresh(owned)
    if (
        owned.status not in {"failed", "stale", "needs_review", "cancelled"}
        or owned.lease_token is not None
    ):
        raise APIError(409, "RUN_ACTIVE", "Run cannot be retried while active")
    uncertain = owned.remote_state == "submitting" and owned.remote_id is None
    if uncertain and not acknowledge_uncertain_submission:
        raise APIError(
            409,
            "SUBMISSION_UNCERTAIN",
            "A previous submission may still be running; explicit acknowledgment is required",
        )
    definition = get_stage(owned.stage, registry)
    initialize_inputs(db, project)
    pending_remote = bool(owned.remote_id and owned.remote_state != "completed")
    if pending_remote:
        # A saved handle is bound to the original input snapshot. Resume polling
        # that job, and retain staleness so its old result cannot be published.
        stale = owned.is_stale or not is_current(db, project, owned.dependency_snapshot)
    else:
        request = RunCreate(
            stage=owned.stage,
            target_language=owned.target_language,
            segment_id=owned.segment_id,
            options=owned.options,
        )
        try:
            snapshot = definition.resolve_inputs(db, project, request)
        except APIError as error:
            if uncertain and acknowledge_uncertain_submission and error.code == "INPUT_REQUIRED":
                from ..dubbing.remote_translation import retire_obsolete_uncertainty

                if retire_obsolete_uncertainty(db, project, owned):
                    return owned
            raise
        from .prepared import has_prepared

        reusable = has_prepared(db, owned) and fingerprint(snapshot) == owned.dependency_fingerprint
        changed_inputs = fingerprint(snapshot) != owned.dependency_fingerprint
        if not reusable and (uncertain or owned.remote_state == "completed" or changed_inputs):
            owned.remote_state, owned.remote_id, owned.request_key = "not_submitted", None, None
            owned.provider = owned.model = None
        owned.dependency_snapshot = snapshot
        owned.dependency_fingerprint = fingerprint(snapshot)
        owned.input_project_revision = project.revision
        stale = False
    owned.status, owned.is_stale, owned.auto_failures = "queued", stale, 0
    owned.safe_error = owned.result = owned.finished_at = owned.cancel_requested_at = None
    owned.due_at = owned.updated_at = utcnow()
    append_event(db, project, "run.retried", run=owned, facts={"revision": project.revision})
    return owned


def cancel_run(db: Session, workspace_id: str, run_id: str):
    owned = owned_run(db, workspace_id, run_id)
    project = lock_project(db, db.get(Project, owned.project_id))
    db.refresh(owned)
    pending_remote = bool(owned.remote_id and owned.remote_state != "completed")
    if (
        owned.status in {"succeeded", "failed", "stale", "cancelled", "needs_review"}
        and not pending_remote
    ):
        return owned
    owned.cancel_requested_at = utcnow()
    if (
        owned.status in {"running", "cancelling"}
        or owned.remote_id
        or owned.remote_state == "submitting"
    ):
        owned.status = "cancelling"
        # retry_wait remote polling has no current lease; make it claimable for recovery.
        if owned.lease_expires_at is None:
            owned.lease_expires_at = utcnow()
            owned.due_at = utcnow()
    else:
        owned.status, owned.finished_at = "cancelled", utcnow()
    append_event(
        db,
        project,
        "run.cancel_requested" if owned.status == "cancelling" else "run.cancelled",
        run=owned,
    )
    return owned


def confirm_cancel(db: Session, run_id: str, token: str, *, remote_confirmed=False):
    project, run = _lock_run_project(db, run_id)
    if not _valid_lease(run, token, utcnow()):
        return False
    if (run.remote_id or run.remote_state == "submitting") and not remote_confirmed:
        return False
    run.status, run.finished_at, run.result = "cancelled", utcnow(), None
    if run.remote_id and remote_confirmed:
        run.remote_state = "completed"
    _end_attempt(db, run, "cancelled")
    _clear_lease(run)
    append_event(db, project, "run.cancelled", run=run)
    return True


def defer_run(db, run_id, token):
    project, run = _lock_run_project(db, run_id)
    if not _valid_lease(run, token, utcnow()):
        return False
    run.status = "retry_wait"
    run.due_at = utcnow() + timedelta(seconds=5)
    _end_attempt(db, run, "pending")
    _clear_lease(run)
    append_event(db, project, "run.pending", run=run)
    return True
