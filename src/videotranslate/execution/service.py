"""Transactional execution mutations. Lock project before run/input/event state."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import APIError
from ..models.core import Project
from ..models.execution import RunAttempt, StageRun
from ..routes.projects import owned_project
from .contracts import RunCreate
from .events import append_event
from .inputs import fingerprint, initialize_inputs, lock_project
from .registry import get_stage


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
