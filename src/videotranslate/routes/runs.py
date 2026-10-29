"""Private stage queue API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import APIError
from ..execution.contracts import RunCreate, RunRetry
from ..execution.service import cancel_run, create_run, owned_run, retry_run, run_json
from ..models.execution import StageRun
from ..security import Identity, require_csrf, require_identity
from .projects import owned_project

router = APIRouter(tags=["runs"])


@router.post("/projects/{project_id}/runs", status_code=201)
def enqueue(
    project_id: str,
    body: RunCreate,
    idempotency_key: Annotated[str | None, Header()] = None,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    owned_project(db, identity.workspace.id, project_id)
    if body.stage in {"transcribe", "reference"}:
        raise APIError(422, "WORKFLOW_REQUIRED", "Use the guarded workflow or reference command")
    run = create_run(db, identity.workspace.id, project_id, body, idempotency_key)
    db.commit()
    return run_json(db, run)


@router.get("/projects/{project_id}/runs")
def list_runs(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    owned_project(db, identity.workspace.id, project_id)
    query = select(StageRun).where(
        StageRun.workspace_id == identity.workspace.id, StageRun.project_id == project_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return {
        "items": [
            run_json(db, r)
            for r in db.scalars(
                query.order_by(StageRun.created_at.desc(), StageRun.id).limit(limit).offset(offset)
            )
        ],
        "total": total,
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: str, identity: Identity = Depends(require_identity), db: Session = Depends(get_db)
):
    return run_json(db, owned_run(db, identity.workspace.id, run_id), attempts=True)


@router.post("/runs/{run_id}/retry")
def retry(
    run_id: str,
    body: RunRetry,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    run = retry_run(
        db,
        identity.workspace.id,
        run_id,
        acknowledge_uncertain_submission=body.acknowledge_uncertain_submission,
    )
    db.commit()
    return run_json(db, run, attempts=True)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, identity: Identity = Depends(require_csrf), db: Session = Depends(get_db)):
    run = cancel_run(db, identity.workspace.id, run_id)
    db.commit()
    return run_json(db, run, attempts=True)
