"""Guarded full workflow commands and bounded owned cold-start discovery."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing import pipeline
from ..dubbing.ownership import owned, project_for
from ..dubbing.pipeline_contracts import (
    PipelineCAS,
    PipelineContinue,
    PipelinePolicyPut,
    PipelineScopePut,
    PipelineStart,
)
from ..models.pipeline import PipelineWorkflow
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(
    prefix="/projects/{project_id}/pipeline", tags=["pipeline"], route_class=BoundedDubbingRoute
)


@router.post("", status_code=202)
def start(
    project_id: str,
    body: PipelineStart,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    result = pipeline.start(
        db, project_for(db, identity, project_id, write=True), body, identity.user.id
    )
    db.commit()
    return result


@router.get("")
def listing(
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000000)] = 0,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return pipeline.list_workflows(db, project_for(db, identity, project_id), limit, offset)


@router.get("/current")
def current(
    project_id: str, identity: Identity = Depends(require_identity), db: Session = Depends(get_db)
):
    project = project_for(db, identity, project_id)
    workflow = db.scalar(
        pipeline.scope(PipelineWorkflow, project)
        .order_by(PipelineWorkflow.created_at.desc(), PipelineWorkflow.id)
        .limit(1)
    )
    return pipeline.detail(db, project, workflow) if workflow else None


@router.get("/{workflow_id}")
def detail(
    project_id: str,
    workflow_id: str,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    return pipeline.detail(db, project, owned(db, PipelineWorkflow, project, workflow_id))


@router.post("/{workflow_id}/continue", status_code=202)
def proceed(
    project_id: str,
    workflow_id: str,
    body: PipelineContinue,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = pipeline.continue_workflow(
        db, project, owned(db, PipelineWorkflow, project, workflow_id), body, identity.user.id
    )
    db.commit()
    return result


@router.post("/{workflow_id}/policy", status_code=202)
def policy(
    project_id: str,
    workflow_id: str,
    body: PipelinePolicyPut,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = pipeline.change_policy(
        db, project, owned(db, PipelineWorkflow, project, workflow_id), body, identity.user.id
    )
    db.commit()
    return result


@router.post("/{workflow_id}/scope", status_code=202)
def scope(
    project_id: str,
    workflow_id: str,
    body: PipelineScopePut,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = pipeline.change_scope(
        db, project, owned(db, PipelineWorkflow, project, workflow_id), body
    )
    db.commit()
    return result


@router.post("/{workflow_id}/cancel", status_code=202)
def cancel(
    project_id: str,
    workflow_id: str,
    body: PipelineCAS,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = pipeline.cancel(db, project, owned(db, PipelineWorkflow, project, workflow_id), body)
    db.commit()
    return result


@router.post("/{workflow_id}/resume", status_code=202)
def resume(
    project_id: str,
    workflow_id: str,
    body: PipelineCAS,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = pipeline.resume(db, project, owned(db, PipelineWorkflow, project, workflow_id), body)
    db.commit()
    return result
