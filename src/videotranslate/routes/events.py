"""Authorized project journal reads."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..execution.events import event_json
from ..models.execution import ProjectEvent
from ..security import Identity, require_identity
from .projects import owned_project

router = APIRouter(tags=["events"])


def event_page(db, workspace_id, project_id, after, limit):
    owned_project(db, workspace_id, project_id)
    query = select(ProjectEvent).where(
        ProjectEvent.workspace_id == workspace_id,
        ProjectEvent.project_id == project_id,
        ProjectEvent.sequence > after,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(ProjectEvent.sequence).limit(limit)).all()
    return {
        "items": [event_json(row) for row in rows],
        "total": total,
        "next_cursor": rows[-1].sequence if rows else after,
    }


@router.get("/projects/{project_id}/events")
def list_events(
    project_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    return event_page(db, identity.workspace.id, project_id, after, limit)
