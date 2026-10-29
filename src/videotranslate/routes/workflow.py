"""Explicit, CSRF protected durable workflow commands."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..dubbing.contracts import Fingerprint, Strict
from ..dubbing.ownership import owned, project_for
from ..dubbing.workflow import command, safe_workflow
from ..models.analysis import WorkflowIntent
from ..security import Identity, require_csrf, require_identity
from .dubbing import BoundedDubbingRoute

router = APIRouter(
    prefix="/projects/{project_id}/workflow", tags=["workflow"], route_class=BoundedDubbingRoute
)


class WorkflowCommand(Strict):
    action: Literal["analyse", "prepare_media"]
    expected_editor_fingerprint: Fingerprint
    auto_advance: bool = False


@router.post("", status_code=202)
def post_workflow(
    project_id: str,
    body: WorkflowCommand,
    identity: Identity = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id, write=True)
    result = command(db, project, body, identity.user.id)
    db.commit()
    return result


@router.get("/{workflow_id}")
def get_workflow(
    project_id: str,
    workflow_id: str,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    project = project_for(db, identity, project_id)
    return safe_workflow(db, project, owned(db, WorkflowIntent, project, workflow_id))
